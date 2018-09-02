import logging
import random
from collections import deque
from typing import Deque, Iterable, Iterator, Optional, TYPE_CHECKING, Union

from .entry import (BaseEntry, RadioSongEntry, RadioStationEntry)
from .exceptions import BrokenEntryError
from .lib import EventEmitter, has_events
from .radio import RadioStation
from .webiesela import WebieselaServer

if TYPE_CHECKING:
    from giesela import Playlist, GieselaPlayer

log = logging.getLogger(__name__)


@has_events("shuffle", "clear", "move_entry", "replay", "history_push", "playlist_load", "entries_added", "entry_added", "entry_removed")
class EntryQueue(EventEmitter):
    player: "GieselaPlayer"

    entries: Deque[BaseEntry]
    history: Deque[BaseEntry]

    def __init__(self, player: "GieselaPlayer"):
        super().__init__()
        self.player = player
        self.config = player.config

        self.entries = deque()
        self.history = deque(maxlen=self.config.history_limit)

    def __iter__(self) -> Iterator[BaseEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, item: int) -> BaseEntry:
        if item >= 0:
            return self.entries[item]
        else:
            item = abs(item) - 1
            return self.history[item]

    def shuffle(self):
        random.shuffle(self.entries)
        self.emit("shuffle", queue=self)
        WebieselaServer.send_player_information(self.player.channel.guild.id)

    def clear(self):
        self.entries.clear()
        self.emit("clear", queue=self)
        WebieselaServer.send_player_information(self.player.channel.guild.id)

    def move(self, from_index: int, to_index: int = None) -> Optional[BaseEntry]:
        if not all(0 <= x < len(self) for x in (from_index, to_index)):
            return None

        move_entry = self.entries.pop(from_index)
        if to_index:
            # FIXME this shouldn't work when from_index < to_index
            self.entries.insert(to_index, move_entry)
        else:
            self.entries.appendleft(move_entry)

        self.emit("move_entry", queue=self, entry=move_entry, from_index=from_index, to_index=to_index)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return move_entry

    def replay(self, index: int = None) -> Optional[BaseEntry]:
        if index is None:
            entry = self.history.popleft()
        else:
            if not 0 <= index < len(self):
                return None
            entry = self.history.pop(index)

        self.entries.appendleft(entry)
        self.emit("replay", queue=self, entry=entry, index=index or 0)
        return entry

    def push_history(self, entry: BaseEntry):
        # TODO use some thin wrapper
        self.history.appendleft(entry)

        self.emit("history_push", queue=self, entry=entry)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

    async def add_playlist(self, playlist: "Playlist", **meta):
        entries = playlist.entries.copy()
        random.shuffle(entries)
        for playlist_entry in entries:
            try:
                entry = playlist_entry.get_entry(**meta)
            except BrokenEntryError:
                continue
            self.add_entry(entry)
        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("playlist_load", queue=self)

    async def add_radio_entry(self, station: RadioStation, now: bool = False, **meta) -> RadioStationEntry:
        if station.has_song_data:
            song_data = await station.get_song_data()
            entry = RadioSongEntry(station, song_data, **meta)
        else:
            entry = RadioStationEntry(station, **meta)

        if now:
            await self.player.play(entry)
        else:
            self.add_entry(entry)

        return entry

    def add_entries(self, entries: Iterable[BaseEntry]):
        self.entries.extend(entries)

        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("entries_added", queue=self, entries=entries)

    def add_entry(self, entry: BaseEntry, placement: int = None):
        if placement is not None:
            self.entries.insert(placement, entry)
        else:
            self.entries.append(entry)

        WebieselaServer.send_player_information(self.player.guild.id)
        self.emit("entry_added", queue=self, entry=entry)

    def remove(self, target: Union[int, BaseEntry]) -> Optional[BaseEntry]:
        if isinstance(target, BaseEntry):
            target = self.entries.index(target)

        if not 0 <= target < len(self):
            return None

        entry = self.entries.pop(target)

        self.emit("entry_removed", queue=self, entry=entry)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return entry

    def get_next(self) -> Optional[BaseEntry]:
        if self.entries:
            return self.entries.popleft()

    def seconds_until(self, index: int, *, with_current: bool = True) -> float:
        estimated_time = sum(e.duration for e in self.entries[:index])

        if with_current and self.player.current_entry:
            estimated_time += self.player.current_entry.duration - self.player.progress

        return estimated_time
