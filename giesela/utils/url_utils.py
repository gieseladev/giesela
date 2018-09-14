import re
from typing import Pattern

import aiohttp

__all__ = ["is_url", "url_is_image"]

RE_HTTP_SCHEME: Pattern = re.compile(r"^https?://")


def is_url(url: str) -> bool:
    match = RE_HTTP_SCHEME.match(url)
    return bool(match)


async def url_is_image(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url) as resp:
            content_type = resp.headers["content-type"]
    except aiohttp.ClientError:
        return False

    return content_type.startswith("image/")
