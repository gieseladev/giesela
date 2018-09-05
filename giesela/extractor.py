import asyncio
import logging
import re
from typing import List, Optional, Pattern, Union

from . import utils
from .entry import BasicEntry, RadioEntry
from .errors import ExtractionError
from .lib.lavalink import LoadTrackSearcher, Track, TrackLoadType, TrackPlaylistInfo
from .lib.lavalink.rest_client import LavalinkREST
from .radio import RadioStation

log = logging.getLogger(__name__)

RE_HTTP_SCHEME: Pattern = re.compile(r"^https?://")


class Extractor:
    def __init__(self, client: LavalinkREST):
        self.client = client
        self.loop = self.client.loop

    @classmethod
    def is_url(cls, url: str) -> bool:
        match = RE_HTTP_SCHEME.match(url)
        return bool(match)

    @classmethod
    def basic_entry_from_load_result(cls, track: Track, playlist_info: TrackPlaylistInfo = None, **extra) -> BasicEntry:
        if playlist_info:
            extra.setdefault("album", playlist_info.name)

        return BasicEntry.from_track_info(track.track, track.info, **extra)

    async def get_radio_entry(self, station: RadioStation) -> RadioEntry:
        result = await self.client.get_tracks(station.stream)
        track = result.track
        if not track:
            raise ExtractionError(f"No result for {station}")

        return RadioEntry.from_track_info(track.track, track.info, station=station)

    async def get_entry(self, identifier: str) -> BasicEntry:
        result = await self.client.get_tracks(identifier)
        track = result.track
        if not track:
            if not result.load_type.has_results:
                raise ExtractionError(f"No results for {identifier}")
            elif result.load_type == TrackLoadType.PLAYLIST:
                raise TypeError("This is a playlist")

        return self.basic_entry_from_load_result(track, result.playlist_info)

    async def get_entries_batch(self, ids: List[str], *, batch_size: int = 50) -> List[BasicEntry]:
        batch_gen = utils.batch_gen(ids, batch_size)
        entries = []

        for batch in batch_gen:
            coros = []
            for identifier in batch:
                coros.append(self.get_entry(identifier))
            batch_entries = await asyncio.wait(coros, loop=self.loop)
            entries.extend(batch_entries)

        return entries

    async def search_entries(self, query: str, searcher=LoadTrackSearcher.YOUTUBE) -> Optional[List[BasicEntry]]:
        result = await self.client.search_tracks(query, searcher)
        if not result.load_type.has_results:
            raise ExtractionError(f"No results for {query}")

        entries = []
        for track in result.tracks:
            entry = self.basic_entry_from_load_result(track)
            entries.append(entry)
        return entries

    async def get(self, target: str, *, search_one=True, searcher=LoadTrackSearcher.YOUTUBE) -> Union[BasicEntry, List[BasicEntry], None]:
        if self.is_url(target):
            result = await self.client.get_tracks(target)
        else:
            result = await self.client.search_tracks(target, searcher)

        if not result.load_type.has_results:
            return None

        playlist_info = result.playlist_info

        if result.load_type == TrackLoadType.SEARCH_RESULT and search_one:
            return self.basic_entry_from_load_result(result.tracks[0], playlist_info)

        if result.track:
            return self.basic_entry_from_load_result(result.track, playlist_info)

        entries = []
        for track in result.tracks:
            entry = self.basic_entry_from_load_result(track, playlist_info)
            entries.append(entry)
        return entries
