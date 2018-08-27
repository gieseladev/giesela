import asyncio
import logging
import os
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


async def _delete_file(filename):
    for x in range(30):
        try:
            os.unlink(filename)
            break

        except PermissionError as e:
            if e.errno == 32:  # File is in use
                await asyncio.sleep(0.25)

        except Exception:
            log.exception(f"Error trying to delete {filename}")
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

    _current_entry: Optional[BaseEntry]
    _volume: float

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

    def __str__(self) -> str:
        playing = f"playing {self.current_entry}" if self.is_playing else ""
        return f"<MusicPlayer for {self.vc_qualified_name} {playing}>"

    @property
    def vc_qualified_name(self) -> str:
        return f"{self.channel.guild.name}#{self.channel.name}"

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

    @property
    def is_playing(self) -> bool:
        return self.voice_client and self.voice_client.is_playing()

    @property
    def is_paused(self) -> bool:
        return self.voice_client and self.voice_client.is_paused()

    @property
    def is_stopped(self) -> bool:
        return not bool(self.player)

    @property
    def state(self) -> int:
        return 1 if self.is_playing else 2 if self.is_paused else 0

    @property
    def connected(self) -> bool:
        return self.voice_client and self.voice_client.is_connected()

    @property
    def voice_channel(self) -> VoiceChannel:
        return self.bot.get_channel(self.channel.id)

    async def connect(self, **kwargs):
        if self.voice_client:
            await self.voice_client.connect(**kwargs)
        else:
            self.voice_client = await self.channel.connect(**kwargs)

    async def disconnect(self, **kwargs):
        if self.voice_client:
            self.stop()
            await self.voice_client.disconnect(**kwargs)
            self.voice_client = None
        self.emit("disconnect", player=self)

    async def move_to(self, target: VoiceChannel):
        self.channel = target

        if self.voice_client:
            await self.voice_client.move_to(target)
            self.channel = target
        else:
            await self.connect()

    def on_entry_added(self, **_):
        if not self.current_entry:
            self.loop.create_task(self.play())

    def skip(self, force: bool = False):
        if self.voice_client:
            if not force and isinstance(self.current_entry, TimestampEntry):
                sub_entry = self.current_entry.get_sub_entry(self)
                self.seek(sub_entry["end"])
            else:
                self.voice_client.stop()

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
        if isinstance(self.current_entry, StreamEntry):
            return

        if self.player:
            self.player.seek(secs)
        self.emit("seek", player=self, entry=self.current_entry, timestamp=secs)

    def pause(self):
        if isinstance(self.current_entry, StreamEntry):
            return self.stop()

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.emit("pause", player=self, entry=self.current_entry)

    def modify_current_entry(self, entry: BaseEntry):
        if not self.current_entry:
            raise ValueError("No current entry")
        if self.current_entry.url != entry.url:
            raise ValueError("Edited entry doesn't share current entry's url")

        self._current_entry = entry
        self.emit("play", player=self, entry=entry)

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
        if entry:
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
            self.stop()
            return

        await entry.get_ready_future(self.queue)

        self._current_entry = entry
        source = self.create_source(entry)

        if self.voice_client.is_playing():
            self.voice_client.source = source
        else:
            self.voice_client.play(source, after=self._playback_finished)
        self.setup_chapters()

        log.info(f"playing {entry} in {self.vc_qualified_name}")
        self.emit("play", player=self, entry=entry)

    def setup_chapters(self):
        if isinstance(self.current_entry, TimestampEntry):
            sub_queue = self.current_entry.sub_queue
            for sub_entry in sub_queue:
                self.player.wait_for_timestamp(sub_entry["start"], only_when_latest=True, target=self.update_chapter)
        elif isinstance(self.current_entry, RadioSongEntry):
            delay = None
            if self.current_entry.poll_time:
                delay = self.current_entry.poll_time
                log.debug(f"Radio stations enforces a custom wait time ({delay}s)")
            elif self.current_entry.song_duration and self.current_entry.song_duration > self.current_entry.uncertainty:
                delay = self.current_entry.song_duration - self.current_entry.song_progress + self.current_entry.uncertainty

            delay = delay if delay and delay > 0 else 40
            self.loop.call_later(delay, self.repeat_chapter_setup)

    def repeat_chapter_setup(self):
        asyncio.ensure_future(self.update_chapter())
        self.setup_chapters()

    async def update_chapter(self):
        self.emit("play", player=self, entry=self.current_entry)
