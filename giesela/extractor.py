import logging
from typing import Optional

from .entry import BasicEntry, RadioEntry
from .lib.lavalink import Track
from .lib.lavalink.rest_client import LavalinkREST
from .radio import RadioStation

log = logging.getLogger(__name__)


class Extractor:
    def __init__(self, client: LavalinkREST):
        self.client = client

    async def _get_track(self, identifier: str) -> Optional[Track]:
        result = await self.client.get_tracks(identifier)
        return result.track

    async def get_radio_entry(self, station: RadioStation) -> RadioEntry:
        track = await self._get_track(station.stream)
        if not track:
            # TODO handle?
            log.warning("no track returned...")
            return
        return RadioEntry.from_track_info(track.track, track.info, station=station)

    async def get_entry(self, query: str) -> BasicEntry:
        result = await self.client.search_tracks(query)
        print(result)
        # Don't mind this garbage it's just for testing purposes
        track = result.tracks[0]
        return BasicEntry.from_track_info(track.track, track.info)
