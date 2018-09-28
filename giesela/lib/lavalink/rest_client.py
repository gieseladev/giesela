from typing import Any, Dict

from aiohttp import ClientSession

from .abstract import AbstractLavalinkClient
from .models import LoadTrackSearcher, LoadTracksResult

__all__ = ["LavalinkREST"]


class LavalinkREST(AbstractLavalinkClient):
    aiosession: ClientSession

    def __init__(self, *, aiosession: ClientSession = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.aiosession = aiosession or getattr(self.bot, "aiosession")
        self._auth_header = dict(authorization=self._password)

    async def get_tracks_raw(self, identifier: str) -> Dict[str, Any]:
        url = f"{self._rest_url}/loadtracks"
        params = dict(identifier=identifier)

        async with self.aiosession.get(url, params=params, headers=self._auth_header) as resp:
            return await resp.json(content_type=None)

    async def get_tracks(self, identifier: str) -> LoadTracksResult:
        result = await self.get_tracks_raw(identifier)
        return LoadTracksResult.from_result(result)

    async def search_tracks(self, query: str, searcher: LoadTrackSearcher = LoadTrackSearcher.YOUTUBE) -> LoadTracksResult:
        identifier = f"{searcher.value}: {query}"
        return await self.get_tracks(identifier)
