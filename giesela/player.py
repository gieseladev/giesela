import abc
import asyncio
import enum
import logging
from typing import Dict, Iterator, Optional, TYPE_CHECKING, Union

from discord import Guild, VoiceChannel
from discord.gateway import DiscordWebSocket
from websockets import ConnectionClosed

from .entry import PlayerEntry, QueueEntry
from .extractor import Extractor
from .lib import EventEmitter, has_events
from .lib.lavalink import LavalinkEvent, LavalinkNode, LavalinkNodeBalancer, LavalinkPlayerState, TrackEndReason, TrackEventDataType
from .queue import EntryQueue

if TYPE_CHECKING:
    from giesela import Giesela

log = logging.getLogger(__name__)


class GieselaPlayerState(enum.IntEnum):
    DISCONNECTED = 0
    PLAYING = 1
    PAUSED = 2
    IDLE = 3


class PlayerStateInterpreter(metaclass=abc.ABCMeta):
    state: GieselaPlayerState

    @property
    def is_playing(self) -> bool:
        return self.state == GieselaPlayerState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self.state == GieselaPlayerState.PAUSED

    @property
    def is_stopped(self) -> bool:
        return self.state == GieselaPlayerState.IDLE

    @property
    def is_connected(self) -> bool:
        return self.state != GieselaPlayerState.DISCONNECTED


@has_events("connect", "disconnect", "volume_change", "pause", "resume", "seek", "skip", "stop", "play", "finished", "chapter")
class GieselaPlayer(EventEmitter, PlayerStateInterpreter):
    voice_channel_id: Optional[int]

    _last_state: Optional[LavalinkPlayerState]
    _current_entry: Optional[PlayerEntry]
    _start_position: float

    def __init__(self, manager: "PlayerManager", node: LavalinkNode, guild_id: int, volume: float, voice_channel_id: int = None):
        super().__init__(loop=manager.loop)
        self.manager = manager
        self.node = node
        self.extractor = manager.extractor
        self.bot = manager.bot
        self.config = self.bot.config

        self.state = GieselaPlayerState.DISCONNECTED
        self.guild_id = guild_id
        self.voice_channel_id = voice_channel_id

        self.queue = EntryQueue(self) \
            .on("entry_added", self.on_entry_added) \
            .on("entries_added", self.on_entry_added)

        self._volume = volume
        self._last_state = None
        self._current_entry = None
        self._start_position = 0

        self._chapter_update_lock = asyncio.Lock()

    def __str__(self) -> str:
        playing = f"playing {self.current_entry!r}" if self.is_playing else ""
        return f"<GieselaPlayer for {self.qualified_channel_name} {playing}>"

    @property
    def qualified_channel_name(self) -> str:
        vc = self.voice_channel
        vc_id = vc.name if vc else self.voice_channel_id
        if vc_id:
            return f"{self.guild.name}#{vc_id}"
        else:
            return self.guild.name

    @property
    def voice_channel(self) -> Optional[VoiceChannel]:
        voice_state = self.guild.me.voice
        if voice_state and voice_state.channel:
            return voice_state.channel
        return self.bot.get_channel(self.voice_channel_id)

    @property
    def guild(self) -> Guild:
        return self.bot.get_guild(self.guild_id)

    @property
    def current_entry(self) -> Optional[PlayerEntry]:
        return self._current_entry

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def progress(self) -> float:
        state = self._last_state
        if not state:
            return 0
        if self.is_playing:
            progress = state.estimate_seconds_now
        else:
            progress = state.seconds
        return progress - self._start_position

    @property
    def can_seek(self) -> bool:
        if self._current_entry:
            return self._current_entry.entry.is_seekable
        return False

    async def connect(self, channel: Union[VoiceChannel, int] = None):
        if channel is not None:
            if isinstance(channel, VoiceChannel):
                channel = channel.id
            self.voice_channel_id = channel
        else:
            channel = self.voice_channel_id

        # FIXME when already connected or something the player doesn't play...

        if not channel:
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

    async def set_volume(self, value: float):
        old_volume = self._volume
        value = max(min(value, 1000), 0)
        # TODO the default volume isn't set
        await self.node.send_volume(self.guild_id, value)
        self._volume = value
        self.emit("volume_change", player=self, old_volume=old_volume, new_volume=value)

    async def pause(self):
        await self.node.send_pause(self.guild_id)
        self.state = GieselaPlayerState.PAUSED
        self.emit("pause", player=self)

    async def resume(self):
        await self.node.send_resume(self.guild_id)
        self.state = GieselaPlayerState.PLAYING
        self.emit("resume", player=self)

    async def seek(self, seconds: float):
        entry = self.current_entry
        if not entry:
            raise ValueError(f"{self} has no current entry")
        if not entry.entry.is_seekable:
            raise TypeError(f"{entry} is not seekable!")
        await self.node.send_seek(self.guild_id, seconds)
        self.emit("seek", player=self, timestamp=seconds)

    async def skip(self):
        self._current_entry = None
        await self.play()
        self.emit("skip", player=self)

    async def stop(self):
        self._current_entry = None
        await self.node.send_stop(self.guild_id)
        self.state = GieselaPlayerState.IDLE
        self.emit("stop", player=self)

    def playback_finished(self, play_next: bool = True, skipped: bool = False):
        entry = self.current_entry
        if entry:
            self.queue.push_history(entry)

        if not skipped:
            self._current_entry = None
            self.state = GieselaPlayerState.IDLE

            self.emit("finished", player=self, entry=entry)

        if play_next:
            self.loop.create_task(self.play())

    async def play(self, entry: QueueEntry = None):
        if not self.is_connected:
            await self.connect()

        if not entry:
            entry = self.queue.get_next()

        if not entry:
            log.info("queue empty")
            await self.stop()
            return

        playable_entry = entry.entry
        self._current_entry = PlayerEntry(player=self, entry=entry)
        self._start_position = playable_entry.start_position or 0

        await self.node.send_play(self.guild_id, playable_entry.track, playable_entry.start_position, playable_entry.end_position)
        self.state = GieselaPlayerState.PLAYING

        log.info(f"playing {self.current_entry} in {self.qualified_channel_name}")
        self.emit("play", player=self)

    def on_entry_added(self, **_):
        if not self.current_entry:
            self.loop.create_task(self.play())

    async def update_state(self, state: LavalinkPlayerState):
        self._last_state = state

        if self._chapter_update_lock.locked():
            return

        async with self._chapter_update_lock:
            updated = await self._current_entry.update_chapter()

        if updated:
            self.emit("chapter", player=self)

    async def migrate_node(self, new_node: LavalinkNode):
        self.node = new_node
        if self.is_connected:
            await self.manager.connect_player(self.guild_id, self.voice_channel_id)

        if self._current_entry:
            entry = self._current_entry.entry
            await self.node.send_play(self.guild_id, entry.track, self._start_position + self.progress, entry.end_position)

        if self.is_paused:
            await self.pause()

    async def handle_event(self, event: LavalinkEvent, data: TrackEventDataType):
        play_next = True
        skipped = False

        if event == LavalinkEvent.TRACK_END:
            if data.reason == TrackEndReason.REPLACED:
                log.info("track was replaced (probably skipped), not handling finished")
                skipped = True

            if not data.reason.start_next:
                log.info("not playing next because Lavalink said so I guess")
                play_next = False
        elif event == LavalinkEvent.TRACK_EXCEPTION:
            log.error(f"Lavalink reported an error: {data.error}")

        self.playback_finished(play_next, skipped)


@has_events("player_create")
class PlayerManager(LavalinkNodeBalancer):
    players: Dict[int, GieselaPlayer]

    def __init__(self, bot: "Giesela"):
        nodes = []
        for node in bot.config.app.lavalink.nodes:
            _node = LavalinkNode(bot, password=node.password, address=node.address, secure=node.secure, region=node.region)
            nodes.append(_node)

        super().__init__(bot.loop, nodes)
        self.bot = bot
        self.extractor = Extractor(self)
        self.players = {}

        bot.add_listener(self.on_shutdown)

    def __iter__(self) -> Iterator[GieselaPlayer]:
        return iter(self.players.values())

    def get_player(self, guild_id: int, volume: float, voice_channel_id: int = None, *, create: bool = True) -> Optional[GieselaPlayer]:
        player = self.players.get(guild_id)
        if not player and create:
            guild = self.bot.get_guild(guild_id)
            player = GieselaPlayer(self, self.pick_node(guild.region), guild_id, volume, voice_channel_id)
            self.emit("player_create", player=player)
            self.players[guild_id] = player
        return player

    def get_discord_websocket(self, guild_id: int) -> DiscordWebSocket:
        # noinspection PyProtectedMember
        return self.bot._connection._get_websocket(guild_id)

    async def connect_player(self, guild_id: int, channel_id: int):
        ws = self.get_discord_websocket(guild_id)
        log.debug(f"connecting {guild_id} to {channel_id}")
        await ws.voice_state(guild_id, channel_id)

    async def disconnect_player(self, guild_id: int):
        ws = self.get_discord_websocket(guild_id)
        log.debug(f"disconnecting {guild_id}")
        await ws.voice_state(guild_id, None)

    async def on_event(self, guild_id: int, event: LavalinkEvent, data: TrackEventDataType, **_):
        player = self.players.get(guild_id)
        if not player:
            log.info(f"No player in guild {guild_id}... Not handling {event}")
            return

        await player.handle_event(event, data)

    async def on_player_update(self, guild_id: int, state: LavalinkPlayerState, **_):
        player = self.players.get(guild_id)
        if not player:
            log.info(f"No player in guild {guild_id}... Not updating {state}")
            return

        await player.update_state(state)

    async def on_voice_channel_update(self, guild_id: int, channel_id: Optional[int], **_):
        if not channel_id:
            return

        player = self.players.get(guild_id)
        if player:
            log.info(f"updating channel_id for {player}")
            player.voice_channel_id = channel_id

    async def on_shutdown(self):
        log.info("Disconnecting from Lavalink")
        await self.shutdown()

    async def on_disconnect(self, node: LavalinkNode, error: ConnectionClosed):
        coros = []
        for player in self:
            if player.node is node:
                log.info(f"moving {player} to another node")
                voice_region = player.guild.region
                new_node = self.pick_node(voice_region)
                coros.append(player.migrate_node(new_node))

        await asyncio.gather(*coros, loop=self.loop)
