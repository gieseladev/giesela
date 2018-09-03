from .entry import BasicEntry
from .lib.lavalink.rest_client import LavalinkREST


class Extractor:
    def __init__(self, client: LavalinkREST):
        self.client = client

    async def get_entry(self, query: str) -> BasicEntry:
        result = await self.client.search_tracks(query)
        print(result)
        # Don't mind this garbage it's just for testing purposes
        track = result.tracks[0]
        return BasicEntry.from_track_info(track.track, track.info)
