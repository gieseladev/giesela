import asyncio
import datetime
import logging
import random
import time
from collections import deque
from typing import Deque, Iterable, Iterator, Optional, TYPE_CHECKING, Union

from .bot import Giesela
from .downloader import Downloader
from .entry import (BaseEntry, RadioSongEntry, RadioStationEntry)
from .exceptions import BrokenEntryError, ExtractionError
from .lib.event_emitter import EventEmitter
from .radio import StationInfo
from .webiesela import WebieselaServer

if TYPE_CHECKING:
    from giesela import Playlist, MusicPlayer

log = logging.getLogger(__name__)


class Queue(EventEmitter):
    bot: Giesela
    player: "MusicPlayer"
    downloader: Downloader

    entries: Deque[BaseEntry]
    history: Deque[BaseEntry]

    def __init__(self, bot: Giesela, player: "MusicPlayer", downloader: Downloader):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.player = player
        self.downloader = downloader

        self.entries = deque()
        self.history = deque(maxlen=self.bot.config.history_limit)

    def __iter__(self) -> Iterator[BaseEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get_web_dict(self):
        data = {
            "entries": [entry.to_web_dict(self.player) for entry in self.entries.copy()],
            "history": [entry.to_web_dict(self.player) for entry in self.history.copy()]
        }
        return data

    def shuffle(self):
        random.shuffle(self.entries)
        self.emit("queue-shuffled", queue=self)
        WebieselaServer.send_player_information(self.player.channel.guild.id)

    def clear(self):
        self.entries.clear()
        self.emit("queue-cleared", queue=self)
        WebieselaServer.send_player_information(self.player.channel.guild.id)

    def move(self, from_index: int, to_index: int) -> Optional[BaseEntry]:
        if not (0 <= from_index < len(self.entries) and 0 <= to_index < len(self.entries)):
            return None

        self.entries.rotate(-from_index)
        move_entry = self.entries.popleft()
        self.entries.rotate(from_index - to_index)

        self.entries.appendleft(move_entry)
        self.entries.rotate(to_index)

        if self.peek() is move_entry:
            move_entry.get_ready_future(self)

        self.emit("entry-moved", queue=self, entry=move_entry, from_index=from_index, to_index=to_index)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return move_entry

    def replay(self, index: int = None, revert: bool = False) -> bool:
        if index is None:
            entry = self.player.current_entry
            if entry:
                entry = entry.copy()
            else:
                return False
        else:
            if not 0 <= index < len(self.history):
                return False
            entry = self.history[index].copy()

        self.add_entry(entry, placement=0)

        if revert and self.player.current_entry:
            self.player.skip()

        return True

    def push_history(self, entry: BaseEntry):
        entry = entry.copy()

        entry.meta["finish_time"] = time.time()
        self.history.appendleft(entry)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

    async def load_playlist(self, playlist: "Playlist", **meta):
        entries = playlist.entries.copy()
        random.shuffle(entries)
        for playlist_entry in entries:
            try:
                entry = playlist_entry.get_entry(**meta)
            except BrokenEntryError:
                continue
            self.add_entry(entry, more_to_come=True)
        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("entry-added", queue=self)

    async def add_radio_entry(self, station_info: StationInfo, now: bool = False, **meta) -> RadioStationEntry:
        if station_info.has_current_song_info:
            entry = RadioSongEntry(station_info, **meta)
        else:
            entry = RadioStationEntry(station_info, **meta)

        if now:
            await self.player.play(entry)
        else:
            self.add_entry(entry)

        return entry

    def add_entries(self, entries: Iterable[BaseEntry], placement: Union[str, int] = None):
        entry = None
        for entry in entries:
            self.add_entry(entry, placement=placement, more_to_come=True)

        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("entry-added", queue=self, entry=entry)

    def add_entry(self, entry: BaseEntry, placement: int = None, more_to_come: bool = False):
        if placement is not None:
            self.entries.insert(placement, entry)
        else:
            self.entries.append(entry)

        if self.peek() is entry:
            entry.get_ready_future(self)

        if not more_to_come:
            WebieselaServer.send_player_information(self.player.guild.id)
            self.emit("entry-added", queue=self, entry=entry)

    def promote_position(self, position: int) -> Optional[BaseEntry]:
        if not 0 <= position < len(self.entries):
            return None

        self.entries.rotate(-position)
        entry = self.entries.popleft()

        self.entries.rotate(position)
        self.entries.appendleft(entry)
        self.emit("entry-promoted", queue=self, entry=entry)

        entry.get_ready_future(self)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return entry

    def promote_last(self) -> Optional[BaseEntry]:
        if len(self.entries) < 2:
            return None

        entry = self.entries.pop()
        self.entries.appendleft(entry)
        self.emit("entry-promoted", queue=self, entry=entry)
        entry.get_ready_future(self)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return entry

    def remove_position(self, position: int) -> Optional[BaseEntry]:
        if not 0 <= position < len(self.entries):
            return None

        self.entries.rotate(-position)
        entry = self.entries.popleft()

        self.emit("entry-removed", queue=self, entry=entry)
        self.entries.rotate(position)

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return entry

    async def get_next_entry(self, pre_download_next: bool = True) -> Optional[BaseEntry]:
        """
            A coroutine which will return the next song or None if no songs left to play.

            Additionally, if pre_download_next is set to True, it will attempt to download the next
            song to be played - so that it's ready by the time we get to it.
        """
        if not self.entries:
            return None

        entry = self.entries.popleft()

        if pre_download_next:
            next_entry = self.peek()
            if next_entry:
                asyncio.ensure_future(next_entry.get_ready_future(self))

        try:
            return await entry.get_ready_future(self)
        except ExtractionError:
            log.warning(f"{entry} is broken!")
        except Exception:
            log.exception(f"Couldn't ready entry {entry}")

        return await self.get_next_entry(pre_download_next)

    def peek(self) -> BaseEntry:
        if self.entries:
            return self.entries[0]

    async def estimate_time_until(self, index: int) -> datetime.timedelta:
        estimated_time = sum(e.duration for e in self.entries[:index])

        if self.player.current_entry:
            estimated_time += self.player.current_entry.duration - self.player.progress

        return datetime.timedelta(seconds=estimated_time)
