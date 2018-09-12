import abc
import copy
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING, Type, Union

from discord import User

from .lib import lavalink
from .radio import RadioSongData, RadioStation, RadioStationManager
from .utils import url_utils

if TYPE_CHECKING:
    from .queue import EntryQueue
    from .player import GieselaPlayer

__all__ = ["load_entry_from_dict",
           "PlayableEntry", "BaseEntry",
           "ChapterData", "SpecificChapterData", "HasChapters",
           "BasicEntry", "ChapterEntry", "RadioEntry",
           "CanWrapEntryType",
           "EntryWrapper", "PlayerEntry", "QueueEntry", "HistoryEntry"]

log = logging.getLogger(__name__)

_DEFAULT = object()

_ENTRY_MAP: Dict[str, Type["PlayableEntry"]] = {}


class _RegisterEntryMeta(abc.ABCMeta, type):
    def __new__(mcs, *args):
        cls = super().__new__(mcs, *args)
        _ENTRY_MAP[cls.__name__] = cls
        return cls


def load_entry_from_dict(data: Dict[str, Any]) -> "PlayableEntry":
    _cls = data.pop("cls", None)
    if not _cls:
        raise KeyError("Data doesn't have a cls")
    cls = _ENTRY_MAP.get(_cls)
    if not cls:
        raise KeyError(f"Cls {_cls} unknown!")
    return cls.from_dict(data)


class Reducible(metaclass=abc.ABCMeta):
    def to_dict(self) -> Dict[str, Any]:
        return {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Any:
        try:
            # noinspection PyArgumentList
            return cls(**data)
        except Exception:
            if isinstance(data, cls):
                return data
            raise


class OrderByAttribute(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def sort_attr(self) -> str:
        pass

    def __eq__(self, other):
        try:
            return self.sort_attr.__eq__(other.sort_attr)
        except AttributeError:
            return NotImplemented

    def __gt__(self, other):
        try:
            return self.sort_attr.__gt__(other.sort_attr)
        except AttributeError:
            return NotImplemented

    def __lt__(self, other):
        try:
            return self.sort_attr.__lt__(other.sort_attr)
        except AttributeError:
            return NotImplemented

    def __ge__(self, other):
        try:
            return self.sort_attr.__ge__(other.sort_attr)
        except AttributeError:
            return NotImplemented

    def __le__(self, other):
        try:
            return self.sort_attr.__le__(other.sort_attr)
        except AttributeError:
            return NotImplemented


class PlayableEntry(Reducible, OrderByAttribute, metaclass=_RegisterEntryMeta):
    start_position: Optional[float]
    end_position: Optional[float]

    def __init__(self, *, track: str, uri: str, seekable: bool, duration: float = None, start_position: float = None, end_position: float = None,
                 **_):
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
    def url(self) -> Optional[str]:
        if url_utils.is_url(self.uri):
            return self.uri

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
        data = super().to_dict()
        data.update(cls=type(self).__name__, track=self._track, uri=self._uri, seekable=self._is_seekable)
        if self._duration:
            data["duration"] = self._duration
        if self.start_position is not None:
            data["start_position"] = self.start_position
        if self.end_position is not None:
            data["end_position"] = self.end_position
        return data


class BaseEntry(Reducible, metaclass=abc.ABCMeta):
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

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        pairs = (("title", self.title), ("artist", self.artist), ("cover", self.cover), ("artist_image", self.artist_image), ("album", self.album))
        data.update(((key, value) for key, value in pairs if value))
        return data

    def copy(self):
        return copy.copy(self)


class ChapterData(BaseEntry):

    def __init__(self, *, title: str, artist: str = None, cover: str = None, artist_image: str = None, album: str = None):
        self.title = title
        self.artist = artist
        self.cover = cover
        self.artist_image = artist_image
        self.album = album


class SpecificChapterData(ChapterData):
    def __init__(self, *, start: float, duration: float = None, end: float = None, **kwargs):
        super().__init__(**kwargs)
        self._start = start

        if duration is not None:
            self.duration = duration
        elif end is not None:
            self.end = end
        else:
            raise ValueError("Either duration or end required!")

    @property
    def start(self) -> float:
        return self._start

    @start.setter
    def start(self, value: float):
        start_delta = value - self._start
        self._start = value
        self.duration -= start_delta

    @property
    def end(self) -> float:
        return self.start + self.duration

    @end.setter
    def end(self, value: float):
        self.duration = value - self.start

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
    def __init__(self, *, title: str, artist: str = None, cover: str = None, artist_image: str = None, album: str = None, **kwargs):
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


class ChapterEntry(BasicEntry, HasChapters):

    def __init__(self, *, chapters: List[SpecificChapterData], **kwargs):
        super().__init__(**kwargs)
        self.chapters = chapters

    @property
    def has_chapters(self):
        return bool(self.chapters)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        chapters = data.pop("chapters", [])
        chapters = [SpecificChapterData.from_dict(chapter) for chapter in chapters]
        data["chapters"] = chapters
        return cls(**data)

    async def get_chapter(self, timestamp: float) -> Optional[SpecificChapterData]:
        return next((chapter for chapter in self.chapters if chapter.contains(timestamp)), None)

    async def get_next_chapter(self, timestamp: float) -> Optional[SpecificChapterData]:
        for chapter in self.chapters:
            if timestamp > chapter.start:
                return chapter

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        chapters = [chapter.to_dict() for chapter in self.chapters]
        data.update(chapters=chapters)
        return data


class RadioEntry(BaseEntry, PlayableEntry, HasChapters):
    wrapper: "EntryWrapper"

    _song_data: Optional[RadioSongData]
    _chapter: Optional[ChapterData]

    def __init__(self, *, station: Union[RadioStation, str], **kwargs):
        super().__init__(**kwargs)
        if isinstance(station, RadioStation):
            self._station = station
            self._station_name = station.name
            self.title = station.name
            self.cover = station.logo
        else:
            self._station_name = station
            self._station = None
            self.title = station
            self.cover = None

        self.artist = None
        self.artist_image = None
        self.album = None

        self._song_data = None
        self._chapter = None

    def __str__(self) -> str:
        return self.title

    @property
    def station_manager(self) -> RadioStationManager:
        wrapper = getattr(self, "wrapper")
        queue = wrapper.highest_wrapper.get("queue")
        return queue.bot.station_manager

    @property
    def station(self) -> RadioStation:
        if not self._station:
            self._station = self.station_manager.find_station(self._station_name)

        return self._station

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

    def to_dict(self):
        data = super().to_dict()
        data["station"] = self._station_name
        return data


def load_wrapper_from_dict(data: Dict[str, Any], **pass_down) -> Union["EntryWrapper", PlayableEntry]:
    _cls = data.pop("cls", None)
    if not _cls:
        raise KeyError("Data doesn't have a cls")
    cls = _ENTRY_MAP.get(_cls)
    if not cls:
        raise KeyError(f"Cls {_cls} unknown!")

    if issubclass(cls, EntryWrapper):
        return cls.from_dict(data, **pass_down)

    return cls.from_dict(data)


# TODO at this point this has just become a double-linked list, might as well use a real list or something xD
class EntryWrapper(Reducible, metaclass=_RegisterEntryMeta):
    wrapper: Optional["EntryWrapper"]

    def __init__(self, *, entry: "CanWrapEntryType", **_):
        self.wrapper = None
        self._set_entry(entry)

    def __repr__(self) -> str:
        return f"{type(self).__name__} -> {repr(self.wrapped)}"

    @property
    def entry(self) -> PlayableEntry:
        if isinstance(self._entry, EntryWrapper):
            return self._entry.entry
        else:
            return self._entry

    def _set_entry(self, entry: "CanWrapEntryType"):
        self._entry = entry
        entry.wrapper = self

    @property
    def wrapped(self) -> "CanWrapEntryType":
        return self._entry

    @property
    def lowest_wrapper(self) -> "EntryWrapper":
        *_, wrapper = self.walk_wrappers()
        return wrapper

    @property
    def highest_wrapper(self) -> "EntryWrapper":
        *_, wrapper = self.walk_wrappers(down=False)
        return wrapper

    def add_wrapper(self, wrapper: Union[Type["EntryWrapper"], "EntryWrapper"], **kwargs):
        if isinstance(wrapper, EntryWrapper):
            wrap = wrapper
            wrap._entry = self._entry
        else:
            wrap = wrapper(entry=self._entry, **kwargs)
        self._set_entry(wrap)

    def remove_wrapper(self, wrapper: Type["EntryWrapper"]):
        if isinstance(self, wrapper):
            raise ValueError("Can't remove top-level wrapper")
        elif isinstance(self.wrapped, wrapper):
            self._set_entry(self.wrapped.entry)
        elif isinstance(self.wrapped, EntryWrapper):
            self.wrapped.remove_wrapper(wrapper)
        else:
            raise TypeError(f"No {wrapper} found in {self}")

    def get_wrapped(self, wrapper: Type["EntryWrapper"]) -> Optional["EntryWrapper"]:
        if isinstance(self, wrapper):
            return self
        elif isinstance(self.wrapped, EntryWrapper):
            return self.wrapped.get_wrapped(wrapper)

    def walk_wrappers(self, down: bool = True) -> Iterator["EntryWrapper"]:
        current = self
        while isinstance(current, EntryWrapper):
            yield current
            if down:
                current = current.wrapped
            else:
                current = current.wrapper

    def get(self, item: str, default: Any = _DEFAULT):
        for wrapper in self.walk_wrappers():
            try:
                return getattr(wrapper, item)
            except AttributeError:
                continue

        if default is not _DEFAULT:
            return default

        raise AttributeError(f"Couldn't find {item} in {self}")

    def has_wrapped(self, wrapper: Type["EntryWrapper"]) -> bool:
        return bool(self.get_wrapped(wrapper))

    def to_dict(self) -> Dict[str, Any]:
        return dict(cls=type(self).__name__, entry=self.wrapped.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **pass_down):
        raw_entry = data.pop("entry")
        entry = load_wrapper_from_dict(raw_entry, **pass_down)
        data["entry"] = entry
        return super().from_dict(data)


CanWrapEntryType = Union[EntryWrapper, PlayableEntry]


class PlayerEntry(EntryWrapper):
    _chapter: Optional[ChapterData]

    def __init__(self, *, player: "GieselaPlayer", **kwargs):
        super().__init__(**kwargs)
        self.player = player

        self._chapter = None

    @property
    def progress(self) -> float:
        return self.player.progress

    @property
    def time_left(self) -> float:
        return self.entry.duration - self.progress

    @property
    def has_chapters(self) -> bool:
        entry = self.entry
        return entry.has_chapters if isinstance(entry, HasChapters) else False

    @property
    def chapter(self) -> Optional[ChapterData]:
        return self._chapter

    def change_entry(self, new_entry: PlayableEntry):
        wrapper = self.lowest_wrapper
        wrapper._entry = new_entry
        # TODO should emit event

    async def get_chapter(self) -> Optional[ChapterData]:
        entry = self.entry
        if self.has_chapters:
            # noinspection PyUnresolvedReferences
            return await entry.get_chapter(self.progress)

    async def get_next_chapter(self) -> Optional[ChapterData]:
        entry = self.entry
        if isinstance(entry, ChapterEntry):
            return await entry.get_next_chapter(self.progress)

    async def update_chapter(self) -> bool:
        if self.has_chapters:
            chapter = await self.get_chapter()
            if chapter != self._chapter:
                self._chapter = chapter
                return True
        return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **pass_down):
        data["player"] = pass_down["player"]
        return super().from_dict(data, **pass_down)


class QueueEntry(EntryWrapper):
    def __init__(self, *, queue: "EntryQueue", requester_id: int, request_timestamp: float, **kwargs):
        super().__init__(**kwargs)
        self.queue = queue
        self.requester_id = requester_id
        self.request_timestamp = request_timestamp

    @property
    def requester(self) -> User:
        return self.queue.bot.get_user(self.requester_id)

    def to_dict(self):
        data = super().to_dict()
        data.update(requester_id=self.requester_id, request_timestamp=self.request_timestamp)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **pass_down):
        data["queue"] = pass_down["queue"]
        return super().from_dict(data, **pass_down)


class HistoryEntry(EntryWrapper):
    def __init__(self, *, finish_timestamp: float, **kwargs):
        super().__init__(**kwargs)

        if not isinstance(self.wrapped, QueueEntry):
            raise TypeError(f"HistoryEntry can only be wrapped around {QueueEntry}, not {type(self.wrapped)}")

        self.finish_timestamp = finish_timestamp

    @property
    def time_passed(self) -> float:
        return time.time() - self.finish_timestamp

    def to_dict(self):
        data = super().to_dict()
        data.update(finish_timestamp=self.finish_timestamp)
        return data
