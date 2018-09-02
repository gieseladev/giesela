import abc
import copy
import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from discord import User

from .exceptions import (OutdatedEntryError)
from .radio import RadioSongData, RadioStation
from .utils import clean_songname

if TYPE_CHECKING:
    from .player import GieselaPlayer

log = logging.getLogger(__name__)


class BaseEntry(metaclass=abc.ABCMeta):
    track_urn: str
    requester: Optional[User]

    start_position: Optional[float]
    end_position: Optional[float]

    def __init__(self, *, track_urn: str, start_position: float = None, end_position: float = None, requester: User = None):
        self.track_urn = track_urn
        self.requester = requester

        self.start_position = start_position
        self.end_position = end_position

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.track_urn}>"

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: "BaseEntry") -> bool:
        if isinstance(other, BaseEntry):
            return self.track_urn == other.track_urn
        return NotImplemented

    @property
    def sort_attr(self) -> str:
        return self.track_urn

    def copy(self):
        return copy.copy(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEntry":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return dict(type=type(self).__name__, track_urn=self.track_urn, start_position=self.start_position, end_position=self.end_position)

    def to_web_dict(self, player: "GieselaPlayer") -> Dict[str, Any]:
        return self.to_dict()


class RadioStationEntry(BaseEntry):
    station: RadioStation

    def __init__(self, station: RadioStation, **kwargs):
        kwargs.setdefault("title", station.name)
        super().__init__(station.stream, **kwargs)
        self.station = station

    @property
    def link(self) -> str:
        return self.station.website or self.station.stream

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RadioStationEntry":
        data["station"] = RadioStation.from_config(data.pop("station"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(station=self.station.to_dict())
        return data

    @property
    def is_downloaded(self) -> bool:
        return True


class RadioSongEntry(RadioStationEntry):
    _current_song_data: RadioSongData

    def __init__(self, station: RadioStation, song_data: RadioSongData, **kwargs):
        super().__init__(station, **kwargs)
        self._current_song_data = song_data

    async def update(self):
        self._current_song_data = await self.station.get_song_data()

    @property
    def next_update_delay(self) -> float:
        if self.song_data.duration and self.song_data.progress is not None:
            timeout = self.song_data.duration - self.song_progress
        else:
            timeout = self.station.update_interval - self.song_data_age

        if timeout <= 0:
            return 0
        else:
            return timeout + self.station.extra_update_delay

    @property
    def song_data_age(self) -> float:
        return time.time() - self._current_song_data.timestamp

    @property
    def song_data(self) -> RadioSongData:
        return self._current_song_data

    @property
    def song_progress(self) -> Optional[float]:
        if self.song_data.progress is not None:
            progress = self.song_data.progress + self.song_data_age
            if self.song_data.duration:
                progress = min(progress, self.song_data.duration)
            return progress

    @property
    def title(self) -> str:
        artist = self.song_data.artist
        song = self.song_data.song_title
        if song:
            return f"{artist or self.station.name} - {song}"
        elif artist:
            return f"{self.station.name} - {artist}"
        else:
            return super().title

    def to_web_dict(self, player: "GieselaPlayer"):
        data = super().to_web_dict(player)

        if player.current_entry is self:
            data.update(song_progress=self.song_progress, song_data=self.song_data.to_dict())

        return data


class YoutubeEntry(BaseEntry):
    video_id: str
    _title: str
    thumbnail: str

    def __init__(self, *args, video_id: str, title: str, thumbnail: str, **kwargs):
        super().__init__(*args, **kwargs)

        self.video_id = video_id
        self._title = title
        self.thumbnail = thumbnail

    @property
    def title(self) -> str:
        return clean_songname(self._title)

    @property
    def sort_attr(self) -> str:
        return self.title

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(video_id=self.video_id, title=self.title, thumbnail=self.thumbnail)
        return data


class TimestampEntry(YoutubeEntry):
    sub_queue: List[dict]

    def __init__(self, *args, sub_queue: List[dict], **kwargs):
        super().__init__(*args, **kwargs)

        self.sub_queue = sub_queue

    def sub_entry_at(self, timestamp: float) -> Optional[dict]:
        sub_entry = None
        for entry in self.sub_queue:
            if timestamp >= entry["start"] or sub_entry is None:
                sub_entry = entry
            else:
                break

        sub_entry["progress"] = max(timestamp - sub_entry["start"], 0)
        return sub_entry

    def get_sub_entry(self, player: "GieselaPlayer") -> Optional[dict]:
        if player.current_entry is not self:
            return None

        return self.sub_entry_at(player.progress)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(sub_queue=self.sub_queue)
        return data


class GieselaEntry(YoutubeEntry):
    song_title: str
    artist: str
    artist_image: str
    cover: str
    album: str

    def __init__(self, *args, song_title: str, artist: str, artist_image: str, album: str, cover: str, **kwargs):
        super().__init__(*args, **kwargs)

        self.song_title = song_title
        self.artist = artist
        self.artist_image = artist_image
        self.cover = cover
        self.album = album

    @property
    def title(self) -> str:
        return f"{self.artist} - {self.song_title}"

    @property
    def sort_attr(self):
        return self.song_title

    @property
    def lyrics_search_query(self) -> str:
        return f"{self.song_title} - {self.artist}"

    @classmethod
    def upgrade(cls, entry: BaseEntry, **kwargs):
        data = entry.to_dict()
        data.update(entry.meta)
        data.update(kwargs)
        return cls.from_dict(data)

    def to_dict(self):
        data = super().to_dict()
        data.update(song_title=self.song_title, artist=self.artist, artist_image=self.artist_image, cover=self.cover, album=self.album)
        return data


class Entry:
    VERSION = 3
    MAPPING = {
        "RadioSongEntry": RadioSongEntry,
        "RadioStationEntry": RadioStationEntry,
        "YoutubeEntry": YoutubeEntry,
        "TimestampEntry": TimestampEntry,
        "GieselaEntry": GieselaEntry
    }

    def __new__(cls, *args, **kwargs):
        raise Exception("This class is static")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEntry":
        entry_version = data.get("version", 0)

        if entry_version < Entry.VERSION:
            raise OutdatedEntryError("Version parameter signifies an outdated entry")

        entry_type = data.get("type", None)
        if not entry_type:
            raise KeyError("Data does not include a type parameter")

        target = cls.MAPPING.get(entry_type, None)

        if not target:
            raise TypeError("Cannot create an entry with this type")

        return target.from_dict(data)
