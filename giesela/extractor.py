import logging
import re
from typing import List, Pattern, Union

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

    @classmethod
    def is_url(cls, url: str) -> bool:
        match = RE_HTTP_SCHEME.match(url)
        return bool(match)

    @classmethod
    def basic_entry_from_load_result(cls, track: Track, playlist_info: TrackPlaylistInfo = None) -> BasicEntry:
        extra = {}
        if playlist_info:
            extra["album"] = playlist_info.name

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

    async def get(self, target: str, searcher=LoadTrackSearcher.YOUTUBE) -> Union[BasicEntry, List[BasicEntry], None]:
        if self.is_url(target):
            result = await self.client.get_tracks(target)
        else:
            result = await self.client.search_tracks(target, searcher)

        if not result.load_type.has_results:
            return None

        playlist_info = result.playlist_info

        if result.track:
            return self.basic_entry_from_load_result(result.track, playlist_info)

        entries = []
        for track in result.tracks:
            entry = self.basic_entry_from_load_result(track, playlist_info)
            entries.append(entry)
        return entries
