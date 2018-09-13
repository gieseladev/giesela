from typing import Optional

from aiohttp import ClientSession

from .models import *


class GiTilsClient:

    def __init__(self, aiosession: ClientSession, url: str):
        self.aiosession = aiosession
        self.url = url

    def __str__(self) -> str:
        return f"GiTilsClient for {self.url}"

    async def get_lyrics(self, query: str) -> Optional[Lyrics]:
        async with self.aiosession.get(f"{self.url}/lyrics", params=dict(query=query)) as resp:
            data = await resp.json()

        if not data.get("success"):
            return None

        return Lyrics.from_data(data)
