import asyncio
import datetime
import logging
import os
import random
import time
import urllib
import urllib.error
from collections import deque
from typing import Iterable, Iterator, Optional, TYPE_CHECKING, Tuple, Union

from youtube_dl.utils import DownloadError, UnsupportedError

from .entry import (BaseEntry, RadioSongEntry, RadioStationEntry, StreamEntry)
from .exceptions import BrokenEntryError, ExtractionError
from .lib.event_emitter import EventEmitter
from .radio import StationInfo
from .webiesela import WebieselaServer

if TYPE_CHECKING:
    from giesela import Playlist

log = logging.getLogger(__name__)


class Queue(EventEmitter):

    def __init__(self, bot, player, downloader):
        super().__init__()
        self.bot = bot
        self.loop = bot.loop
        self.player = player
        self.downloader = downloader
        self.entries = deque()
        self.history = []

    def __iter__(self) -> Iterator[BaseEntry]:
        return iter(self.entries)

    def get_web_dict(self):
        data = {
            "entries": [entry.to_web_dict(True) for entry in self.entries.copy()],
            "history": [entry.to_web_dict(True) for entry in self.history.copy()]
        }
        return data

    def shuffle(self):
        random.shuffle(self.entries)
        WebieselaServer.send_player_information(self.player.channel.guild.id)

    def clear(self):
        self.entries.clear()
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
            move_entry.get_ready_future()

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

        self._add_entry(entry, placement=0)

        if revert and self.player.current_entry:
            self.player.skip()

        return True

    def push_history(self, entry: BaseEntry):
        entry = entry.copy()

        entry.meta["finish_time"] = time.time()
        q = self.bot.config.history_limit - 1
        self.history = [entry, *self.history[:q]]

        WebieselaServer.send_player_information(self.player.channel.guild.id)

    async def load_playlist(self, playlist: "Playlist", **meta):
        entries = playlist.entries.copy()
        random.shuffle(entries)
        for playlist_entry in entries:
            try:
                entry = playlist_entry.get_entry(**meta)
            except BrokenEntryError:
                continue
            self._add_entry(entry, more_to_come=True)
        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("entry-added", queue=self)

    async def add_stream_entry(self, stream_url: str, **meta) -> Tuple[BaseEntry, int]:
        info = {"title": stream_url, "extractor": None}
        try:
            info = await self.downloader.extract_info(self.loop, stream_url, download=False)

        except DownloadError as e:
            if e.exc_info[0] == UnsupportedError:
                print("[STREAM] Assuming content is a direct stream")

            elif e.exc_info[0] == urllib.error.URLError:
                if os.path.exists(os.path.abspath(stream_url)):
                    raise ExtractionError("This is not a stream, this is a file path.")

                else:  # it might be a file path that just doesn't exist
                    raise ExtractionError("Invalid input: {0.exc_info[0]}: {0.exc_info[1].reason}".format(e))

            else:
                raise ExtractionError("Unknown error: {}".format(e))

        except Exception as e:
            print("Could not extract information from {} ({}), falling back to direct".format(stream_url, e))

        dest_url = stream_url
        if info.get("extractor"):
            dest_url = info.get("url")

        if info.get("extractor", None) == "twitch:stream":
            title = info.get("description")
        else:
            title = info.get("title", "Untitled")

        entry = StreamEntry(
            self,
            stream_url,
            title,
            destination=dest_url,
            **meta
        )

        self._add_entry(entry)

        return entry, len(self.entries)

    async def add_radio_entry(self, station_info: StationInfo, now: bool = False, **meta):
        if station_info.has_current_song_info:
            entry = RadioSongEntry(self, station_info, **meta)
        else:
            entry = RadioStationEntry(self, station_info, **meta)

        if now:
            await entry._download(self)

            if self.player.current_entry:
                self.player.handle_manually = True

            self.player.play_entry(entry)
            WebieselaServer.send_player_information(self.player.channel.guild.id)
        else:
            self._add_entry(entry)

    def add_entries(self, entries: Iterable[BaseEntry], placement: Union[str, int] = None):
        entry = None
        for entry in entries:
            self._add_entry(entry, placement=placement, more_to_come=True)

        WebieselaServer.send_player_information(self.player.channel.guild.id)
        self.emit("entry-added", queue=self, entry=entry)

    def _add_entry(self, entry: BaseEntry, placement: Union[str, int] = None, more_to_come: bool = False):
        if placement is not None:
            if placement == "random":
                if len(self.entries) > 0:
                    placement = random.randrange(0, len(self.entries))
                else:
                    placement = 0

            self.entries.insert(placement, entry)
        else:
            self.entries.append(entry)

        if self.peek() is entry:
            entry.get_ready_future(self)

        if not more_to_come:
            WebieselaServer.send_player_information(entry.meta["channel"].guild.id)
            self.emit("entry-added", queue=self, entry=entry)

    def promote_position(self, position: int) -> Optional[BaseEntry]:
        if not 0 <= position < len(self.entries):
            return None

        self.entries.rotate(-position)
        entry = self.entries.popleft()

        self.entries.rotate(position)
        self.entries.appendleft(entry)
        self.emit("entry-added", queue=self, entry=entry)

        entry.get_ready_future()

        WebieselaServer.send_player_information(self.player.channel.guild.id)

        return entry

    def promote_last(self) -> Optional[BaseEntry]:
        if len(self.entries) < 2:
            return None

        entry = self.entries.pop()
        self.entries.appendleft(entry)
        self.emit("entry-added", queue=self, entry=entry)
        entry.get_ready_future()

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

    async def get_next_entry(self, pre_download_next=True) -> Optional[BaseEntry]:
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
        """
            Returns the next entry that should be scheduled to be played.
        """
        if self.entries:
            return self.entries[0]

    async def estimate_time_until(self, index: int) -> datetime.timedelta:
        estimated_time = sum(e.end_seconds for e in self.entries[:index])

        if self.player.current_entry:
            estimated_time += self.player.current_entry.duration - self.player.progress

        return datetime.timedelta(seconds=estimated_time)
