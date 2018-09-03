import abc
import copy
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from discord import User

from .lib import lavalink
from .radio import RadioSongData, RadioStation

if TYPE_CHECKING:
    from .player import GieselaPlayer

log = logging.getLogger(__name__)


class PlayableEntry(metaclass=abc.ABCMeta):
    start_position: Optional[float]
    end_position: Optional[float]

    def __init__(self, *, track: str, uri: str, seekable: bool, duration: float = None, start_position: float = None, end_position: float = None):
        self._track = track
        self._uri = uri
        self._is_seekable = seekable
        self._duration = duration

        self.start_position = start_position
        self.end_position = end_position

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.uri}>"

    def __hash__(self) -> int:
        return hash(self.track)

    def __eq__(self, other: "PlayableEntry") -> bool:
        if isinstance(other, PlayableEntry):
            return self.uri == other.uri
        return NotImplemented

    @property
    def track(self) -> str:
        return self._track

    @property
    def uri(self) -> str:
        return self._uri

    @property
    def sort_attr(self):
        return self.uri

    @property
    def track_length(self) -> Optional[float]:
        return self._duration

    @property
    def duration(self) -> Optional[float]:
        start = self.start_position or 0
        end = self.end_position

        if end is None:
            if self._duration is None:
                return None
            else:
                end = self._duration

        return end - start

    @property
    def is_stream(self) -> bool:
        return self._duration is None

    @property
    def is_seekable(self) -> bool:
        return self._is_seekable

    @classmethod
    def kwargs_from_track_info(cls, track: str, info: lavalink.TrackInfo) -> Dict[str, Any]:
        return dict(track=track, uri=info.uri, seekable=info.is_seekable, duration=info.duration, start_position=info.start_position)

    @classmethod
    def from_track_info(cls, track: str, info: lavalink.TrackInfo) -> "PlayableEntry":
        return cls(**cls.kwargs_from_track_info(track, info))

    def copy(self):
        return copy.copy(self)

    def to_dict(self) -> Dict[str, Any]:
        return dict(type=type(self).__name__, track=self._track, uri=self._uri, seekable=self._is_seekable,
                    duration=self._duration, start_position=self.start_position, end_position=self.end_position)


class BaseEntry(PlayableEntry):

    def __init__(self, *, title: str, artist: str, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.artist = artist

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def sort_attr(self):
        return self.artist, self.title

    @classmethod
    def kwargs_from_track_info(cls, track: str, info: lavalink.TrackInfo):
        kwargs = super().kwargs_from_track_info(track, info)
        kwargs.update(title=info.title, artist=info.author)
        return kwargs

    def to_dict(self):
        data = super().to_dict()
        data.update(title=self.title, artist=self.artist)
        return data


class RadioEntry(PlayableEntry):
    def __init__(self, *, station: RadioStation, song_data: RadioSongData = None, **kwargs):
        super().__init__(**kwargs)
        self.station = station
        self._current_song_data = song_data

    def __str__(self) -> str:
        if self.artist:
            origin = self.artist if self.title else self.station.name
            title = self.title or self.artist
        elif self.title:
            origin = self.station.name
            title = self.title
        else:
            return self.station.name

        return f"{origin} - {title}"

    async def update(self):
        self._current_song_data = await self.station.get_song_data()

    @property
    def next_update_delay(self) -> Optional[float]:
        if not self._current_song_data:
            return

        if self.song_data.duration and self.song_data.progress is not None:
            timeout = self.song_data.duration - self.song_progress
        else:
            timeout = self.station.update_interval - self.song_data_age

        if timeout <= 0:
            return 0
        else:
            return timeout + self.station.extra_update_delay

    @property
    def song_data_age(self) -> Optional[float]:
        if self._current_song_data:
            return time.time() - self._current_song_data.timestamp

    @property
    def song_data(self) -> Optional[RadioSongData]:
        return self._current_song_data

    @property
    def song_progress(self) -> Optional[float]:
        if self.song_data and self.song_data.progress is not None:
            progress = self.song_data.progress + self.song_data_age
            if self.song_data.duration:
                progress = min(progress, self.song_data.duration)
            return progress

    @property
    def title(self) -> Optional[str]:
        return self.song_data and self.song_data.title

    @property
    def artist(self) -> Optional[str]:
        return self.song_data and self.song_data.artist

    @property
    def artist_image(self) -> Optional[str]:
        return self.song_data and self.song_data.artist_image

    @property
    def cover(self) -> Optional[str]:
        return self.song_data and self.song_data.cover

    @property
    def album(self) -> Optional[str]:
        return self.song_data and self.song_data.album


@dataclass
class ChapterData:
    start: float
    duration: float
    title: str

    @property
    def end(self) -> float:
        return self.start + self.duration

    def contains(self, timestamp: float) -> bool:
        return self.start <= timestamp < self.end

    def to_dict(self) -> Dict[str, Any]:
        return dict(start=self.start, duration=self.duration, title=self.title)


class ChapterEntry(BaseEntry):

    def __init__(self, chapters: List[ChapterData], **kwargs):
        super().__init__(**kwargs)
        self.chapters = chapters

    def get_chapter(self, timestamp: float) -> Optional[ChapterData]:
        return next((chapter for chapter in self.chapters if chapter.contains(timestamp)), None)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        chapters = [chapter.to_dict() for chapter in self.chapters]
        data.update(chapters=chapters)
        return data


class GieselaEntry(BaseEntry):
    def __init__(self, *, artist_image: str, cover: str, album: str = None, **kwargs):
        super().__init__(**kwargs)

        self.artist_image = artist_image
        self.cover = cover
        self.album = album

    def to_dict(self):
        data = super().to_dict()
        data.update(artist_image=self.artist_image, cover=self.cover, album=self.album)
        return data


class EntryWrapper(metaclass=abc.ABCMeta):
    def __init__(self, *, entry: Union[PlayableEntry, "EntryWrapper"]):
        self._entry = entry

    def __repr__(self) -> str:

        return f"{type(self).__name__} -> {repr(self.wrapped)}"

    @property
    def entry(self) -> PlayableEntry:
        if isinstance(self._entry, EntryWrapper):
            return self._entry.entry
        else:
            return self._entry

    @property
    def wrapped(self) -> Union[PlayableEntry, "EntryWrapper"]:
        return self._entry

    def to_dict(self) -> Dict[str, Any]:
        return dict(entry=self._entry.to_dict())


class PlayerEntry(EntryWrapper):
    def __init__(self, *, player: "GieselaPlayer", **kwargs):
        super().__init__(**kwargs)
        self.player = player

    @property
    def progress(self) -> float:
        return self.player.progress

    @property
    def time_left(self) -> float:
        return self.entry.duration - self.progress


class QueueEntry(EntryWrapper):
    def __init__(self, *, requester: User, request_timestamp: float, **kwargs):
        super().__init__(**kwargs)
        self.requester = requester
        self.request_timestamp = request_timestamp

    def to_dict(self):
        data = super().to_dict()
        data.update(request_timestamp=self.request_timestamp)
        return data


class HistoryEntry(EntryWrapper):
    def __init__(self, *, finish_timestamp: float, **kwargs):
        super().__init__(**kwargs)
        self.finish_timestamp = finish_timestamp

    def to_dict(self):
        data = super().to_dict()
        data.update(finish_timestamp=self.finish_timestamp)
        return data
