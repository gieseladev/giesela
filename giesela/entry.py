import abc
import copy
import logging
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING, Type, Union

from discord import User

from .lib import lavalink
from .radio import RadioSongData, RadioStation

if TYPE_CHECKING:
    from .player import GieselaPlayer

__all__ = ["PlayableEntry", "BaseEntry",
           "ChapterData", "SpecificChapterData", "HasChapters",
           "BasicEntry", "ChapterEntry", "RadioEntry",
           "EntryWrapper", "PlayerEntry", "QueueEntry", "HistoryEntry"]

log = logging.getLogger(__name__)

_DEFAULT = object()


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

    def __str__(self) -> str:
        return self.uri

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
    def from_track_info(cls, track: str, info: lavalink.TrackInfo, **extra) -> "PlayableEntry":
        kwargs = cls.kwargs_from_track_info(track, info)
        kwargs.update(extra)
        return cls(**kwargs)

    def copy(self):
        return copy.copy(self)

    def to_dict(self) -> Dict[str, Any]:
        return dict(type=type(self).__name__, track=self._track, uri=self._uri, seekable=self._is_seekable,
                    duration=self._duration, start_position=self.start_position, end_position=self.end_position)


class BaseEntry(metaclass=abc.ABCMeta):
    title: str
    artist: Optional[str]
    cover: Optional[str]
    artist_image: Optional[str]
    album: Optional[str]

    def __str__(self) -> str:
        if self.artist:
            return f"{self.artist} - {self.title}"
        return self.title

    @property
    def sort_attr(self):
        if self.artist:
            return self.artist, self.title
        return self.title


class ChapterData(BaseEntry):

    def __init__(self, *, title: str, artist: str = None, cover: str = None, artist_image: str = None, album: str = None):
        self.title = title
        self.artist = artist
        self.cover = cover
        self.artist_image = artist_image
        self.album = album

    def to_dict(self) -> Dict[str, Any]:
        return dict(title=self.title,
                    artist=self.artist, cover=self.cover, artist_image=self.artist_image, album=self.album)


class SpecificChapterData(ChapterData):
    def __init__(self, *, start: float, duration: float = None, end: float = None, **kwargs):
        super().__init__(**kwargs)
        self.start = start

        if not ((duration is not None) ^ (end is not None)):
            raise ValueError("Either duration or end required!")

        self.duration = duration or end - start
        self.end = end or start + duration

    def contains(self, timestamp: float) -> bool:
        return self.start <= timestamp < self.end

    def get_chapter_progress(self, progress: float) -> float:
        return progress - self.start

    def to_dict(self):
        data = super().to_dict()
        data.update(start=self.start, duration=self.duration)
        return data


class HasChapters(metaclass=abc.ABCMeta):
    @property
    def has_chapters(self) -> bool:
        return True

    @abc.abstractmethod
    async def get_chapter(self, progress: float) -> ChapterData:
        pass


class BasicEntry(BaseEntry, PlayableEntry):
    def __init__(self, *, title: str, artist: str, cover: str = None, artist_image: str = None, album: str = None, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.artist = artist
        self.cover = cover
        self.artist_image = artist_image
        self.album = album

    @classmethod
    def kwargs_from_track_info(cls, track: str, info: lavalink.TrackInfo):
        kwargs = super().kwargs_from_track_info(track, info)
        kwargs.update(title=info.title, artist=info.author)
        return kwargs

    def to_dict(self):
        data = super().to_dict()
        data.update(title=self.title, artist=self.artist, cover=self.cover, artist_image=self.artist_image, album=self.album)
        return data


class ChapterEntry(BasicEntry, HasChapters):

    def __init__(self, chapters: List[SpecificChapterData], **kwargs):
        super().__init__(**kwargs)
        self.chapters = chapters

    @property
    def has_chapters(self):
        return bool(self.chapters)

    async def get_chapter(self, timestamp: float) -> Optional[ChapterData]:
        return next((chapter for chapter in self.chapters if chapter.contains(timestamp)), None)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        chapters = [chapter.to_dict() for chapter in self.chapters]
        data.update(chapters=chapters)
        return data


class RadioEntry(BaseEntry, PlayableEntry, HasChapters):
    _song_data: Optional[RadioSongData]
    _chapter: Optional[ChapterData]

    def __init__(self, *, station: RadioStation, **kwargs):
        super().__init__(**kwargs)
        self.station = station
        self.title = station.name
        self.cover = station.logo
        self.artist = None
        self.artist_image = None
        self.album = None

        self._song_data = None
        self._chapter = None

    def __str__(self) -> str:
        return self.title

    @property
    def has_chapters(self):
        return self.station.has_song_data

    async def get_chapter(self, progress: float):
        if self.needs_update:
            await self.update(progress)
        return self._chapter

    async def update(self, progress: float):
        data = await self.station.get_song_data()
        self._song_data = data

        kwargs = dict(title=data.title, artist=data.artist, cover=data.cover, artist_image=data.artist_image, album=data.album)
        if data.progress is not None and data.duration is not None:
            chapter = SpecificChapterData(start=progress - data.estimated_progress, duration=data.duration, **kwargs)
        else:
            chapter = ChapterData(**kwargs)

        self._chapter = chapter

    @property
    def needs_update(self) -> bool:
        if not self.station.has_song_data:
            return False
        data = self._song_data
        if not data:
            return True

        if data.estimated_progress is not None:
            return data.estimated_progress >= data.duration

        return data.age >= self.station.update_interval

    @property
    def song_data(self) -> Optional[RadioSongData]:
        return self._song_data


class EntryWrapper(metaclass=abc.ABCMeta):
    def __init__(self, *, entry: Union[PlayableEntry, "EntryWrapper"], **_):
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

    def add_wrapper(self, wrapper: Type["EntryWrapper"], **kwargs):
        wrap = wrapper(entry=self._entry, **kwargs)
        self._entry = wrap

    def remove_wrapper(self, wrapper: Type["EntryWrapper"]):
        if isinstance(self, wrapper):
            raise ValueError("Can't remove top-level wrapper")
        elif isinstance(self.wrapped, wrapper):
            self._entry = self.wrapped._entry
        elif isinstance(self.wrapped, EntryWrapper):
            self.wrapped.remove_wrapper(wrapper)
        else:
            raise TypeError(f"No {wrapper} found in {self}")

    def get_wrapper(self, wrapper: Type["EntryWrapper"]) -> Optional["EntryWrapper"]:
        if isinstance(self, wrapper):
            return self
        elif isinstance(self.wrapped, EntryWrapper):
            return self.wrapped.get_wrapper(wrapper)

    def walk_wrappers(self) -> Iterator["EntryWrapper"]:
        current = self
        while isinstance(current, EntryWrapper):
            yield current
            current = current.wrapped

    def get(self, item: str, default: Any = _DEFAULT):
        for wrapper in self.walk_wrappers():
            try:
                return getattr(wrapper, item)
            except AttributeError:
                continue

        if default is not _DEFAULT:
            return default

        raise AttributeError(f"Couldn't find {item} in {self}")

    def has_wrapper(self, wrapper: Type["EntryWrapper"]) -> bool:
        return bool(self.get_wrapper(wrapper))

    def to_dict(self) -> Dict[str, Any]:
        return dict(entry=self._entry.to_dict())


class PlayerEntry(EntryWrapper):
    _chapter: Optional[ChapterData]

    def __init__(self, *, player: "GieselaPlayer", **kwargs):
        super().__init__(**kwargs)
        self.player = player

        entry = self.entry
        if isinstance(entry, HasChapters):
            self.has_chapters = entry.has_chapters
        else:
            self.has_chapters = False

        self._chapter = None

    @property
    def progress(self) -> float:
        return self.player.progress

    @property
    def time_left(self) -> float:
        return self.entry.duration - self.progress

    @property
    def chapter(self) -> Optional[ChapterData]:
        return self._chapter

    async def get_chapter(self) -> Optional[ChapterData]:
        entry = self.entry
        if self.has_chapters:
            # noinspection PyUnresolvedReferences
            return await entry.get_chapter(self.progress)

    async def update_chapter(self) -> bool:
        if self.has_chapters:
            chapter = await self.get_chapter()
            if chapter != self._chapter:
                self._chapter = chapter
                return True
        return False


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
