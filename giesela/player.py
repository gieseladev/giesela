import abc
import asyncio
import enum
import logging
import rapidjson
from typing import Dict, Iterator, Optional, TYPE_CHECKING, Union

from aioredis import Redis
from discord import Guild, User, VoiceChannel
from discord.gateway import DiscordWebSocket
from websockets import ConnectionClosed

from .entry import PlayerEntry, QueueEntry, SpecificChapterData
from .extractor import Extractor
from .lib import EventEmitter, LavalinkNode, LavalinkNodeBalancer, has_events
from .lib.lavalink import LavalinkEvent, LavalinkPlayerState, TrackEndReason, TrackEventDataType
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


@has_events("connect", "disconnect", "volume_change", "pause", "resume", "seek", "skip", "revert", "stop", "play", "finished", "chapter")
class GieselaPlayer(EventEmitter, PlayerStateInterpreter):
    voice_channel_id: Optional[int]

    _last_state: Optional[LavalinkPlayerState]
    _current_entry: Optional[PlayerEntry]
    _start_position: float

    def __init__(self, manager: "PlayerManager", node: LavalinkNode, guild_id: int, voice_channel_id: int = None):
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

        self._volume = None
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
    async def volume(self) -> float:
        if self._volume is None:
            self._volume = await self.config.get_guild(self.guild_id).player.volume
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

        if not channel:
            raise ValueError("No voice channel specified")

        await self.manager.connect_player(self.guild_id, channel)
        await self.node.send_volume(self.guild_id, await self.volume)

        self.state = GieselaPlayerState.IDLE
        self.emit("connect", player=self)

    async def disconnect(self):
        if not self.is_connected:
            return

        # TODO stop, store progress and current entry somehow and continue on connect
        await self.stop()

        await self.manager.disconnect_player(self.guild_id)
        self.state = GieselaPlayerState.DISCONNECTED
        self.emit("disconnect", player=self)

    async def set_volume(self, value: float):
        old_volume = self._volume
        value = max(min(value, 1000), 0)
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

    async def revert(self, requester: User, *, respect_chapters: bool = True):
        if respect_chapters and self.current_entry:
            previous_chapter = await self.current_entry.get_previous_chapter()

            if previous_chapter and isinstance(previous_chapter, SpecificChapterData):
                await self.seek(previous_chapter.start)
                return

        # if we have history entries then decide whether to restart or replay previous
        if self.queue.history:
            restart_entry = False

            # restart when the progress is bigger than a certain threshold
            if self.current_entry:
                point_of_restart = await self.config.get_guild(self.guild_id).player.restart_entry_point
                if point_of_restart is None or self.progress > point_of_restart:
                    restart_entry = True

            if restart_entry:
                await self.seek(0)
            else:
                # otherwise replay the previous entry
                entry = self.queue.get_replay_entry(requester)
                await self.play(entry)
        else:
            # otherwise only restart
            if self.current_entry:
                await self.seek(0)
            else:
                return

        self.emit("revert", player=self)

    async def skip(self, *, respect_chapters: bool = True):
        if respect_chapters and self.current_entry:
            next_chapter = await self.current_entry.get_next_chapter()

            if next_chapter and isinstance(next_chapter, SpecificChapterData):
                return await self.seek(next_chapter.start)

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
            # FIXME duplicate history entries
            log.debug(f"finished playing {entry}")
            self.queue.push_history(entry)

        if not skipped:
            self._current_entry = None
            self.state = GieselaPlayerState.IDLE

            self.emit("finished", player=self, entry=entry)

        if play_next:
            self.loop.create_task(self.play())

    async def play(self, entry: QueueEntry = None, *, start: float = None):
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

        if start is not None:
            start += playable_entry.start_position or 0
        else:
            start = playable_entry.start_position

        await self.node.send_play(self.guild_id, playable_entry.track, start, playable_entry.end_position)
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
        await self.node.send_destroy(self.guild_id)
        self.node = new_node

        await self.node.send_voice_state()

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

    async def dump_to_redis(self, redis: Redis):
        key = f"{self.config.app.redis.namespaces.queue}:{self.guild_id}:current_entry"
        if self._current_entry:
            entry_data = self._current_entry.to_dict()
            entry_data["progress"] = self.progress
            data = rapidjson.dumps(entry_data)
            log.debug(f"writing current entry to redis {self}")

            await redis.set(key, data)
        else:
            log.debug(f"deleting current entry {self}")
            await redis.delete(key)

        await self.queue.dump_to_redis(redis)

    async def load_from_redis(self, redis: Redis):
        key = f"{self.config.app.redis.namespaces.queue}:{self.guild_id}:current_entry"
        raw_entry = await redis.get(key)

        if raw_entry:
            log.debug(f"loading current entry {self}")
            data = rapidjson.loads(raw_entry)

            progress = data.pop("progress")

            player_entry = PlayerEntry.from_dict(data, player=self, queue=self.queue)
            await self.play(player_entry.wrapped, start=progress)

        await self.queue.load_from_redis(redis)
        self.on_entry_added()


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
        bot.add_listener(self.on_ready)

    def __iter__(self) -> Iterator[GieselaPlayer]:
        return iter(self.players.values())

    def get_player(self, guild_id: int, voice_channel_id: int = None, *, create: bool = True) -> Optional[GieselaPlayer]:
        player = self.players.get(guild_id)

        if not player and create:
            guild = self.bot.get_guild(guild_id)
            if guild:
                player = GieselaPlayer(self, self.pick_node(guild.region), guild_id, voice_channel_id)
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

    async def dump_to_redis(self):
        redis = self.bot.config.redis

        coros = []
        players = []
        for guild_id, player in self.players.items():
            # This handles "None"
            voice_channel_id = rapidjson.dumps(player.voice_channel_id)
            players.extend((guild_id, voice_channel_id))
            coros.append(player.dump_to_redis(redis))

        key = f"{self.bot.config.app.redis.namespaces.queue}:players"
        await redis.delete(key)

        if not coros:
            return

        log.debug(f"writing {len(coros)} player(s) to redis")

        await asyncio.gather(
            redis.hmset(key, *players),
            *coros,
            loop=self.loop
        )

    async def load_from_redis(self):
        redis = self.bot.config.redis
        key = f"{self.bot.config.app.redis.namespaces.queue}:players"
        guilds = await redis.hgetall(key)

        log.info(f"loading {len(guilds)} players from redis")

        coros = []

        for guild_id, voice_channel_id in guilds.items():
            guild_id = int(guild_id)
            voice_channel_id = rapidjson.loads(voice_channel_id)

            player = self.get_player(guild_id, voice_channel_id)
            if player:
                coros.append(player.load_from_redis(redis))
            else:
                log.warning(f"Couldn't load player for {guild_id}")

        await asyncio.gather(*coros, loop=self.loop)

    async def on_ready(self):
        await self.load_from_redis()

    async def on_shutdown(self):
        log.info("Disconnecting from Lavalink")
        await self.dump_to_redis()
        await self.shutdown()

    async def on_disconnect(self, node: LavalinkNode, error: ConnectionClosed):
        if self.bot.exit_signal:
            log.debug(f"ignoring {node} disconnect because Giesela is shutting down")
            return

        coros = []
        for player in self:
            if player.node is node:
                log.info(f"moving {player} to another node")
                voice_region = player.guild.region
                new_node = self.pick_node(voice_region)
                coros.append(player.migrate_node(new_node))

        await asyncio.gather(*coros, loop=self.loop)
