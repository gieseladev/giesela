import enum
from typing import Any, Dict, List, NamedTuple

__all__ = ["LavalinkEvent", "LavalinkPlayerState", "TrackLoadType", "TrackPlaylistInfo", "TrackInfo", "Track", "LoadTracksResult"]


class LavalinkEvent(enum.Enum):
    TRACK_END = "TrackEndEvent"
    TRACK_EXCEPTION = "TrackExceptionEvent"
    TRACK_STUCK = "TrackStuckEvent"


class LavalinkPlayerState(NamedTuple):
    time: int
    position: int


class TrackLoadType(enum.Enum):
    SINGLE = "TRACK_LOADED"
    PLAYLIST = "PLAYLIST_LOADED"
    SEARCH_RESULT = "SEARCH_RESULT"
    NO_MATCHES = "NO_MATCHES"
    LOAD_FAILED = "LOAD_FAILED"


class TrackPlaylistInfo(NamedTuple):
    name: str
    selected_track: int


class TrackInfo(NamedTuple):
    identifier: str
    is_seekable: bool
    author: str
    length: int
    is_stream: bool
    position: int
    title: str
    uri: str


class Track(NamedTuple):
    track: str
    info: TrackInfo

    @classmethod
    def from_result(cls, data: Dict[str, Any]) -> "Track":
        track = data["track"]
        info = TrackInfo(**data["info"])
        return Track(track, info)


class LoadTracksResult(NamedTuple):
    load_type: TrackLoadType
    playlist_info: TrackPlaylistInfo = None
    tracks: List[Track] = []

    def __len__(self) -> int:
        return len(self.tracks)

    @property
    def track(self) -> Track:
        if self.load_type == TrackLoadType.SINGLE:
            return self.tracks[0]
        else:
            raise TypeError(f"{self.load_type} doesn't have a singular track")

    @classmethod
    def from_result(cls, data: Dict[str, Any]) -> "LoadTracksResult":
        load_type = TrackLoadType(data["loadType"])
        playlist_info = data["playlistInfo"]
        if playlist_info:
            playlist_info = TrackPlaylistInfo(**playlist_info)
        else:
            playlist_info = None

        tracks = list(map(Track.from_result, data["tracks"]))

        return LoadTracksResult(load_type, playlist_info, tracks)
