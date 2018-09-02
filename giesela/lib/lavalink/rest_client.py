from typing import Any, Dict

from aiohttp import ClientSession

from .abstract import AbstractLavalinkClient
from .models import LoadTracksResult

__all__ = ["LavalinkREST"]


class LavalinkREST(AbstractLavalinkClient):
    aiosession: ClientSession

    def __init__(self, *, rest_url: str, aiosession: ClientSession = None, **kwargs):
        super().__init__(**kwargs)
        self.aiosession = aiosession or getattr(self.bot, "aiosession")
        self.api_url = rest_url.rstrip("/")
        self._auth_header = dict(authorization=self._password)

    async def get_tracks_raw(self, query: str) -> Dict[str, Any]:
        url = f"{self.api_url}/loadtracks"
        params = dict(identifier=query)

        async with self.aiosession.get(url, params=params, headers=self._auth_header) as resp:
            return await resp.json(content_type=None)

    async def get_tracks(self, query: str) -> LoadTracksResult:
        result = await self.get_tracks_raw(query)
        return LoadTracksResult.from_result(result)
