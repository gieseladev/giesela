import enum
import time
from dataclasses import dataclass  # since < 3.7 is out of the picture anyway, why not use dataclasses as well xD
from typing import Any, Dict, List, NamedTuple, Optional, Union

from . import utils

__all__ = ["LavalinkEvent",
           "TrackEndReason", "LavalinkEventData", "TrackEndEventData", "TrackExceptionEventData", "TrackStuckEventData", "TrackEventDataType",
           "LavalinkPlayerState",
           "TrackLoadType", "TrackPlaylistInfo", "TrackInfo", "Track", "LoadTracksResult", "LoadTrackSearcher",
           "LavalinkStats"]


class LavalinkEvent(enum.Enum):
    TRACK_END = "TrackEndEvent"
    TRACK_EXCEPTION = "TrackExceptionEvent"
    TRACK_STUCK = "TrackStuckEvent"


class TrackEndReason(enum.Enum):
    FINISHED = "FINISHED"
    LOAD_FAILED = "LOAD_FAILED"
    STOPPED = "STOPPED"
    REPLACED = "REPLACED"
    CLEANUP = "CLEANUP"

    @property
    def start_next(self) -> bool:
        return self in {TrackEndReason.FINISHED, TrackEndReason.LOAD_FAILED}


@dataclass
class LavalinkEventData:
    track: str

    # noinspection PyArgumentList
    @classmethod
    def from_data(cls, event: LavalinkEvent, data: Dict[str, Any]):
        track = data["track"]

        if event == LavalinkEvent.TRACK_END:
            reason = TrackEndReason(data["reason"])
            return TrackEndEventData(track, reason)
        elif event == LavalinkEvent.TRACK_EXCEPTION:
            return TrackExceptionEventData(track, data["error"])
        elif event == LavalinkEvent.TRACK_STUCK:
            return TrackStuckEventData(track, data["thresholdMs"])


@dataclass
class TrackEndEventData(LavalinkEventData):
    reason: TrackEndReason


@dataclass
class TrackExceptionEventData(LavalinkEventData):
    error: str


@dataclass
class TrackStuckEventData(LavalinkEventData):
    threshold_ms: int


TrackEventDataType = Union[TrackEndEventData, TrackExceptionEventData, TrackStuckEventData]


class LavalinkPlayerState(NamedTuple):
    time: int
    position: int

    @property
    def seconds(self) -> float:
        return utils.from_milli(self.position)

    @property
    def time_seconds(self) -> float:
        return utils.from_milli(self.time)

    @property
    def age(self) -> float:
        return max(time.time() - self.time_seconds, 0)

    @property
    def estimate_seconds_now(self) -> float:
        return self.seconds + self.age


class TrackLoadType(enum.Enum):
    SINGLE = "TRACK_LOADED"
    PLAYLIST = "PLAYLIST_LOADED"
    SEARCH_RESULT = "SEARCH_RESULT"
    NO_MATCHES = "NO_MATCHES"
    LOAD_FAILED = "LOAD_FAILED"

    @property
    def has_results(self) -> bool:
        return self not in {TrackLoadType.NO_MATCHES, TrackLoadType.LOAD_FAILED}


class TrackPlaylistInfo(NamedTuple):
    name: str
    selected_track: Optional[int]

    @classmethod
    def from_result(cls, data: Dict[str, Any]) -> "TrackPlaylistInfo":
        data["selected_track"] = data.pop("selectedTrack", None)
        return TrackPlaylistInfo(**data)


class TrackInfo(NamedTuple):
    identifier: str
    is_seekable: bool
    author: str
    length: int
    is_stream: bool
    position: int
    title: str
    uri: str

    @property
    def seconds(self) -> float:
        return utils.from_milli(self.position)

    @property
    def duration(self) -> Optional[float]:
        if self.is_stream:
            return None
        return utils.from_milli(self.length)

    @property
    def start_position(self) -> Optional[float]:
        if self.position:
            return utils.from_milli(self.position)

        return None


class Track(NamedTuple):
    track: str
    info: TrackInfo

    @classmethod
    def from_result(cls, data: Dict[str, Any]) -> "Track":
        track = data["track"]
        info = data["info"]
        info["is_seekable"] = info.pop("isSeekable")
        info["is_stream"] = info.pop("isStream")
        info = TrackInfo(**info)
        return Track(track, info)


class LoadTracksResult(NamedTuple):
    load_type: TrackLoadType
    playlist_info: Optional[TrackPlaylistInfo]
    tracks: List[Track]

    def __len__(self) -> int:
        return len(self.tracks)

    @property
    def track(self) -> Optional[Track]:
        if self.load_type == TrackLoadType.SINGLE:
            return self.tracks[0]
        elif self.load_type == TrackLoadType.PLAYLIST:
            index = self.playlist_info.selected_track
            if index is not None and 0 <= index < len(self.tracks):
                return self.tracks[index]

        return None

    @classmethod
    def from_result(cls, data: Dict[str, Any]) -> "LoadTracksResult":
        load_type = TrackLoadType(data["loadType"])
        playlist_info = data["playlistInfo"]
        playlist_info = TrackPlaylistInfo.from_result(playlist_info) if playlist_info else None

        tracks = list(map(Track.from_result, data["tracks"]))

        return LoadTracksResult(load_type, playlist_info, tracks)


class LoadTrackSearcher(enum.Enum):
    YOUTUBE = "ytsearch"
    SOUNDCLOUD = "scsearch"


class LavalinkMemoryStats(NamedTuple):
    free: int
    reservable: int
    used: int
    allocated: int

    @classmethod
    def from_data(cls, data):
        return LavalinkMemoryStats(**data)


class LavalinkCPUStats(NamedTuple):
    cores: int
    system_load: float
    lavalink_load: float

    @classmethod
    def from_data(cls, data):
        data["system_load"] = data.pop("systemLoad")
        data["lavalink_load"] = data.pop("lavalinkLoad")
        return LavalinkCPUStats(**data)


class LavalinkFrameStats(NamedTuple):
    sent: int
    deficit: int
    nulled: int

    @classmethod
    def from_data(cls, data):
        return LavalinkFrameStats(**data)


class LavalinkStats(NamedTuple):
    players: int
    playing_players: int
    uptime: int
    memory: LavalinkMemoryStats
    cpu: LavalinkCPUStats
    frame_stats: Optional[LavalinkFrameStats]

    @property
    def uptime_seconds(self) -> float:
        return utils.from_milli(self.uptime)

    @classmethod
    def from_data(cls, data):
        data["playing_players"] = data.pop("playingPlayers")
        data["memory"] = LavalinkMemoryStats.from_data(data["memory"])
        data["cpu"] = LavalinkCPUStats.from_data(data["cpu"])
        frame_stats = data.pop("frameStats", None)
        data["frame_stats"] = LavalinkFrameStats.from_data(frame_stats) if frame_stats else None

        return cls(**data)
