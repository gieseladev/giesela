import itertools
import logging
import random
import time
from collections import deque
from typing import Deque, Iterable, Iterator, Optional, TYPE_CHECKING, Union

from discord import User

from .entry import CanWrapEntryType, HistoryEntry, PlayableEntry, PlayerEntry, QueueEntry
from .lib import EventEmitter, has_events

if TYPE_CHECKING:
    from giesela import GieselaPlayer

log = logging.getLogger(__name__)


@has_events("shuffle", "clear", "move_entry", "replay", "history_push", "playlist_load", "entries_added", "entry_added", "entry_removed")
class EntryQueue(EventEmitter):
    player: "GieselaPlayer"

    entries: Deque[QueueEntry]
    history: Deque[HistoryEntry]

    def __init__(self, player: "GieselaPlayer"):
        super().__init__()
        self.player = player
        self.config = player.config

        self.entries = deque()
        self.history = deque(maxlen=self.config.history_limit)

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

    def wrap_queue_entry(self, entry: PlayableEntry, requester: User) -> QueueEntry:
        return QueueEntry(entry=entry, queue=self, requester=requester, request_timestamp=time.time())

    def shuffle(self):
        random.shuffle(self.entries)
        self.emit("shuffle", queue=self)

    def clear(self):
        self.entries.clear()
        self.emit("clear", queue=self)

    def move(self, from_index: int, to_index: int = 0) -> QueueEntry:
        if not all(0 <= x < len(self) for x in (from_index, to_index)):
            raise ValueError(f"indices must be in range 0-{len(self)} ({from_index}, {to_index})")

        move_entry = self.entries.pop(from_index)
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
            entry = self.history.pop(index)

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

        entry = self.entries.pop(target)

        self.emit("entry_removed", queue=self, entry=entry)

        return entry

    def get_next(self) -> Optional[QueueEntry]:
        if self.entries:
            return self.entries.popleft()

    def time_until(self, index: int, *, with_current: bool = True) -> float:
        entries = itertools.islice(self.entries, index)
        estimated_time = sum(e.entry.duration for e in entries)

        if with_current and self.player.current_entry:
            estimated_time += self.player.current_entry.time_left

        return estimated_time

    def total_duration(self) -> float:
        return sum(entry.entry.duration for entry in self.entries)
