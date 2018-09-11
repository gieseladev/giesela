import asyncio
import itertools
import logging
import random
import rapidjson
import time
from collections import deque
from typing import Deque, Iterable, Iterator, Optional, TYPE_CHECKING, TypeVar, Union

from aioredis import Redis
from discord import User

from .entry import CanWrapEntryType, HistoryEntry, PlayableEntry, PlayerEntry, QueueEntry
from .lib import EventEmitter, has_events

if TYPE_CHECKING:
    from giesela import GieselaPlayer

log = logging.getLogger(__name__)

_VT = TypeVar("_VT")


def deque_pop_index(queue: Deque[_VT], index: int) -> _VT:
    queue.rotate(-index)
    value = queue.popleft()
    queue.rotate(index)
    return value


@has_events("shuffle", "clear", "move_entry", "replay", "history_push", "playlist_load", "entries_added", "entry_added", "entry_removed")
class EntryQueue(EventEmitter):
    player: "GieselaPlayer"

    entries: Deque[QueueEntry]
    history: Deque[HistoryEntry]

    def __init__(self, player: "GieselaPlayer"):
        super().__init__()
        self.player = player
        self.bot = player.bot
        self.config = player.config

        self.entries = deque()
        self.history = deque()  # TODO sensibly apply max constraints from config

    def __iter__(self) -> Iterator[QueueEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, item: int) -> Union[QueueEntry, HistoryEntry]:
        if item >= 0:
            return self.entries[item]
        else:
            item = abs(item) - 1
            return self.history[item]

    async def dump_to_redis(self, redis: Redis):
        prefix = f"{self.config.app.redis.namespaces.queue}:{self.player.guild_id}"
        queue_key = f"{prefix}:queue"
        history_key = f"{prefix}:history"

        await redis.delete(queue_key, history_key)

        coros = []
        if self.entries:
            log.debug(f"writing queue to redis ({len(self.entries)} entr(y/ies))")
            queue = (rapidjson.dumps(entry.to_dict()) for entry in self.entries)
            coros.append(redis.rpush(queue_key, *queue))

        if self.history:
            log.debug(f"writing history to redis ({len(self.history)} entr(y/ies))")
            history = (rapidjson.dumps(entry.to_dict()) for entry in self.history)
            coros.append(redis.rpush(history_key, *history))

        await asyncio.gather(
            *coros,
            loop=self.loop
        )

    async def _load_queue_from_redis(self, redis: Redis):
        key = f"{self.config.app.redis.namespaces.queue}:{self.player.guild_id}:queue"

        entries = await redis.lrange(key, 0, -1)
        log.info(f"loading {len(entries)} queue entries from redis")
        for raw_entry in entries:
            data = rapidjson.loads(raw_entry)
            entry = QueueEntry.from_dict(data, queue=self)
            self.entries.append(entry)

    async def _load_history_from_redis(self, redis):
        key = f"{self.config.app.redis.namespaces.queue}:{self.player.guild_id}:history"

        entries = await redis.lrange(key, 0, -1)
        log.info(f"loading {len(entries)} history entries from redis")
        for raw_entry in entries:
            data = rapidjson.loads(raw_entry)
            entry = HistoryEntry.from_dict(data, queue=self)
            self.history.append(entry)

    async def load_from_redis(self, redis: Redis):
        await asyncio.gather(self._load_queue_from_redis(redis),
                             self._load_history_from_redis(redis),
                             loop=self.loop)

    def wrap_queue_entry(self, entry: PlayableEntry, requester: User) -> QueueEntry:
        return QueueEntry(entry=entry, queue=self, requester_id=requester.id, request_timestamp=time.time())

    def shuffle(self):
        random.shuffle(self.entries)
        self.emit("shuffle", queue=self)

    def clear(self):
        self.entries.clear()
        self.emit("clear", queue=self)

    def move(self, from_index: int, to_index: int = 0) -> QueueEntry:
        if not all(0 <= x < len(self) for x in (from_index, to_index)):
            raise ValueError(f"indices must be in range 0-{len(self)} ({from_index}, {to_index})")

        move_entry = deque_pop_index(self.entries, from_index)
        if to_index:
            self.entries.insert(to_index, move_entry)
        else:
            self.entries.appendleft(move_entry)

        self.emit("move_entry", queue=self, entry=move_entry, from_index=from_index, to_index=to_index)

        return move_entry

    def replay(self, requester: User, index: int = None) -> Optional[QueueEntry]:
        if index is None:
            entry = self.history.popleft()
        else:
            if not 0 <= index < len(self):
                return None
            entry = deque_pop_index(self.history, index)

        entry = self.wrap_queue_entry(entry.entry, requester)
        self.entries.appendleft(entry)
        self.emit("replay", queue=self, entry=entry, index=index or 0)
        return entry

    def push_history(self, entry: PlayerEntry):
        entry = HistoryEntry(finish_timestamp=time.time(), entry=entry.wrapped)
        self.history.appendleft(entry)

        self.emit("history_push", queue=self, entry=entry)

    def add_entries(self, entries: Iterable[CanWrapEntryType], requester: User, *, position: int = None):
        entries = list(self.wrap_queue_entry(entry, requester) for entry in entries)
        if position is None:
            self.entries.extend(entries)
        else:
            if not 0 <= position < len(self.entries):
                raise ValueError(f"position out of bounds must be 0 <= {position} < {len(self.entries)}")

            self.entries.rotate(position)
            entry_amount = len(entries)
            self.entries.extendleft(reversed(entries))
            self.entries.rotate(-(position + entry_amount))

        self.emit("entries_added", queue=self, entries=entries)

    def add_entry(self, entry: CanWrapEntryType, requester: User, *, placement: int = None) -> QueueEntry:
        entry = self.wrap_queue_entry(entry, requester)
        if placement is not None:
            self.entries.insert(placement, entry)
        else:
            self.entries.append(entry)

        self.emit("entry_added", queue=self, entry=entry)

        return entry

    def remove(self, target: Union[int, QueueEntry]) -> Optional[QueueEntry]:
        if isinstance(target, QueueEntry):
            target = self.entries.index(target)

        if not 0 <= target < len(self):
            return None

        entry = deque_pop_index(self.entries, target)

        self.emit("entry_removed", queue=self, entry=entry)

        return entry

    def get_next(self) -> Optional[QueueEntry]:
        if self.entries:
            return self.entries.popleft()

    def peek(self) -> Optional[QueueEntry]:
        if self.entries:
            return self.entries[0]

    def time_until(self, index: int, *, with_current: bool = True) -> float:
        entries = itertools.islice(self.entries, index)
        estimated_time = sum(entry.entry.duration for entry in entries if entry.entry.duration)

        if with_current and self.player.current_entry:
            estimated_time += self.player.current_entry.time_left

        return estimated_time

    def total_duration(self) -> float:
        return sum(entry.entry.duration for entry in self.entries if entry.entry.duration)
