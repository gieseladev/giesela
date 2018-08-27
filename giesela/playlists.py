import bisect
import json
import logging
import uuid
from collections import defaultdict, deque
from pathlib import Path
from shelve import DbfilenameShelf, Shelf
from typing import Any, Callable, Container, Deque, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple, Type, TypeVar, Union

from discord import TextChannel, User

from . import entry as entry_module, mosaic, utils
from .bot import Giesela
from .entry import BaseEntry, Entry
from .lib.api import imgur
from .lib.ui import text as text_utils
from .queue import Queue

log = logging.getLogger(__name__)

_DEFAULT = object()

UUIDType = Union[str, int, uuid.UUID]
KT = TypeVar("KT")


def filter_dict(d: Mapping[KT, Any], keys: Container[KT]) -> dict:
    return {key: value for key, value in d.items() if key in keys}


def normalise_entry_data(entry: Dict[str, Any]) -> Dict[str, Any]:
    if entry.get("type", None) in ("VGMEntry", "DiscogsEntry", "SpotifyEntry"):
        entry["type"] = "GieselaEntry"
    if "expected_filename" in entry:
        entry["filename"] = entry["expected_filename"]

    return filter_dict(entry, ENTRY_SLOTS)


def get_uuid(gpl_id: UUIDType) -> uuid.UUID:
    if isinstance(gpl_id, str):
        return uuid.UUID(hex=gpl_id)
    elif isinstance(gpl_id, int):
        return uuid.UUID(int=gpl_id)
    elif isinstance(gpl_id, uuid.UUID):
        return gpl_id
    else:
        raise TypeError("Can't resolve uuid")


ENTRY_SLOTS = ("version", "type", "filename",  # meta
               "video_id", "url", "title", "duration", "thumbnail",  # basic
               "song_title", "artist", "artist_image", "cover", "album")  # complex


class PlaylistEntry:
    playlist: "Playlist"
    # TODO marking as broken

    _entry: dict

    url: str

    def __init__(self, entry: Union[BaseEntry, dict]):
        self.playlist = None

        if isinstance(entry, BaseEntry):
            entry = entry.to_dict()

        entry = normalise_entry_data(entry)

        self._entry = entry

    def __repr__(self) -> str:
        return f"Entry {self.title} of {self.playlist}"

    def __hash__(self) -> int:
        return hash(self.url)

    def __setstate__(self, state: dict):
        self._entry = state

    def __getstate__(self) -> dict:
        return self._entry

    def __reduce__(self) -> Tuple[Callable, tuple, dict]:
        return object.__new__, (PlaylistEntry,), self.__getstate__()

    def __getattr__(self, item: str) -> Optional[Any]:
        return self._entry.get(item)

    def __eq__(self, other) -> bool:
        if isinstance(other, (PlaylistEntry, BaseEntry)):
            return self.url == other.url
        return NotImplemented

    def __lt__(self, other) -> bool:
        if isinstance(other, (PlaylistEntry, BaseEntry)):
            return self.sort_attr.__lt__(other.sort_attr)
        return NotImplemented

    def __le__(self, other) -> bool:
        if isinstance(other, (PlaylistEntry, BaseEntry)):
            return self.sort_attr.__le__(other.sort_attr)
        return NotImplemented

    def __gt__(self, other) -> bool:
        if isinstance(other, (PlaylistEntry, BaseEntry)):
            return self.sort_attr.__gt__(other.sort_attr)
        return NotImplemented

    def __ge__(self, other) -> bool:
        if isinstance(other, (PlaylistEntry, BaseEntry)):
            return self.sort_attr.__ge__(other.sort_attr)
        return NotImplemented

    @property
    def __class__(self) -> BaseEntry:
        if self.type:
            cls = getattr(entry_module, self.type, None)
        else:
            cls = None
        return cls or PlaylistEntry

    @property
    def title(self) -> str:
        if self.artist and self.song_title:
            return f"{self.artist} - {self.song_title}"
        return self._entry["title"]

    @property
    def sort_attr(self) -> str:
        return self.title

    @classmethod
    def from_gpl(cls, data: dict) -> "PlaylistEntry":
        return cls(data)

    def to_gpl(self) -> dict:
        return self._entry

    def edit(self, **changes):
        changes = filter_dict(changes, ENTRY_SLOTS)
        self._entry.update(changes)
        if self.playlist:
            self.playlist.save()

    def copy(self) -> "PlaylistEntry":
        data = self.to_gpl().copy()
        return self.from_gpl(data)

    def get_entry(self, *, author: User, channel: TextChannel, **meta) -> BaseEntry:
        entry = Entry.from_dict(self._entry)
        meta.update(author=author, channel=channel, playlist=self.playlist, playlist_entry=self)
        entry.meta.update(meta)
        return entry


PLAYLIST_SLOTS = ("gpl_id", "name", "description", "author_id", "cover", "entries", "editor_ids")
# This makes backward-compatible saves somewhat possible
PLAYLIST_SLOT_DEFAULTS = {"description": None, "cover": None, "entries": [], "editor_ids": []}


class Playlist:
    manager: "PlaylistManager"

    gpl_id: uuid.UUID
    name: str
    description: Optional[str]
    author_id: int
    cover: Optional[str]
    entries: List[PlaylistEntry]
    editor_ids: Set[int]

    _author: User
    _editors: List[User]

    def __init__(self, **kwargs):
        self.manager = None

        self.gpl_id = kwargs.pop("gpl_id", uuid.uuid4())
        self.name = kwargs.pop("name")
        self.description = kwargs.pop("description", None)
        self.cover = kwargs.pop("cover", None)
        self.entries = sorted(kwargs.pop("entries"))
        self.editor_ids = kwargs.pop("editors", [])

        author = kwargs.pop("author", None)
        if author:
            if isinstance(author, dict):
                self.author_id = author["id"]
            else:
                self.author_id = author.id
        else:
            self.author_id = kwargs.pop("author_id")

        self.init()

    def __repr__(self) -> str:
        return f"Playlist {self.gpl_id}"

    def __str__(self) -> str:
        return f"Playlist \"{self.name}\""

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, entry: Union[BaseEntry, PlaylistEntry]) -> bool:
        return self.has(entry)

    def __iter__(self) -> Iterator[PlaylistEntry]:
        return iter(self.entries)

    def __reversed__(self) -> Iterator[PlaylistEntry]:
        return reversed(self.entries)

    def __getstate__(self) -> dict:
        return {key: getattr(self, key) for key in PLAYLIST_SLOTS}

    def __setstate__(self, state: dict):
        for key in PLAYLIST_SLOTS:
            value = state[key] if key in state else PLAYLIST_SLOT_DEFAULTS[key]
            setattr(self, key, value)
        self.init()

    def __enter__(self) -> "Playlist":
        if hasattr(self, "__opened__"):
            raise ValueError("Playlist is already open!")

        setattr(self, "__opened__", True)
        return self

    def __exit__(self, exc_type: Optional[Type[Exception]], exc: Optional[Exception], exc_tb: Optional):
        delattr(self, "__opened__")
        self.save()
        if exc:
            raise exc

    @property
    def duration(self) -> int:
        return sum(entry.duration for entry in self.entries)

    @property
    def author(self) -> User:
        if not getattr(self, "_author", False):
            self._author = self.manager.bot.get_user(self.author_id)
        return self._author

    @property
    def editors(self) -> List[User]:
        if not getattr(self, "_editors", False):
            self._editors = list(filter(None, map(self.manager.bot.get_user, self.editor_ids)))
        return self._editors

    @author.setter
    def author(self, author: User):
        self.author_id = author.id
        self._author = author

    def init(self):
        self.entries.sort()
        for entry in self.entries:
            entry.playlist = self

    @classmethod
    def from_gpl(cls, manager: "PlaylistManager", data: dict) -> "Playlist":
        data = {key: value for key, value in data.items() if key in PLAYLIST_SLOTS}

        gpl_id = data.pop("gpl_id", None)
        if gpl_id:
            data["gpl_id"] = get_uuid(gpl_id)

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

    def add(self, entry: Union[BaseEntry, PlaylistEntry]):
        if not isinstance(entry, PlaylistEntry):
            entry = PlaylistEntry(entry)
        if entry in self:
            raise ValueError(f"{entry} is already in {self}")

        entry.playlist = self
        bisect.insort_left(self.entries, entry)
        self.save()

    def remove(self, entry: Union[BaseEntry, PlaylistEntry]):
        for _entry in reversed(self):
            if _entry.url == entry.url:
                self.entries.remove(_entry)
                break
        else:
            raise KeyError(f"{entry} isn't in {self}")
        self.save()

    def edit_entry(self, entry: Union[BaseEntry, PlaylistEntry], changes: Dict[str, Any]):
        for _entry in self:
            if _entry == entry:
                break
        else:
            raise KeyError(f"{entry} isn't in {self}")

        _entry.edit(**changes)

    def has(self, entry: Union[BaseEntry, PlaylistEntry]) -> bool:
        for _entry in self:
            if _entry.url == entry.url:
                return True
        return False

    def rename(self, name: str):
        self.name = name
        self.save()

    def set_description(self, description: str):
        self.description = description
        self.save()

    async def set_cover(self, cover: str = None) -> bool:
        if cover:
            cover = await imgur.upload_playlist_cover(self.name, cover)
        else:
            cover = await self.generate_cover()

        if not cover:
            return False

        self.cover = cover
        self.save()
        return True

    def save(self):
        if hasattr(self, "__opened__"):
            log.debug("not saving playlist because it's open")
            return
        self.manager.save_playlist(self)
        log.debug(f"saved playlist {self}")

    def edit(self) -> "EditPlaylistProxy":
        return EditPlaylistProxy(self)

    def delete(self):
        self.manager.remove_playlist(self)
        log.debug(f"deleted playlist {self}")

    def transfer(self, new_author: User):
        self.author = new_author
        self.save()

    def add_editor(self, user: User):
        if self.is_editor(user):
            return
        self.editor_ids.add(user.id)
        if hasattr(self, "_editors"):
            self._editors.append(user)
        self.save()

    def remove_editor(self, user: User):
        if not self.is_editor(user):
            return
        self.editor_ids.remove(user.id)
        if hasattr(self, "_editors"):
            self._editors.remove(user)
        self.save()

    def is_author(self, user: User) -> bool:
        return user.id == self.author_id

    def is_editor(self, user: User) -> bool:
        return user.id in self.editor_ids

    def can_edit(self, user: User) -> bool:
        return self.is_author(user) or self.is_editor(user)

    async def play(self, queue: Queue, **meta):
        await queue.load_playlist(self, **meta)

    async def generate_cover(self) -> Optional[str]:
        return await mosaic.generate_playlist_cover(self)


class EditChange:
    ADDED = 1
    REMOVED = 2
    EDITED = 3

    ALL_TYPES = (ADDED, REMOVED, EDITED)

    change_type: int
    success: Optional[bool]
    entry: PlaylistEntry
    changes: Optional[Dict[str, Any]]

    def __init__(self, change_type: int, *, entry: PlaylistEntry, changes: Dict[str, Any] = None):
        if change_type not in self.ALL_TYPES:
            raise ValueError(f"Unknown change type {change_type}")

        self.success = None
        self.entry = entry
        self.changes = changes
        self.change_type = change_type

    def __repr__(self) -> str:
        return f"EditChange(EditChange.{self.name(self.change_type).upper()}, {self.entry})"

    def __str__(self) -> str:
        action = self.name(self.change_type)
        success = "❌" if self.success is False else ""

        return f"{success}{action} \"{self.entry.title}\""

    @property
    def symbol(self) -> str:
        return self.get_symbol(self.change_type)

    @classmethod
    def added(cls, entry: PlaylistEntry):
        return cls(EditChange.ADDED, entry=entry)

    @classmethod
    def removed(cls, entry: PlaylistEntry):
        return cls(EditChange.REMOVED, entry=entry)

    @classmethod
    def edited(cls, entry: PlaylistEntry, changes: Dict[str, Any]):
        return cls(EditChange.EDITED, entry=entry, changes=changes)

    @classmethod
    def name(cls, change_type: int) -> str:
        if change_type == cls.ADDED:
            action = "added"
        elif change_type == cls.REMOVED:
            action = "removed"
        elif change_type == cls.EDITED:
            action = "edited"
        else:
            action = "unknown"
        return action

    @classmethod
    def get_symbol(cls, change_type: int) -> str:
        if change_type == EditChange.ADDED:
            return "+"
        elif change_type == EditChange.REMOVED:
            return "-"
        elif change_type == EditChange.EDITED:
            return "\✏"

    def apply(self, playlist: Playlist) -> bool:
        try:
            if self.change_type == self.ADDED:
                playlist.add(self.entry)
            elif self.change_type == self.REMOVED:
                playlist.remove(self.entry)
            elif self.change_type == self.EDITED:
                playlist.edit_entry(self.entry, self.changes)
        except (KeyError, ValueError):
            self.success = False
            return False
        else:
            self.success = True
            return True


class EditPlaylistProxy:
    _playlist: Playlist
    _entries: List[PlaylistEntry]
    _entry_map: Dict[PlaylistEntry, EditChange]

    _changes: Deque[EditChange]

    def __init__(self, playlist: Playlist):
        self._playlist = playlist
        self._entries = playlist.entries.copy()
        self._entry_map = {}

        self._changes = deque()
        self._undo_stack = deque(maxlen=25)

    def __str__(self) -> str:
        return ", ".join(self.simple_changelog())

    def __getattr__(self, item):
        return getattr(self._playlist, item)

    @property
    def entries(self) -> List[PlaylistEntry]:
        return self._entries

    @property
    def entry_map(self) -> Dict[PlaylistEntry, EditChange]:
        return self._entry_map

    def rebuild_entries(self):
        entries = self._playlist.entries.copy()
        self._entry_map.clear()

        for change in self._changes:
            self._entry_map[change.entry] = change
            if change.change_type == change.ADDED:
                bisect.insort_left(self._entries, change.entry)
            elif change.change_type == change.EDITED:
                index = entries.index(change.entry)
                entry = change.entry.copy()
                entry.edit(**change.changes)
                entries[index] = entry

        self._entries = entries

    def undo(self) -> Optional[EditChange]:
        if self._changes:
            change = self._changes.pop()
            self._undo_stack.append(change)
            self.rebuild_entries()
            return change

    def redo(self) -> Optional[EditChange]:
        if self._undo_stack:
            change = self._undo_stack.pop()
            self._changes.append(change)
            self.rebuild_entries()
            return change

    def get_change(self, entry: PlaylistEntry) -> Optional[EditChange]:
        return self._entry_map.get(entry)

    def find_change(self, change_type: int, entry) -> EditChange:
        for change in self._changes:
            if change.change_type == change_type and change.entry == entry:
                return change
        raise KeyError(f"Couldn't find that change: {EditChange.name(change_type)} {entry}")

    def index_of(self, entry: PlaylistEntry) -> int:
        index = bisect.bisect_left(self._entries, entry)
        if index == len(self._entries) or self._entries[index] != entry:
            raise ValueError(f"{entry} doesn't seem to be in {self._playlist}")

        return index

    def search_entry(self, target: str, *, threshold: float = .2) -> Optional[PlaylistEntry]:
        _entry = None
        _similarity = 0
        for entry in self._entries:
            similarity = utils.similarity(target, (entry.title, entry.artist, entry.song_title), lower=True)
            if similarity > _similarity:
                _entry = entry
                _similarity = similarity

        if _similarity <= threshold:
            return None

        return _entry

    def add_entry(self, entry: Union[BaseEntry, PlaylistEntry]) -> PlaylistEntry:
        if not isinstance(entry, PlaylistEntry):
            entry = PlaylistEntry(entry)

        if entry in self._entries:
            raise KeyError(f"{entry} already in {self._playlist}")

        self._undo_stack.clear()
        try:
            change = self.find_change(EditChange.REMOVED, entry)
        except KeyError:
            change = EditChange.added(entry)
            self._changes.append(change)
            self._entry_map[entry] = change
        else:
            self._changes.remove(change)
            self._entry_map.pop(entry)

        bisect.insort_left(self._entries, entry)
        return entry

    def remove_entry(self, entry: Union[int, PlaylistEntry]) -> PlaylistEntry:
        if isinstance(entry, int):
            entry = self._entries[entry]

        if entry not in self._entries:
            raise KeyError(f"{entry} not in {self._playlist}")

        self._undo_stack.clear()
        try:
            change = self.find_change(EditChange.ADDED, entry)
        except KeyError:
            change = EditChange.removed(entry)
            self._changes.append(change)
            self._entry_map[entry] = change
        else:
            self._changes.remove(change)
            self._entry_map.pop(entry)

        return entry

    def edit_entry(self, entry: [int, PlaylistEntry], changes: Dict[str, Any]) -> PlaylistEntry:
        if isinstance(entry, int):
            index = entry
            entry = self._entries[entry]
        else:
            index = bisect.bisect_left(self._entries, entry)
            if index == len(self._entries) or self._entries[index] != entry:
                raise ValueError(f"{entry} doesn't seem to be in {self._playlist}")

        self._undo_stack.clear()
        change = EditChange.edited(entry, changes)
        self._changes.append(change)
        self._entry_map[entry] = change

        edited_entry = entry.copy()
        edited_entry.edit(**changes)
        self._entries[index] = edited_entry

        return edited_entry

    def apply(self):
        with self._playlist as playlist:
            for change in self._changes:
                change.apply(playlist)

    def simple_changelog(self) -> List[str]:
        counts = defaultdict()
        for change in self._changes:
            if change.success is not False:
                counts[change.change_type] += 1
        keys = sorted(counts.keys())

        logs = []
        for key in keys:
            action = EditChange.name(key)
            count = counts[key]
            inflected_entry = "entry" if count == 0 else "entries"
            logs.append(f"{action} {count} {inflected_entry}")
        return logs

    def get_changelog(self, limit: int = None) -> List[str]:
        changes = deque(self._changes, maxlen=limit)
        return list(map(str, changes))

    def prepare_changelog(self, width: int = 70, limit: int = None) -> str:
        changes = deque(self._changes, maxlen=limit)
        changelog = []
        for change in changes:
            symbol = change.symbol
            text = f" {symbol} \"{change.entry.title}\""
            changelog.append(text_utils.shorten(text, width, "...\""))

        return "\n".join(changelog)


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

        log.debug(f"playlist manager ready ({len(self)} loaded)")

    def __len__(self) -> int:
        return len(self._playlists)

    def __iter__(self) -> Iterable[Playlist]:
        return iter(self.playlists)

    @property
    def playlists(self) -> Iterable[Playlist]:
        return self._playlists.values()

    @classmethod
    def load(cls, bot: Giesela, storage_location: Union[str, Path]) -> "PlaylistManager":
        if isinstance(storage_location, str):
            storage_location = Path(storage_location)
        storage_location.parent.mkdir(exist_ok=True)
        storage_location = storage_location.absolute()
        shelf = DbfilenameShelf(str(storage_location))
        inst = cls(bot, shelf)
        inst.init()
        return inst

    def init(self):
        pass

    def close(self):
        self.storage.close()

    def import_from_gpl(self, playlist: Union[dict, str], *, author: User = None) -> Optional[Playlist]:
        if isinstance(playlist, str):
            try:
                playlist = json.loads(playlist)
            except json.JSONDecodeError:
                return

        try:
            playlist = Playlist.from_gpl(self, playlist)
        except Exception as e:
            log.warning("Couldn't import playlist", exc_info=e)
            return

        playlist.author = author

        self.add_playlist(playlist)
        return playlist

    def add_playlist(self, playlist: Playlist):
        if playlist.gpl_id in self._playlists:
            raise KeyError("Playlist with this id already exists, remove it first!")
        playlist.manager = self
        playlist.save()

    def remove_playlist(self, playlist: Playlist):
        if playlist.gpl_id not in self._playlists:
            raise ValueError("This playlist doesn't belong to this manager...")
        playlist.manager = None
        del self._playlists[playlist.gpl_id]
        del self.storage[playlist.gpl_id.hex]

    def save_playlist(self, playlist: Playlist):
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
            similarity = utils.similarity(name, (playlist.name, playlist.description), lower=True)
            if similarity > _similarity:
                _playlist = playlist
                _similarity = similarity

        if _similarity <= threshold:
            return None

        return _playlist
