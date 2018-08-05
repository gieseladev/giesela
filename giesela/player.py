import asyncio
import enum
import logging
import os
import traceback
from asyncio import AbstractEventLoop
from typing import Optional, TYPE_CHECKING

from discord import VoiceChannel, VoiceClient

from .downloader import Downloader
from .entry import BaseEntry, RadioSongEntry, StreamEntry, TimestampEntry
from .lib import EventEmitter, GieselaSource
from .queue import Queue
from .webiesela import WebieselaServer

if TYPE_CHECKING:
    from giesela import Giesela

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
        log.warning("[Config:SaveVideos] Could not delete file {}, giving up and moving on".format(os.path.relpath(filename)))


class MusicPlayer(EventEmitter):
    bot: "Giesela"
    loop: AbstractEventLoop
    downloader: Downloader

    channel: VoiceChannel
    voice_client: VoiceClient

    queue: Queue

    def __init__(self, bot: "Giesela", downloader: Downloader, channel: VoiceChannel):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.downloader = downloader

        self.channel = channel
        self.voice_client = next((voice_client for voice_client in bot.voice_clients if voice_client.guild == channel.guild), None)

        self.queue = Queue(bot, self, downloader)
        self.queue.on("entry-added", self.on_entry_added)

        self._current_entry = None

        self._volume = bot.config.default_volume

    @property
    def player(self) -> Optional[GieselaSource]:
        if self.voice_client:
            return self.voice_client.source

    @property
    def current_entry(self) -> Optional[BaseEntry]:
        return self._current_entry

    @property
    def progress(self) -> float:
        if self.player:
            return self.player.progress
        return 0

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value
        if self.player:
            self.player.volume = value

        WebieselaServer.small_update(self.voice_client.guild.id, volume=value)

    async def connect(self, **kwargs):
        if self.voice_client:
            await self.voice_client.connect(**kwargs)
        else:
            self.voice_client = await self.channel.connect(**kwargs)

    async def disconnect(self, **kwargs):
        if self.voice_client:
            await self.voice_client.disconnect(**kwargs)

    async def move_to(self, target: VoiceChannel):
        self.channel = target

        if self.voice_client:
            await self.voice_client.move_to(target)
        else:
            await self.connect()

    def on_entry_added(self, **_):
        if not self.current_entry:
            asyncio.ensure_future(self.play())

    def skip(self):
        if self.voice_client:
            self.voice_client.stop()
        asyncio.ensure_future(self.play())

    def stop(self):
        if self.voice_client:
            self.voice_client.stop()

        self.emit("stop", player=self)

    def resume(self):
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.emit("resume", player=self, entry=self.current_entry)
            return

    def seek(self, secs: float):
        if self.player:
            self.player.seek(secs)
        self.emit("play", player=self, entry=self.current_entry)

    def pause(self):
        if isinstance(self.current_entry, StreamEntry):
            self.stop()
            return

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.emit("pause", player=self, entry=self.current_entry)

    def kill(self):
        if self.voice_client:
            self.voice_client.stop()
        self.queue.clear()
        self._events.clear()

    def _playback_finished(self, error: Exception = None):
        log.debug("playback finished")

        if error:
            log.exception("Playback error")

        entry = self.current_entry
        self.queue.push_history(entry)
        self._current_entry = None

        if not self.bot.config.save_videos and entry:
            if any([entry.filename == e.filename for e in self.queue.entries]):
                print("[Config:SaveVideos] Skipping deletion, found song in queue")
            else:
                asyncio.ensure_future(_delete_file(entry.filename))

        self.emit("finished-playing", player=self, entry=entry)

        if self.voice_client and self.voice_client.is_connected():
            self.loop.create_task(self.play())
        else:
            log.info("disconnected")

    def create_source(self, entry: BaseEntry) -> GieselaSource:
        return GieselaSource(entry.filename, self.volume)

    async def play(self, entry: BaseEntry = None):
        if not self.voice_client:
            await self.connect()

        if self.voice_client.is_paused():
            self.resume()
            return

        if not entry:
            entry = await self.queue.get_next_entry()

        if not entry:
            log.debug("queue empty")
            return

        await entry.get_ready_future()

        self._current_entry = entry
        source = self.create_source(entry)

        self.voice_client.play(source, after=self._playback_finished)
        log.info(f"playing {entry} in {self.voice_client}")
        self.emit("play", player=self, entry=entry)

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
