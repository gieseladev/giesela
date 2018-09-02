import asyncio
import logging
from asyncio import AbstractEventLoop
from typing import Any, Dict, Optional, TYPE_CHECKING, Union

from discord import Guild, VoiceChannel, VoiceClient

from .downloader import Downloader
from .entry import BaseEntry, RadioSongEntry, StreamEntry, TimestampEntry
from .lib import EventEmitter, GieselaSource
from .queue import Queue

if TYPE_CHECKING:
    from giesela import Giesela

log = logging.getLogger(__name__)


class LavalinkPlayer(EventEmitter):
    bot: "Giesela"
    loop: AbstractEventLoop

    _channel: VoiceChannel
    voice_client: VoiceClient

    queue: Queue

    _current_entry: Optional[BaseEntry]
    _volume: float

    def __init__(self, bot: "Giesela", downloader: Downloader, channel: VoiceChannel):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.downloader = downloader

        self._channel = channel
        self.voice_client = next((voice_client for voice_client in bot.voice_clients if voice_client.guild == channel.guild), None)

        self.queue = Queue(bot, self, downloader)
        self.queue.on("entry-added", self.on_entry_added)

        self._current_entry = None

        self._volume = bot.config.default_volume

    def __str__(self) -> str:
        playing = f"playing {self.current_entry}" if self.is_playing else ""
        return f"<MusicPlayer for {self.vc_qualified_name} {playing}>"

    @property
    def channel(self) -> VoiceChannel:
        return self._channel

    @channel.setter
    def channel(self, value: Union[int, VoiceChannel]):
        if isinstance(value, int):
            value = self.bot.get_channel(value)
        if not isinstance(value, VoiceChannel):
            raise TypeError(f"{value} isn't a voice channel")

        self._channel = value

    @property
    def vc_qualified_name(self) -> str:
        return f"{self.channel.guild.name}#{self.channel.name}"

    @property
    def guild(self) -> Guild:
        return self._channel.guild

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
        return self._volume / 1000

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
        return self.bot.get_channel(self._channel.id)

    async def connect(self, **kwargs):
        if self.voice_client:
            await self.voice_client.connect(**kwargs)
        else:
            self.voice_client = await self._channel.connect(**kwargs)

    async def disconnect(self, **kwargs):
        if self.voice_client:
            self.stop()
            await self.voice_client.disconnect(**kwargs)
            self.voice_client = None
        self.emit("disconnect", player=self)

    async def move_to(self, target: VoiceChannel):
        self._channel = target

        if self.voice_client:
            await self.voice_client.move_to(target)
            self._channel = target
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
        await self.setup_chapters()

        log.info(f"playing {entry} in {self.vc_qualified_name}")
        self.emit("play", player=self, entry=entry)

    async def setup_chapters(self):
        if isinstance(self.current_entry, TimestampEntry):
            sub_queue = self.current_entry.sub_queue
            for sub_entry in sub_queue:
                self.player.wait_for_timestamp(sub_entry["start"], only_when_latest=True, target=self.update_chapter)

        elif isinstance(self.current_entry, RadioSongEntry):
            await self.current_entry.update()
            delay = max(self.current_entry.next_update_delay, 1)
            self.loop.call_later(delay, self.repeat_chapter_setup)

    def repeat_chapter_setup(self):
        asyncio.ensure_future(self.update_chapter())
        asyncio.ensure_future(self.setup_chapters())

    async def update_chapter(self):
        self.emit("play", player=self, entry=self.current_entry)


class LavalinkClient(EventEmitter):
    bot: "Giesela"
    players: Dict[int, LavalinkPlayer]

    _voice_state: Dict[str, Any]

    def __init__(self, bot: "Giesela"):
        super().__init__()
        self.bot = bot
        bot.add_listener(self.on_socket_response)
        self.players = {}

        self._voice_state = {}

    def get_player(self, guild_id: int, *, create: bool = True) -> Optional[LavalinkPlayer]:
        player = self.players.get(guild_id)
        if not player and create:
            # TODO create
            player = LavalinkPlayer(self.bot)
            self.players[guild_id] = player
        return player

    async def on_socket_response(self, data: Dict[str, Any]):
        if not data or data.get("t") not in {"VOICE_STATE_UPDATE", "VOICE_SERVER_UPDATE"}:
            return

        if data["t"] == "VOICE_SERVER_UPDATE":
            event_data = data["d"]
            self._voice_state.update({
                "op": "voiceUpdate",
                "guildId": event_data["guild_id"],
                "event": event_data
            })
        else:
            event_data = data["d"]
            if int(event_data["user_id"]) != self.bot.user.id:
                return

            self._voice_state.update({"sessionId": event_data["session_id"]})

            guild_id = int(event_data["guild_id"])

            if guild_id in self.players:
                self.players[guild_id].channel = event_data["channel_id"]

        if all(key in self._voice_state for key in ("op", "guildId", "sessionId", "event")):
            guild_id = event_data["guild_id"]
            log.debug(f"sending voice_state for guild {guild_id}")
            await self.ws.send(**self._voice_state)
            self._voice_state.clear()
