from typing import Any, Dict, NamedTuple, Optional

__all__ = ["Lyrics"]


class LyricsOrigin(NamedTuple):
    query: Optional[str]
    source_name: str
    source_url: str
    url: str


class Lyrics(NamedTuple):
    title: str
    artist: str
    lyrics: str
    release_date: int
    origin: LyricsOrigin

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "Lyrics":
        data["origin"] = LyricsOrigin(**data["origin"])
        return Lyrics(**data)
