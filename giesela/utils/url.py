import re
from typing import Pattern

__all__ = ["is_url"]

RE_HTTP_SCHEME: Pattern = re.compile(r"^https?://")


def is_url(url: str) -> bool:
    match = RE_HTTP_SCHEME.match(url)
    return bool(match)
