import json
import logging
import uuid
from pathlib import Path
from shelve import DbfilenameShelf, Shelf
from typing import Any, Dict, Iterable, List, Optional, Union

from discord import User

from . import utils
from .bot import Giesela
from .entry import BaseEntry, Entry
from .queue import Queue

log = logging.getLogger(__name__)

_DEFAULT = object()


class PlaylistEntry:
    playlist: "Playlist"

    _entry: dict

    def __init__(self, entry: Union[BaseEntry, dict]):
        self.playlist = None

        if isinstance(entry, BaseEntry):
            entry = entry.to_dict()
        self._entry = entry

    def __repr__(self) -> str:
        return f"Entry {self._entry['title']} of {self.playlist}"

    def __getstate__(self) -> dict:
        return self._entry

    def __setstate__(self, state: dict):
        self._entry = state

    def __getattr__(self, item: str) -> Any:
        return self._entry[item]

    @classmethod
    def from_gpl(cls, data: dict) -> "PlaylistEntry":
        return cls(data)

    def to_gpl(self) -> dict:
        return self._entry

    def entry(self, queue: Queue) -> BaseEntry:
        return Entry.from_dict(queue, self._entry)


PLAYLIST_SLOTS = ("gpl_id", "name", "description", "author_id", "cover", "entries")


class Playlist:
    manager: "PlaylistManager"

    gpl_id: uuid.UUID
    name: str
    description: Optional[str]
    author_id: int
    cover: Optional[str]
    entries: List[PlaylistEntry]

    def __init__(self, **kwargs):
        self.manager = None

        self.gpl_id = kwargs.pop("gpl_id", uuid.uuid4())
        self.name = kwargs.pop("name")
        self.description = kwargs.pop("description", None)
        author = kwargs.pop("author", None)
        if author:
            self.author_id = self.author.id
        else:
            self.author_id = kwargs.pop("author_id")
        self.cover = kwargs.pop("cover", None)
        self.entries = kwargs.pop("entries")
        for entry in self.entries:
            entry.playlist = self

    def __repr__(self) -> str:
        return f"Playlist {self.gpl_id}"

    def __str__(self) -> str:
        return f"Playlist \"{self.name}\""

    def __len__(self) -> int:
        return len(self.entries)

    def __getstate__(self) -> dict:
        return {key: getattr(self, key) for key in PLAYLIST_SLOTS}

    def __setstate__(self, state: dict):
        for key in PLAYLIST_SLOTS:
            setattr(self, key, state[key])

    @property
    def duration(self) -> int:
        return sum(entry.duration for entry in self.entries)

    @property
    def author(self) -> User:
        if not getattr(self, "_author", False):
            self._author = self.manager.bot.get_user(self.author_id)
        return self._author

    def init(self):
        pass

    @classmethod
    def from_gpl(cls, manager: "PlaylistManager", data: dict) -> "Playlist":
        data = {key: value for key, value in data.items() if key in PLAYLIST_SLOTS}
        _entries = data.pop("entries")
        entries = []
        for _entry in _entries:
            entry = PlaylistEntry.from_gpl(_entry)
            entries.append(entry)
        inst = cls(entries=entries, **data)
        inst.manager = manager
        inst.init()
        return inst

    def to_gpl(self) -> dict:
        data = self.__getstate__()
        data["gpl_id"] = data.pop("gpl_id").hex
        data["entries"] = [entry.to_gpl() for entry in data.pop("entries")]
        return data

    def save(self):
        self.manager.save_playlist(self)


UUIDType = Union[str, int, uuid.UUID]


def get_uuid(gpl_id: UUIDType) -> uuid.UUID:
    if isinstance(gpl_id, str):
        return uuid.UUID(hex=gpl_id)
    elif isinstance(gpl_id, int):
        return uuid.UUID(int=gpl_id)
    elif isinstance(gpl_id, uuid.UUID):
        return gpl_id
    else:
        raise TypeError("Can't resolve uuid")


class PlaylistManager:
    bot: Giesela
    storage: Shelf
    _playlists: Dict[uuid.UUID, Playlist]

    def __init__(self, bot: Giesela, storage: Shelf):
        self.bot = bot
        self.storage = storage

        self._playlists = {}
        for gpl_id in self.storage:
            playlist = self.storage[gpl_id]
            playlist.manager = self
            self._playlists[playlist.gpl_id] = playlist

    def __len__(self) -> int:
        return len(self._playlists)

    def __iter__(self) -> Iterable[Playlist]:
        return iter(self.playlists)

    @property
    def playlists(self) -> Iterable[Playlist]:
        return self._playlists.values()

    @classmethod
    def load(cls, bot: Giesela, storage_location: Union[str, Path]) -> "PlaylistManager":
        if isinstance(storage_location, Path):
            storage_location = storage_location.absolute()
        shelf = DbfilenameShelf(storage_location)
        inst = cls(bot, shelf)
        inst.init()
        return inst

    def init(self):
        for playlist in self.playlists:
            playlist.init()
        log.debug(f"playlist manager ready ({len(self)} loaded)")

    def import_from_gpl(self, playlist: Union[dict, str]) -> Optional[Playlist]:
        if isinstance(playlist, str):
            try:
                playlist = json.loads(playlist)
            except json.JSONDecodeError:
                return None

        playlist = Playlist.from_gpl(self, playlist)
        self.add_playlist(playlist)
        return playlist

    def add_playlist(self, playlist: Playlist):
        if playlist.gpl_id in self._playlists:
            raise ValueError("Playlist with this id already exists, remove it first!")
        playlist.manager = self
        playlist.save()

    def save_playlist(self, playlist: Playlist):
        if playlist.gpl_id in self._playlists:
            self._playlists[playlist.gpl_id] = playlist
        self.storage[playlist.gpl_id.hex] = playlist

    def get_playlist(self, gpl_id: UUIDType, default: Any = _DEFAULT) -> Optional[Playlist]:
        try:
            gpl_id = get_uuid(gpl_id)
            return self._playlists[gpl_id]
        except (TypeError, KeyError):
            if default is _DEFAULT:
                raise
            else:
                return default

    def find_playlist(self, name: str, threshold: float = .2) -> Optional[Playlist]:
        _playlist = None
        _similarity = 0
        for playlist in self:
            similarity = utils.similarity(name, (playlist.name, playlist.description))
            if similarity > _similarity:
                _playlist = playlist
                _similarity = similarity

        if _similarity <= threshold:
            return None

        return _playlist
