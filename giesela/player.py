import asyncio
import enum
import logging
import os
import subprocess
import sys
import traceback
from threading import Thread
from typing import TYPE_CHECKING

from discord import VoiceChannel

from giesela.entry import RadioSongEntry, StreamEntry, TimestampEntry
from giesela.exceptions import FFmpegError, FFmpegWarning
from giesela.lib import EventEmitter
from giesela.queue import Queue
from giesela.utils import create_cmd_params, format_time_ffmpeg
from giesela.webiesela import WebieselaServer

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class RepeatState(enum.IntEnum):
    NONE = 0  # queue plays as normal
    ALL = 1  # Entire queue repeats
    SINGLE = 2  # Currently playing song repeats forever

    def __str__(self):
        return self.name


async def _delete_file(filename):
    for x in range(30):
        try:
            os.unlink(filename)
            break

        except PermissionError as e:
            if e.errno == 32:  # File is in use
                await asyncio.sleep(0.25)

        except Exception:
            traceback.print_exc()
            print("Error trying to delete " + filename)
            break
    else:
        print("[Config:SaveVideos] Could not delete file {}, giving up and moving on".format(
            os.path.relpath(filename)))


class MusicPlayer(EventEmitter):

    def __init__(self, bot, channel: VoiceChannel):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.channel = channel
        self.voice_client = None

        self.queue = Queue(bot, self)
        self.queue.on("entry-added", self.on_entry_added)

        self._play_lock = asyncio.Lock()
        self._current_player = None
        self._current_entry = None
        self.repeat_state = RepeatState.NONE

        self.volume = bot.config.default_volume
        self.chapter_updater = None

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value
        if self._current_player:
            self._current_player.buff.volume = value

        WebieselaServer.small_update(self.voice_client.guild.id, volume=value)

    def on_entry_added(self):
        if self.is_stopped:
            self.loop.call_later(2, self.play)

    def skip(self):
        self.skipRepeat = True
        self._kill_current_player()
        self.update_chapter_updater()

    def repeat(self):
        if self.is_repeat_none:
            self.repeatState = MusicPlayerRepeatState.ALL
        elif self.is_repeat_all:
            self.repeatState = MusicPlayerRepeatState.SINGLE
        elif self.is_repeat_single:
            self.repeatState = MusicPlayerRepeatState.NONE
        else:
            # no idea how that should happen but eh...
            return False

        WebieselaServer.small_update(self.voice_client.guild.id, repeat_state=self.repeatState.value, repeat_state_name=str(self.repeatState))
        return True

    def stop(self):
        self.state = MusicPlayerState.STOPPED
        self._kill_current_player()

        self.emit("stop", player=self)

    def resume(self):
        if self.is_paused and self._current_player:
            self._current_player.resume()
            self.update_chapter_updater()
            self.state = MusicPlayerState.PLAYING
            self.emit("resume", player=self, entry=self.current_entry)
            return

        if self.is_paused and not self._current_player:
            self.state = MusicPlayerState.PLAYING
            self._kill_current_player()
            return

        raise ValueError("Cannot resume playback from state %s" % self.state)

    def seek(self, secs):
        if (not self.current_entry) or secs >= self.current_entry.end_seconds:
            print("[PLAYER] Seek target out of bounds, skipping!")
            self.skip()
            return True

        secs = max(0, secs)

        entry = self.current_entry
        if not entry.seek(secs):
            print("[PLAYER] Couldn't set start of entry")
            return False

        self.handle_manually = True
        self.play_entry(entry)
        self.emit("play", player=self, entry=entry)
        return True

    def set_filters(self, filters):
        if not self.current_entry:
            return False

        entry = self.current_entry
        entry.set_start(self.progress)

        if not filters:
            entry.meta.pop("filters", None)
        else:
            entry.meta["filters"] = filters

        self.handle_manually = True
        self.play_entry(entry)
        self.emit("play", player=self, entry=entry)
        return True

    def pause(self):
        if isinstance(self.current_entry, StreamEntry):
            print("Won't pause because I'm playing a stream")
            self.stop()
            return

        if self.is_playing:
            self.state = MusicPlayerState.PAUSED

            if self._current_player:
                self._current_player.pause()
                self.update_chapter_updater(pause=True)

            self.emit("pause", player=self, entry=self.current_entry)
            return

        elif self.is_paused:
            return

        raise ValueError("Cannot pause a MusicPlayer in state %s" % self.state)

    def kill(self):
        self.state = MusicPlayerState.DEAD
        self.queue.clear()
        self._events.clear()
        self._kill_current_player()

    def _playback_finished(self):
        if self.handle_manually:
            self.handle_manually = False
            return

        entry = self._current_entry

        self.queue.push_history(entry)

        if self.is_repeat_all or (self.is_repeat_single and not self.skipRepeat):
            self.queue._add_entry(entry, placement=0)
        self.skipRepeat = False

        if self._current_player:
            self._current_player.after = None
            self._kill_current_player()

        self._current_entry = None

        if not self.is_stopped and not self.is_dead:
            self.play(_continue=True)

        if not self.bot.config.save_videos and entry:
            if any([entry.filename == e.filename for e in self.queue.entries]):
                print("[Config:SaveVideos] Skipping deletion, found song in queue")

            else:
                asyncio.ensure_future(_delete_file(entry.filename))

        self.emit("finished-playing", player=self, entry=entry)

    def _kill_current_player(self):
        if self._current_player:
            if self.is_paused:
                self.resume()

            try:
                self._current_player.stop()
            except OSError:
                pass
            self._current_player = None
            return True

        return False

    def play(self, _continue=False):
        self.loop.create_task(self._play(_continue=_continue))

    async def _play(self, _continue=False):
        """
            Plays the next entry from the Queue, or resumes playback of the current entry if paused.
        """
        if self.is_paused:
            return self.resume()

        if self.is_dead:
            return

        if self.is_stopped or _continue:
            try:
                entry = await self.queue.get_next_entry()

            except Exception:
                print("Failed to get entry.")
                traceback.print_exc()
                # Retry playing the next entry in a sec.
                self.loop.call_later(0.1, self.play)
                return

            # If nothing left to play, transition to the stopped state.
            if not entry:
                self.stop()
                return

            await self._play_entry(entry)
            self.emit("play", player=self, entry=entry)

    def play_entry(self, entry):
        self.loop.create_task(self._play_entry(entry))

    async def _play_entry(self, entry):
        """
            Play the entry
        """

        if self.is_dead:
            return

        with await self._play_lock:
            # In-case there was a player, kill it. RIP.
            self._kill_current_player()

            before_options = {
                "nostdin": None
            }
            options = {
                "vn": None,
                "b:a": "128k"
            }

            if not isinstance(entry, StreamEntry):
                start_seconds = int(entry.start_seconds)

                before_options["ss"] = format_time_ffmpeg(start_seconds)
                options["to"] = format_time_ffmpeg(int(entry.end_seconds) - start_seconds)

            if "filters" in entry.meta:
                options.update({
                    "filter:a": "\"" + ",".join(entry.meta["filters"]) + "\""
                })

            self._current_player = _monkeypatch_player(self.voice_client.create_ffmpeg_player(
                entry.filename,
                before_options=create_cmd_params(before_options),
                options=create_cmd_params(options),
                stderr=subprocess.PIPE,
                after=lambda: self.loop.call_soon_threadsafe(
                    self._playback_finished)
            ))
            self._current_player.setDaemon(True)
            self._current_player.buff.volume = self._volume

            self.state = MusicPlayerState.PLAYING
            self._current_entry = entry
            self._stderr_future = asyncio.Future()

            stderr_thread = Thread(
                target=filter_stderr,
                args=(self._current_player.process, self._stderr_future),
                name="{} stderr reader".format(self._current_player.name)
            )

            stderr_thread.start()
            self._current_player.start()
            self.update_chapter_updater()

    def update_chapter_updater(self, pause=False):
        if self.chapter_updater:
            print("[CHAPTER-UPDATER] Cancelling old updater")
            self.chapter_updater.cancel()

        if not pause and isinstance(self.current_entry, (RadioSongEntry, TimestampEntry)):
            print("[CHAPTER-UPDATER] Creating new updater")
            self.chapter_updater = asyncio.ensure_future(self.update_chapter(), loop=self.loop)

    async def update_chapter(self):
        while True:
            if self.current_entry:
                if isinstance(self.current_entry, TimestampEntry):
                    sub_entry = self.current_entry.current_sub_entry
                    # just to be sure, add an extra 2 seconds
                    delay = (sub_entry["duration"] - sub_entry["progress"]) + 2

                elif isinstance(self.current_entry, RadioSongEntry):
                    if self.current_entry.poll_time:
                        print("[CHAPTER-UPDATER] this radio stations enforces a custom wait time")

                        delay = self.current_entry.poll_time
                    elif self.current_entry.song_duration > 5:
                        delay = self.current_entry.song_duration - self.current_entry.song_progress + self.current_entry.uncertainty
                        if delay <= 0:
                            delay = 40
                    else:
                        delay = 40
                else:
                    return  # this is not the kind of entry that requires an update
            else:
                print("[CHAPTER-UPDATER] There's nothing playing")
                return

            print("[CHAPTER-UPDATER] Waiting " + str(round(delay, 1)) +
                  " seconds before emitting now playing event")

            before_title = self.current_entry.title

            await asyncio.sleep(delay)
            if not self.current_entry:
                # print("[CHAPTER-UPDATER] Waited for nothing. There's nothing playing anymore")
                return

            if self.current_entry.title == before_title:
                print(
                    "[CHAPTER-UPDATER] The same thing is still playing. Back to sleep!")
                continue

            print("[CHAPTER-UPDATER] Emitting next now playing event")
            self.emit("play", player=self, entry=self.current_entry)

    @property
    def current_entry(self):
        return self._current_entry

    @property
    def is_repeat_none(self):
        return self.repeatState == MusicPlayerRepeatState.NONE

    @property
    def is_repeat_all(self):
        return self.repeatState == MusicPlayerRepeatState.ALL

    @property
    def is_repeat_single(self):
        return self.repeatState == MusicPlayerRepeatState.SINGLE

    @property
    def is_playing(self):
        return self.state == MusicPlayerState.PLAYING

    @property
    def is_paused(self):
        return self.state == MusicPlayerState.PAUSED

    @property
    def is_stopped(self):
        return self.state == MusicPlayerState.STOPPED

    @property
    def is_dead(self):
        return self.state == MusicPlayerState.DEAD

    @property
    def progress(self):
        secs = 0

        if self._current_player:
            secs = round(self._current_player.buff.frame_count * 0.02)

        if self.current_entry.start_seconds:
            secs += self.current_entry.start_seconds

        return secs


def filter_stderr(popen: subprocess.Popen, future: asyncio.Future):
    last_ex = None

    while True:
        data = popen.stderr.readline()
        if data:
            print("Data from ffmpeg: {}".format(data))
            try:
                if check_stderr(data):
                    sys.stderr.buffer.write(data)
                    sys.stderr.buffer.flush()

            except FFmpegError as e:
                print("Error from ffmpeg: %s", str(e).strip())
                last_ex = e

            except FFmpegWarning:
                pass  # useless message
        else:
            break

    if last_ex:
        future.set_exception(last_ex)
    else:
        future.set_result(True)


def check_stderr(data: bytes):
    try:
        data = data.decode("utf8")
    except:
        print("Unknown error decoding message from ffmpeg")
        return True  # duck it

    warnings = [
        "Header missing",
        "Estimating duration from birate, this may be inaccurate",
        "Using AVStream.codec to pass codec parameters to muxers is deprecated, use AVStream.codecpar instead.",
        "Application provided invalid, non monotonically increasing dts to muxer in stream",
        "Last message repeated",
        "Failed to send close message",
        "decode_band_types: Input buffer exhausted before END element found"
    ]
    errors = [
        # need to regex this properly, its both a warning and an error
        "Invalid data found when processing input",
    ]

    if any(msg in data for msg in warnings):
        raise FFmpegWarning(data)

    if any(msg in data for msg in errors):
        raise FFmpegError(data)

    return True
