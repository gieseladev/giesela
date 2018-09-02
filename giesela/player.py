import abc
import asyncio
import enum
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING, Union

from discord import Guild, VoiceChannel
from discord.gateway import DiscordWebSocket
from websockets import ConnectionClosed

from .entry import BaseEntry, RadioSongEntry, TimestampEntry
from .lib import EventEmitter, has_events
from .lib.lavalink import LavalinkAPI, LavalinkEvent, LavalinkPlayerState, TrackEventDataType
from .queue import EntryQueue

if TYPE_CHECKING:
    from giesela import Giesela

log = logging.getLogger(__name__)


class GieselaPlayerState(enum.IntEnum):
    DISCONNECTED = 0
    PLAYING = 1
    PAUSED = 2
    IDLE = 3


class StateInterpreter(metaclass=abc.ABCMeta):
    state: GieselaPlayerState

    @property
    def is_playing(self) -> bool:
        return self.state == GieselaPlayerState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self.state == GieselaPlayerState.PAUSED

    @property
    def is_connected(self) -> bool:
        return self.state != GieselaPlayerState.DISCONNECTED


@has_events("connect", "disconnect", "pause", "resume", "seek", "skip", "stop", "play", "finished", "chapter")
class GieselaPlayer(EventEmitter, StateInterpreter):
    voice_channel_id: Optional[int]

    _last_state: Optional[LavalinkPlayerState]
    _current_entry: Optional[BaseEntry]
    _start_position: float

    def __init__(self, manager: "PlayerManager", guild_id: int, voice_channel_id: int = None):
        super().__init__(loop=manager.loop)
        self.manager = manager
        self.bot = manager.bot
        self.config = self.bot.config

        self.state = GieselaPlayerState.DISCONNECTED
        self.guild_id = guild_id
        self.voice_channel_id = voice_channel_id

        self.queue = EntryQueue(self)
        self.queue.on("entry-added", self.on_entry_added)

        self._volume = self.config.default_volume
        self._last_state = None
        self._current_entry = None
        self._start_position = 0

    def __str__(self) -> str:
        playing = f"playing {self.current_entry}" if self.is_playing else ""
        return f"<GieselaPlayer for {self.qualified_channel_name} {playing}>"

    @property
    def qualified_channel_name(self) -> str:
        return f"{self.guild.name}#{self.voice_channel.name}"

    @property
    def voice_channel(self) -> VoiceChannel:
        return self.bot.get_channel(self.voice_channel_id)

    @property
    def guild(self) -> Guild:
        return self.bot.get_guild(self.guild_id)

    @property
    def current_entry(self) -> Optional[BaseEntry]:
        return self._current_entry

    @property
    def volume_percentage(self) -> float:
        return self._volume / 1000

    @property
    def progress(self) -> float:
        state = self._last_state
        if not state:
            return 0
        if self.state == GieselaPlayerState.PLAYING:
            progress = state.estimate_seconds_now
        else:
            progress = state.seconds
        return progress - self._start_position

    async def connect(self, channel: Union[VoiceChannel, int] = None):
        if isinstance(channel, VoiceChannel):
            channel = channel.id

        if channel and not self.voice_channel_id:
            raise ValueError("No voice channel specified")

        await self.manager.connect_player(self.guild_id, channel)
        self.state = GieselaPlayerState.IDLE
        self.emit("connect", player=self)

    async def disconnect(self):
        if not self.is_connected:
            return
        await self.stop()

        await self.manager.disconnect_player(self.guild_id)
        self.state = GieselaPlayerState.DISCONNECTED
        self.emit("disconnect", player=self)

    async def pause(self):
        await self.manager.send_pause(self.guild_id)
        self.state = GieselaPlayerState.PAUSED
        self.emit("pause", player=self)

    async def resume(self):
        await self.manager.send_resume(self.guild_id)
        self.state = GieselaPlayerState.PLAYING
        self.emit("resume", player=self)

    async def seek(self, seconds: float):
        await self.manager.send_seek(self.guild_id, seconds)
        self.emit("seek", player=self, timestamp=seconds)

    async def skip(self, force: bool = False):
        if not force and isinstance(self.current_entry, TimestampEntry):
            sub_entry = self.current_entry.get_sub_entry(self)
            await self.seek(sub_entry["end"])
        else:
            await self.manager.send_stop(self.guild_id)
        self.emit("skip", player=self)

    async def stop(self):
        await self.manager.send_stop(self.guild_id)
        self.state = GieselaPlayerState.IDLE
        self.emit("stop", player=self)

    def modify_current_entry(self, entry: BaseEntry):
        if not self.current_entry:
            raise ValueError("No current entry")
        if self.current_entry != entry:
            raise ValueError("Edited entry doesn't share current entry's url")

        self._current_entry = entry
        self.emit("play", player=self, entry=entry)

    def playback_finished(self, play_next: bool = True):
        entry = self.current_entry
        if entry:
            self.queue.push_history(entry)

        self._current_entry = None
        self.state = GieselaPlayerState.IDLE

        self.emit("finished", player=self, entry=entry)

        if play_next:
            self.loop.create_task(self.play())

    async def play(self, entry: BaseEntry = None):
        if not self.is_connected:
            await self.connect()

        if not entry:
            entry = self.queue.get_next()

        if not entry:
            log.debug("queue empty")
            await self.stop()
            return

        self._current_entry = entry
        self._start_position = entry.start_position or 0

        await self.manager.send_play(self.guild_id, entry.track_urn, entry.start_position, entry.end_position)

        await self.setup_chapters()

        log.info(f"playing {entry} in {self.qualified_channel_name}")
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
        self.emit("chapter", player=self)

    async def handle_event(self, event: LavalinkEvent, data: TrackEventDataType):
        play_next = True

        if event == LavalinkEvent.TRACK_END:
            if not data.reason.start_next:
                log.info("not playing next because Lavalink said so I guess")
                play_next = False
        elif event == LavalinkEvent.TRACK_EXCEPTION:
            log.error(f"Lavalink reported an error: {data.error}")

        await self.playback_finished(play_next)

    async def update_state(self, state: LavalinkPlayerState):
        self._last_state = state

    def on_entry_added(self, **_):
        if not self.current_entry:
            self.loop.create_task(self.play())


class PlayerManager(LavalinkAPI):
    bot: "Giesela"
    players: Dict[int, GieselaPlayer]

    _voice_state: Dict[str, Any]

    def __init__(self, bot: "Giesela", password: str, rest_url: str, ws_url: str):
        super().__init__(bot, password=password, rest_url=rest_url, ws_url=ws_url)
        self.players = {}

        self._voice_state = {}

        bot.add_listener(self.on_socket_response)

    def get_player(self, guild_id: int, voice_channel_id: int = None, *, create: bool = True) -> Optional[GieselaPlayer]:
        player = self.players.get(guild_id)
        if not player and create:
            # TODO create
            player = GieselaPlayer(self, guild_id, voice_channel_id)
            self.players[guild_id] = player
        return player

    def get_discord_websocket(self, guild_id: int) -> DiscordWebSocket:
        # noinspection PyProtectedMember
        return self.bot._connection._get_websocket(guild_id)

    async def connect_player(self, guild_id: int, channel_id: int):
        ws = self.get_discord_websocket(guild_id)
        await ws.voice_state(guild_id, channel_id)

    async def disconnect_player(self, guild_id: int):
        ws = self.get_discord_websocket(guild_id)
        await ws.voice_state(guild_id, None)

    async def on_event(self, guild_id: int, event: LavalinkEvent, data: TrackEventDataType):
        player = self.players.get(guild_id)
        if not player:
            log.info(f"No player in guild {guild_id}... Not handling {event}")
            return

        await player.handle_event(event, data)

    async def on_player_update(self, guild_id: int, state: LavalinkPlayerState):
        player = self.players.get(guild_id)
        if not player:
            log.info(f"No player in guild {guild_id}... Not updating {state}")
            return

        await player.update_state(state)

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
            await self.send_raw(self._voice_state)
            self._voice_state.clear()

    async def on_disconnect(self, error: ConnectionClosed):
        for player in self.players.values():
            await player.disconnect()
