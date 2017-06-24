import asyncio
import audioop
import os
import subprocess
import sys
import traceback
from array import array
from collections import deque
from enum import Enum
from shutil import get_terminal_size
from threading import Thread

from .entry import StreamPlaylistEntry
from .exceptions import FFmpegError, FFmpegWarning
from .lib.event_emitter import EventEmitter
from .logger import log
from .radio import Radio
from .utils import format_time_ffmpeg


class PatchedBuff:
    """
        PatchedBuff monkey patches a readable object, allowing you to vary what the volume is as the song is playing.
    """

    def __init__(self, buff, *, draw=False):
        self.buff = buff
        self.frame_count = 0
        self.volume = 1.0

        self.draw = draw
        self.use_audioop = True
        self.frame_skip = 2
        self.rmss = deque([2048], maxlen=90)

    def __del__(self):
        if self.draw:
            log(' ' * (get_terminal_size().columns - 1), end='\r')

    def read(self, frame_size):
        self.frame_count += 1

        frame = self.buff.read(frame_size)

        if self.volume != 1:
            frame = self._frame_vol(frame, self.volume, maxv=2)

        if self.draw and not self.frame_count % self.frame_skip:
            # these should be processed for every frame, but "overhead"
            rms = audioop.rms(frame, 2)
            self.rmss.append(rms)

            max_rms = sorted(self.rmss)[-1]
            meter_text = 'avg rms: ***REMOVED***:.2f***REMOVED***, max rms: ***REMOVED***:.2f***REMOVED*** '.format(
                self._avg(self.rmss), max_rms)
            self._pprint_meter(rms / max(1, max_rms),
                               text=meter_text, shift=True)

        return frame

    def _frame_vol(self, frame, mult, *, maxv=2, use_audioop=True):
        if use_audioop:
            return audioop.mul(frame, 2, min(mult, maxv))
        else:
            # ffmpeg returns s16le pcm frames.
            frame_array = array('h', frame)

            for i in range(len(frame_array)):
                frame_array[i] = int(frame_array[i] * min(mult, min(1, maxv)))

            return frame_array.tobytes()

    def _avg(self, i):
        return sum(i) / len(i)

    def _pprint_meter(self, perc, *, char='#', text='', shift=True):
        tx, ty = get_terminal_size()

        if shift:
            outstr = text + \
                "***REMOVED******REMOVED***".format(char * (int((tx - len(text)) * perc) - 1))
        else:
            outstr = text + \
                "***REMOVED******REMOVED***".format(char * (int(tx * perc) - 1))[len(text):]

        log(outstr.ljust(tx - 1), end='\r')


class MusicPlayerState(Enum):
    STOPPED = 0  # When the player isn't playing anything
    PLAYING = 1  # The player is actively playing music.
    PAUSED = 2   # The player is paused on a song.
    WAITING = 3  # The player has finished its song but is still downloading the next one
    DEAD = 4     # The player has been killed.

    def __str__(self):
        return self.name


class MusicPlayerRepeatState(Enum):
    NONE = 0    # Playlist plays as normal
    ALL = 1     # Entire playlist repeats
    SINGLE = 2  # Currently playing song repeats

    def __str__(self):
        return self.name


class MusicPlayer(EventEmitter):

    def __init__(self, bot, voice_client, playlist):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.voice_client = voice_client
        self.playlist = playlist
        self.playlist.on('entry-added', self.on_entry_added)

        self._play_lock = asyncio.Lock()
        self._current_player = None
        self._current_entry = None
        self.state = MusicPlayerState.STOPPED
        self.repeatState = MusicPlayerRepeatState.NONE
        self.skipRepeat = False

        self.loop.create_task(self.websocket_check())
        self.bot.socket_server.threaded_broadcast_information()
        self.handle_manually = False

        self.volume_scale = 1  # volume is divided by this value
        self.volume = bot.config.default_volume

    @property
    def volume(self):
        return self._volume * self.volume_scale

    @volume.setter
    def volume(self, value):
        value /= self.volume_scale
        self._volume = value
        if self._current_player:
            self._current_player.buff.volume = value

        self.bot.socket_server.threaded_broadcast_information()

    def on_entry_added(self, playlist, entry):
        if self.is_stopped:
            self.loop.call_later(2, self.play)

    def skip(self):
        self.skipRepeat = True
        self._kill_current_player()

    def repeat(self):
        if self.is_repeatNone:
            self.repeatState = MusicPlayerRepeatState.ALL
            return
        if self.is_repeatAll:
            self.repeatState = MusicPlayerRepeatState.SINGLE
            return
        if self.is_repeatSingle:
            self.repeatState = MusicPlayerRepeatState.NONE
            return

    def stop(self):
        self.state = MusicPlayerState.STOPPED
        self._kill_current_player()

        self.emit('stop', player=self)

    def resume(self):
        if self.is_paused and self._current_player:
            self._current_player.resume()
            self.state = MusicPlayerState.PLAYING
            self.emit('resume', player=self, entry=self.current_entry)
            self.bot.socket_server.threaded_broadcast_information()
            return

        if self.is_paused and not self._current_player:
            self.state = MusicPlayerState.PLAYING
            self._kill_current_player()
            return

        raise ValueError('Cannot resume playback from state %s' % self.state)

    def goto_seconds(self, secs):
        if (not self.current_entry) or secs >= self.current_entry.duration or (self.current_entry.end_seconds is not None and secs >= self.current_entry.end_seconds):
            self.skip()
            return True

        secs = max(0, secs)

        c_entry = self.current_entry
        if not c_entry.set_start(secs):
            return False

        self.play_entry(c_entry)
        return True

    def pause(self):
        if type(self.current_entry).__name__ == "StreamPlaylistEntry":
            log("Won't pause because I'm playing a stream")
            self.stop()
            self.bot.socket_server.threaded_broadcast_information()
            return

        if self.is_playing:
            self.state = MusicPlayerState.PAUSED

            if self._current_player:
                self._current_player.pause()

            self.emit('pause', player=self, entry=self.current_entry)
            self.bot.socket_server.threaded_broadcast_information()
            return

        elif self.is_paused:
            return

        raise ValueError('Cannot pause a MusicPlayer in state %s' % self.state)

    def kill(self):
        self.state = MusicPlayerState.DEAD
        self.playlist.clear()
        self._events.clear()
        self._kill_current_player()
        self.bot.socket_server.threaded_broadcast_information()

    def _playback_finished(self):
        if self.handle_manually:
            self.handle_manually = False
            return

        entry = self._current_entry

        self.playlist.push_history(entry)

        if self.is_repeatAll or (self.is_repeatSingle and not self.skipRepeat):
            self.playlist._add_entry(entry)
            if self.is_repeatSingle:
                self.playlist.promote_last()
        self.skipRepeat = False

        if self._current_player:
            self._current_player.after = None
            self._kill_current_player()

        self._current_entry = None

        if not self.is_stopped and not self.is_dead:
            self.play(_continue=True)

        if not self.bot.config.save_videos and entry:
            if any([entry.filename == e.filename for e in self.playlist.entries]):
                log("[Config:SaveVideos] Skipping deletion, found song in queue")

            else:
                # log("[Config:SaveVideos] Deleting file: %s" % os.path.relpath(entry.filename))
                asyncio.ensure_future(self._delete_file(entry.filename))

        self.emit('finished-playing', player=self, entry=entry)

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

    async def _delete_file(self, filename):
        for x in range(30):
            try:
                os.unlink(filename)
                break

            except PermissionError as e:
                if e.winerror == 32:  # File is in use
                    await asyncio.sleep(0.25)

            except Exception as e:
                traceback.print_exc()
                log("Error trying to delete " + filename)
                break
        else:
            log("[Config:SaveVideos] Could not delete file ***REMOVED******REMOVED***, giving up and moving on".format(
                os.path.relpath(filename)))

    def play(self, _continue=False):
        self.loop.create_task(self._play(_continue=_continue))

    async def _play(self, _continue=False):
        """
            Plays the next entry from the playlist, or resumes playback of the current entry if paused.
        """
        if self.is_paused:
            return self.resume()

        if self.is_dead:
            return

        with await self._play_lock:
            if self.is_stopped or _continue:
                try:
                    entry = await self.playlist.get_next_entry()

                except Exception as e:
                    log("Failed to get entry.")
                    traceback.print_exc()
                    # Retry playing the next entry in a sec.
                    self.loop.call_later(0.1, self.play)
                    return

                # If nothing left to play, transition to the stopped state.
                if not entry:
                    self.stop()
                    return

                # In-case there was a player, kill it. RIP.
                self._kill_current_player()

                self._current_player = self._monkeypatch_player(self.voice_client.create_ffmpeg_player(
                    entry.filename,
                    before_options="-nostdin -ss ***REMOVED******REMOVED***".format(
                        format_time_ffmpeg(int(entry.start_seconds))),
                    # before_options="-nostdin",
                    options="-vn -to ***REMOVED******REMOVED*** -b:a 128k".format(format_time_ffmpeg(
                        int(entry.end_seconds - entry.start_seconds))) if entry.end_seconds is not None else "-vn -b:a 128k",
                    # options="-vn -b:a 128k",
                    stderr=subprocess.PIPE,
                    # Threadsafe call soon, b/c after will be called from the
                    # voice playback thread.
                    after=lambda: self.loop.call_soon_threadsafe(
                        self._playback_finished)
                ))
                self._current_player.setDaemon(True)
                self._current_player.buff.volume = self._volume

                # I need to add ytdl hooks
                self.state = MusicPlayerState.PLAYING
                self._current_entry = entry
                self._stderr_future = asyncio.Future()

                stderr_thread = Thread(
                    target=filter_stderr,
                    args=(self._current_player.process, self._stderr_future),
                    name="***REMOVED******REMOVED*** stderr reader".format(self._current_player.name)
                )

                stderr_thread.start()
                self._current_player.start()
                self.emit('play', player=self, entry=entry)
                self.bot.socket_server.threaded_broadcast_information()
                asyncio.ensure_future(self.update_timestamp())

    async def _absolute_current_song(self):
        if not self.current_entry:
            return None
        if type(self.current_entry) == StreamPlaylistEntry:
            if self.current_entry.radio_station_data:
                data = await Radio.get_current_song(self.loop, self.current_entry.radio_station_data.name)
                if data:
                    return data["title"]  # it's title, not name idiot
        elif self.current_entry.provides_timestamps:
            try:
                return self.current_entry.get_current_song_from_timestamp(self.progress)["name"]
            except:
                pass

        return self.current_entry._title

    async def update_timestamp(self, delay=None):
        if not delay:
            if self.current_entry:
                if self.current_entry.provides_timestamps:
                    prg, dur = self.current_entry.get_local_progress(
                        self.progress)
                    # just to be sure, add an extra 2 seconds
                    next_delay = (dur - prg) + 2
                    return await self.update_timestamp(next_delay)

                elif type(self.current_entry) == StreamPlaylistEntry:
                    if self.current_entry.radio_station_data:
                        next_delay = 40  # I don't want this to be too fast...
                        if Radio.has_station_data(self.current_entry.radio_station_data.name):
                            data = await Radio.get_current_song(
                                self.bot.loop, self.current_entry.radio_station_data.name)
                            # proto sounds cool, doesn't it?
                            proto_delay = (data["duration"] - data["progress"])
                            # just making sure that it's not somehow ducked up
                            # (like capitalfm)
                            if proto_delay > 0:
                                next_delay = proto_delay + 2  # adding those extra 2 seconds just to be safe
                        return await self.update_timestamp(next_delay)

                return  # this is not the kind of entry that requires an update
            else:
                print("[TIMESTAMP-ENTRY] Not going to emit another now playing event")
                return

        print("[TIMESTAMP-ENTRY] Waiting for " + str(delay) +
              " seconds before emitting now playing event")
        before_data = ***REMOVED***"url": self.current_entry.url, "song_name": await self._absolute_current_song()***REMOVED***
        expected_progress = self.progress + delay

        # print("I expect to have a progress of ***REMOVED******REMOVED*** once I wake up".format(expected_progress))
        await asyncio.sleep(delay)
        if not self.current_entry:
            return
        # gotta be sure to be on the same entry but not on the same sub entry
        if not (self.current_entry.url == before_data["url"] and await self._absolute_current_song() != before_data["song_name"]):
            print("[TIMESTAMP-ENTRY] nothing's changed since last time!")
        else:
            # print("Expected: ***REMOVED******REMOVED***, Got: ***REMOVED******REMOVED***".format(expected_progress, self.progress))
            if not ((expected_progress + .75) > self.progress > (expected_progress - .75)):
                print("[TIMESTAMP-ENTRY] Expected progress ***REMOVED******REMOVED*** but got ***REMOVED******REMOVED***; assuming there's already another one running".format(
                    expected_progress, self.progress))
                return
            print("[TIMESTAMP-ENTRY] Emitting next now playing event")
            self.emit('play', player=self, entry=self.current_entry)
        await self.update_timestamp()

    def play_entry(self, entry):
        self.loop.create_task(self._play_entry(entry))

    async def _play_entry(self, entry):
        self.handle_manually = True

        if self.is_dead:
            log("ded")
            return

        with await self._play_lock:
            # In-case there was a player, kill it. RIP.
            self._kill_current_player()

            self._current_player = self._monkeypatch_player(self.voice_client.create_ffmpeg_player(
                entry.filename,
                before_options="-nostdin -ss ***REMOVED******REMOVED***".format(
                    format_time_ffmpeg(int(entry.start_seconds))),
                # before_options="-nostdin",
                options="-vn -to ***REMOVED******REMOVED*** -b:a 128k".format(format_time_ffmpeg(
                    int(entry.end_seconds - entry.start_seconds))) if entry.end_seconds is not None else "-vn -b:a 128k",
                # options="-vn -b:a 128k",
                stderr=subprocess.PIPE,
                # Threadsafe call soon, b/c after will be called from the
                # voice playback thread.
                after=lambda: self.loop.call_soon_threadsafe(
                    self._playback_finished)
            ))
            self._current_player.setDaemon(True)
            self._current_player.buff.volume = self._volume

            # I need to add ytdl hooks
            self.state = MusicPlayerState.PLAYING
            self._current_entry = entry
            self._stderr_future = asyncio.Future()

            stderr_thread = Thread(
                target=filter_stderr,
                args=(self._current_player.process, self._stderr_future),
                name="***REMOVED******REMOVED*** stderr reader".format(self._current_player.name)
            )

            stderr_thread.start()
            self._current_player.start()
            self.emit('play', player=self, entry=entry)
            self.bot.socket_server.threaded_broadcast_information()
            asyncio.ensure_future(self.update_timestamp())

    def _monkeypatch_player(self, player):
        original_buff = player.buff
        player.buff = PatchedBuff(original_buff)
        return player

    def reload_voice(self, voice_client):
        self.voice_client = voice_client
        if self._current_player:
            self._current_player.player = voice_client.play_audio
            self._current_player._resumed.clear()
            self._current_player._connected.set()

    async def websocket_check(self):
        if self.bot.config.debug_mode:
            log("[Debug] Creating websocket check loop")

        while not self.is_dead:
            try:
                self.voice_client.ws.ensure_open()
                assert self.voice_client.ws.open
            except:
                if self.bot.config.debug_mode:
                    log("[Debug] Voice websocket is %s, reconnecting" %
                        self.voice_client.ws.state_name)
                await self.bot.reconnect_voice_client(self.voice_client.channel.server)
                await asyncio.sleep(4)
            finally:
                await asyncio.sleep(1)

    @property
    def current_entry(self):
        return self._current_entry

    @property
    def is_repeatNone(self):
        return self.repeatState == MusicPlayerRepeatState.NONE

    @property
    def is_repeatAll(self):
        return self.repeatState == MusicPlayerRepeatState.ALL

    @property
    def is_repeatSingle(self):
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
        return round(self._current_player.buff.frame_count * 0.02) + (self.current_entry.start_seconds if self.current_entry is not None else 0)
        # TODO: Properly implement this
        #       Correct calculation should be bytes_read/192k
        #       192k AKA sampleRate * (bitDepth / 8) * channelCount
        #       Change frame_count to bytes_read in the PatchedBuff


def filter_stderr(popen: subprocess.Popen, future: asyncio.Future):
    last_ex = None

    while True:
        data = popen.stderr.readline()
        if data:
            log("Data from ffmpeg: ***REMOVED******REMOVED***".format(data))
            try:
                if check_stderr(data):
                    sys.stderr.buffer.write(data)
                    sys.stderr.buffer.flush()

            except FFmpegError as e:
                log("Error from ffmpeg: %s", str(e).strip())
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
        data = data.decode('utf8')
    except:
        log("Unknown error decoding message from ffmpeg", exc_info=True)
        return True  # fuck it

    # log.ffmpeg("Decoded data from ffmpeg: ***REMOVED******REMOVED***".format(data))

    # TODO: Regex
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
# if redistributing ffmpeg is an issue, it can be downloaded from here:
#  - http://ffmpeg.zeranoe.com/builds/win32/static/ffmpeg-latest-win32-static.7z
#  - http://ffmpeg.zeranoe.com/builds/win64/static/ffmpeg-latest-win64-static.7z
#
# Extracting bin/ffmpeg.exe, bin/ffplay.exe, and bin/ffprobe.exe should be fine
# However, the files are in 7z format so meh
# I don't know if we can even do this for the user, at most we open it in the browser
# I can't imagine the user is so incompetent that they can't pull 3 files out of it...
# ...
# ...right?

# Get duration with ffprobe
#   ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -sexagesimal filename.mp3
# This is also how I fix the format checking issue for now
# ffprobe -v quiet -print_format json -show_format stream

# Normalization filter
# -af dynaudnorm
