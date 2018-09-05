import abc
import asyncio
import enum
import logging
from typing import Any, Dict, Iterable, List, Optional, TYPE_CHECKING, Type, Union

from discord import User

from giesela import ExtractionError, Extractor

if TYPE_CHECKING:
    from .playlist import Playlist

__all__ = ["PlaylistRecovery", "get_recovery_plan"]

log = logging.getLogger(__name__)

GPLType = Union[Dict[str, Any], List[Dict[str, Any]]]


class GPLVersion(enum.IntEnum):
    v1 = 1
    v2 = 2
    v3 = 3


class FixStep(metaclass=abc.ABCMeta):
    def __init__(self, *, description: str = None):
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

    def __init__(self, *, required_input: Dict[str, Type], **kwargs):
        kwargs.setdefault("description", "Getting input")
        super().__init__(**kwargs)
        self.required_input = required_input

    @property
    def can_apply(self) -> bool:
        return self.has_input

    @property
    def has_input(self) -> bool:
        return hasattr(self, "_args")

    @property
    def args(self) -> Dict[str, Any]:
        if not self.has_input:
            raise ValueError("No input provided")
        return self._args

    async def provide(self, **kwargs):
        self._args = {}
        required = self.required_input.copy()
        for key, value in kwargs.items():
            required_type = required.pop(key, None)
            if not required_type:
                raise KeyError(f"Key {key} not required input")
            if not isinstance(value, required_type):
                raise TypeError(f"{key} needs to be of type {required_type}, not {type(value)}")
            self._args[key] = value

        if required:
            raise ValueError(f"Not all required arguments provided ({list(required)} missing)")


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


class V1toV2(InputStep):
    def __init__(self, **kwargs):
        kwargs["required_input"] = dict(name=str, author=User)
        super().__init__(**kwargs)

    async def apply(self, data: GPLType):
        if not isinstance(data, list):
            raise ValueError("v1 data needs to be a list...")
        return dict(name=self.args["name"], author_id=self.args["author"].id, entries=data)


class V2toV3(ExtractorStep):
    def __init__(self, **kwargs):
        kwargs.setdefault("description", "Extracting additional data...")
        super().__init__(**kwargs)

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

    def __init__(self, steps: List[FixStep], data: GPLType):
        self.steps = steps
        self.step_iter = iter(steps)
        self.current_step = None
        self._next_step()

        self.data = data

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
    def needs_input(self) -> bool:
        step = self.current_step
        return isinstance(step, InputStep) and not step.has_input

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

    async def provide_input(self, **args):
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


def get_recovery_plan(data: GPLType) -> Optional[PlaylistRecovery]:
    version = get_version(data)
    if not version:
        # nothing we can do about this
        return None

    steps = []

    if version <= GPLVersion.v1:
        steps.append(V1toV2())
    if version <= GPLVersion.v2:
        steps.append(V2toV3())

    if not steps:
        return None

    return PlaylistRecovery(steps, data)
