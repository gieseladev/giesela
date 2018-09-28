import abc
import asyncio
import enum
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, TYPE_CHECKING, Type, Union

from discord import User

from giesela import ExtractionError, Extractor

if TYPE_CHECKING:
    from .playlist import Playlist
    from .manager import PlaylistManager

__all__ = ["PlaylistRecovery", "get_recovery_plan"]

log = logging.getLogger(__name__)

GPLType = Union[Dict[str, Any], List[Dict[str, Any]]]


class GPLVersion(enum.IntEnum):
    v1 = 1
    v2 = 2
    v3 = 3


class FixStep(metaclass=abc.ABCMeta):
    def __init__(self, *, description: str = None) -> None:
        self.description = description

    @property
    def progress(self) -> Optional[float]:
        return None

    @property
    def can_apply(self) -> bool:
        return True

    @abc.abstractmethod
    async def apply(self, data: GPLType) -> GPLType:
        pass


class InputStep(FixStep, abc.ABC):
    _args: Dict[str, Any]

    def __init__(self, *, required_input: Dict[str, Type], supplied_input: Dict[str, Any] = None, **kwargs) -> None:
        kwargs.setdefault("description", "Getting input")
        super().__init__(**kwargs)

        self._required_input = required_input
        self._args = supplied_input or {}

    @property
    def can_apply(self) -> bool:
        return self.has_all_input

    @property
    def has_all_input(self) -> bool:
        return set(self._args) == set(self._required_input)

    @property
    def required_input(self) -> Dict[str, Any]:
        return self._required_input

    @property
    def missing_input(self) -> Dict[str, Any]:
        required = self._required_input.copy()
        for arg in self._args:
            required.pop(arg)
        return required

    @property
    def args(self) -> Dict[str, Any]:
        return self._args

    async def provide(self, **kwargs):
        for key, value in kwargs.items():
            required_type = self._required_input.get(key)
            if not required_type:
                raise KeyError(f"Key {key} not required input")

            if not isinstance(value, required_type):
                raise TypeError(f"{key} needs to be of type {required_type}, not {type(value)}")

            self._args[key] = value


class ExtractorStep(FixStep, abc.ABC):
    _extractor: Extractor

    @property
    def can_apply(self) -> bool:
        return self.has_extractor

    @property
    def has_extractor(self) -> bool:
        return hasattr(self, "_extractor")

    @property
    def extractor(self) -> Extractor:
        if not self.has_extractor:
            raise ValueError("No extractor provided")
        return self._extractor

    @extractor.setter
    def extractor(self, value: Extractor):
        setattr(self, "_extractor", value)


class AddPlaylistMeta(InputStep):
    def __init__(self, *, name: str = None, author: User = None, **kwargs) -> None:
        kwargs["required_input"] = dict(name=str, author=User)
        kwargs["supplied_input"] = {key: value for key, value in dict(name=name, author=author).items() if value}
        super().__init__(**kwargs)

    async def apply(self, data: GPLType):
        if not isinstance(data, list):
            raise ValueError("v1 data needs to be a list...")
        author = self.args["author"]
        if isinstance(author, User):
            author = author.id

        return dict(name=self.args["name"], author_id=author, entries=data)


class UpdateEntries(ExtractorStep):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("description", "Extracting additional data...")
        super().__init__(**kwargs)

        self.broken_entries = []

        self._total_entries = 0
        self._handled_entries = 0

    @property
    def progress(self) -> float:
        if not self._total_entries:
            return 0
        return self._handled_entries / self._total_entries

    @classmethod
    def test_valid_entry(cls, entry: Dict[str, Any]) -> bool:
        try:
            entry = entry["entry"]
            track = entry["track"]
            uri = entry["uri"]
            is_seekable = entry["seekable"]

            if all((track, uri, is_seekable)):
                return True
        except KeyError:
            return False

    async def _fix_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.test_valid_entry(entry):
            return entry

        uri = entry["url"]
        extra = dict(title=entry.get("song_title"), artist=entry.get("artist"), artist_image=entry.get("artist_image"), cover=entry.get("cover"),
                     album=entry.get("album"))
        try:
            entry = await self.extractor.get_entry(uri)
        except (ExtractionError, TypeError):
            log.warning(f"Couldn't extract {uri}")
            self.broken_entries.append(entry)
            return

        entry = entry.to_dict()
        for key, value in extra.items():
            if not value:
                continue
            entry[key] = value
        return dict(entry=entry)

    async def fix_entry(self, entry: Dict[str, Any]):
        result = await self._fix_entry(entry)
        self._handled_entries += 1
        return result

    async def apply(self, data: GPLType):
        _entries = data["entries"]
        self._total_entries = len(_entries)

        coros = (self.fix_entry(entry) for entry in _entries)
        entries = await asyncio.gather(*coros)
        data["entries"] = list(filter(None, entries))
        return data


class PlaylistRecovery:
    current_step: Optional[FixStep]

    def __init__(self, steps: List[FixStep], data: GPLType, basic_info: Dict[str, Any] = None) -> None:
        self.steps = steps
        self.step_iter = iter(steps)
        self.current_step = None
        self._next_step()

        self.data = data
        self.information = basic_info

    def __iter__(self) -> Iterable[FixStep]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def done(self) -> bool:
        return self.current_step is None

    @property
    def current_step_index(self) -> int:
        try:
            return self.steps.index(self.current_step)
        except ValueError:
            return 0

    @property
    def is_input(self) -> bool:
        return isinstance(self.current_step, InputStep)

    @property
    def needs_input(self) -> bool:
        return self.is_input and not self.current_step.has_all_input

    @property
    def needs_extractor(self) -> bool:
        step = self.current_step
        return isinstance(step, ExtractorStep) and not step.has_extractor

    @property
    def can_advance(self) -> bool:
        return self.current_step.can_apply

    @property
    def input_steps(self) -> List[InputStep]:
        return [step for step in self if isinstance(step, InputStep)]

    @property
    def extractor_steps(self) -> List[ExtractorStep]:
        return [step for step in self if isinstance(step, ExtractorStep)]

    async def provide_input(self, args):
        if isinstance(self.current_step, InputStep):
            await self.current_step.provide(**args)
        else:
            raise TypeError(f"{self.current_step} doesn't need any input")

    def provide_extractor(self, extractor: Extractor, only_current: bool = False):
        if only_current:
            if isinstance(self.current_step, ExtractorStep):
                self.current_step.extractor = extractor
            else:
                raise TypeError(f"{self.current_step} doesn't need an extractor")
        else:
            for step in self.extractor_steps:
                step.extractor = extractor

    def _next_step(self):
        self.current_step = next(self.step_iter, None)

    def try_build(self) -> Optional["Playlist"]:
        from .playlist import Playlist

        try:
            playlist = Playlist.from_gpl(self.data)
        except Exception:
            log.exception("Couldn't build playlist")
        else:
            return playlist

    async def advance(self):
        self.data = await self.current_step.apply(self.data)
        self._next_step()

    async def recover(self) -> Optional["Playlist"]:
        while not self.done:
            await self.advance()

        return self.try_build()


def get_version(data: GPLType) -> Optional[GPLVersion]:
    # v1 was a list of entries, no metadata
    if isinstance(data, list):
        return GPLVersion.v1
    elif not isinstance(data, dict):
        return None

    entries = data.get("entries")
    if entries:
        entry = entries[0]
        # v2 doesn't use wrappers
        if "entry" not in entry:
            return GPLVersion.v2

    # should be fine
    return GPLVersion.v3


def _extract_old_entry_meta(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    author_id = None
    playlist_name = None
    playlist_cover = None

    for entry in entries:
        try:
            meta = entry["meta"]
        except Exception:
            continue

        try:
            playlist = meta["playlist"]["value"]
            playlist_name = playlist.get("name")
            playlist_cover = playlist.get("cover")
        except Exception:
            pass

        try:
            author = meta["author"]
            author_id = int(author["id"])
        except Exception:
            pass

        if author_id and playlist_name and playlist_cover:
            break

    return dict((key, value) for key, value in (("author_id", author_id), ("name", playlist_name), ("cover", playlist_cover)) if value)


def _try_extract_keys(data: Mapping, keys: Iterable):
    _data = {}
    for key in keys:
        try:
            _data[key] = data[key]
        except KeyError:
            continue
    return _data


def get_playlist_information(data: GPLType, version: GPLVersion = None) -> Dict[str, Any]:
    version = version or get_version(data)

    if not version:
        return {}

    info = {}

    if version == GPLVersion.v1:
        info = _extract_old_entry_meta(data)
    elif version == GPLVersion.v2:
        info = _extract_old_entry_meta(data.get("entries"))

    if version >= GPLVersion.v2:
        extracted = _try_extract_keys(data, ("name", "description", "author_id", "cover", "editor_ids", "gpl_id"))
        for key, value in extracted.items():
            if value:
                info[key] = value

    return info


def get_recovery_plan(manager: "PlaylistManager", data: GPLType) -> Optional[PlaylistRecovery]:
    version = get_version(data)
    if not version:
        # nothing we can do about this
        return None

    steps = []

    info = get_playlist_information(data, version)

    if version <= GPLVersion.v1:
        author = manager.bot.get_user(info.get("author_id"))
        steps.append(AddPlaylistMeta(name=info.get("name"), author=author))
    if version <= GPLVersion.v2:
        steps.append(UpdateEntries())

    if not steps:
        return None

    return PlaylistRecovery(steps, data, info)
