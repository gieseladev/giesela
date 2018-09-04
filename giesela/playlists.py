import bisect
import json
import logging
import uuid
from collections import defaultdict, deque
from pathlib import Path
from shelve import DbfilenameShelf, Shelf
from typing import Any, Container, Deque, Dict, Iterable, Iterator, List, Mapping, Optional, TYPE_CHECKING, Tuple, Type, TypeVar, Union

from discord import User

from giesela.lib import mosaic
from giesela.ui import text as text_utils
from . import utils
from .bot import Giesela
from .entry import BaseEntry, EntryWrapper, PlayableEntry, load_entry_from_dict
from .lib.api import imgur

if TYPE_CHECKING:
    from .queue import EntryQueue

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

    return entry


def get_uuid(gpl_id: UUIDType) -> uuid.UUID:
    if isinstance(gpl_id, str):
        return uuid.UUID(hex=gpl_id)
    elif isinstance(gpl_id, int):
        return uuid.UUID(int=gpl_id)
    elif isinstance(gpl_id, uuid.UUID):
        return gpl_id
    else:
        raise TypeError("Can't resolve uuid")


def search_entries(entries: Iterable["PlaylistEntry"], target: str, *, threshold: float = .8) -> Iterator[Tuple["PlaylistEntry", float]]:
    for pl_entry in entries:
        entry = pl_entry.entry
        if entry.uri == target or entry.track == target:
            yield pl_entry, 1

        if isinstance(entry, BaseEntry):
            comp = (str(entry), entry.title, entry.artist)
        else:
            comp = str(entry)

        similarity = utils.similarity(target, comp, lower=True)
        if similarity > threshold:
            yield pl_entry, similarity


def search_entry(entries, target: str, *, threshold: float = .8) -> Optional["PlaylistEntry"]:
    _entry = None
    _similarity = 0
    for pl_entry, similarity in search_entries(entries, target, threshold=threshold):
        if similarity > _similarity:
            _entry = pl_entry
            _similarity = similarity

    if _similarity <= threshold:
        return None

    return _entry


class LoadedPlaylistEntry(EntryWrapper):
    def __init__(self, *, playlist: "Playlist", playlist_entry: "PlaylistEntry", **kwargs):
        super().__init__(**kwargs)
        self.playlist = playlist
        self.playlist_entry = playlist_entry

    @classmethod
    def create(cls, playlist_entry: "PlaylistEntry") -> "LoadedPlaylistEntry":
        return cls(playlist_entry=playlist_entry, playlist=playlist_entry.playlist, entry=playlist_entry.entry)


class PlaylistEntry:
    playlist: "Playlist" = None

    def __init__(self, entry: PlayableEntry):
        self._entry = entry

    def __repr__(self) -> str:
        playlist = repr(self.playlist)
        me = repr(self._entry)
        return f"{me} - {playlist}"

    def __getstate__(self):
        return dict(entry=self._entry)

    def __setstate__(self, state: dict):
        self._entry = state["entry"]

    def __hash__(self) -> int:
        return hash(self._entry)

    def __eq__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self._entry == other._entry
        return NotImplemented

    def __lt__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self._entry.__lt__(other._entry)
        return NotImplemented

    def __le__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self._entry.__le__(other._entry)
        return NotImplemented

    def __gt__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self._entry.__gt__(other._entry)
        return NotImplemented

    def __ge__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self._entry.__ge__(other._entry)
        return NotImplemented

    @property
    def entry(self):
        return self._entry

    @property
    def sort_attr(self):
        return self._entry.sort_attr

    @classmethod
    def from_gpl(cls, data: dict) -> "PlaylistEntry":
        data["entry"] = load_entry_from_dict(data.pop("entry"))
        return cls(**data)

    def to_gpl(self):
        entry = self._entry.to_dict()
        # TODO add meta?
        return dict(entry=entry)

    def replace(self, entry: PlayableEntry):
        before_sort_attr = self.sort_attr
        self._entry = entry
        self.save(reorder=self.sort_attr != before_sort_attr)

    def save(self, *, reorder: bool = False):
        if self.playlist:
            if reorder:
                log.debug(f"{self} sort attribute has changed, re-ordering in playlist")
                self.playlist.reorder_entry(self)
            else:
                self.playlist.save()
        else:
            log.warning("Can't save {self}, no playlist...")

    def copy(self) -> "PlaylistEntry":
        data = self.to_gpl().copy()
        return self.from_gpl(data)

    def get_wrapper(self) -> LoadedPlaylistEntry:
        if not self.playlist:
            raise ValueError("This entry doesn't belong to a playlist")
        return LoadedPlaylistEntry.create(self)


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
    editor_ids: List[int]

    _author: User
    _editors: List[User]

    def __init__(self, **kwargs):
        self.manager = None

        self.gpl_id = kwargs.pop("gpl_id", uuid.uuid4())
        self.name = kwargs.pop("name")
        self.description = kwargs.pop("description", None)
        self.cover = kwargs.pop("cover", None)
        self.entries = kwargs.pop("entries", [])
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

    def __contains__(self, entry: PlaylistEntry) -> bool:
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
    def total_duration(self) -> int:
        return sum(entry.entry.duration for entry in self.entries)

    @property
    def author(self) -> User:
        if not getattr(self, "_author", False):
            self._author = self.manager.bot.get_user(self.author_id)
        return self._author

    @author.setter
    def author(self, author: User):
        self.author_id = author.id
        self._author = author

    @property
    def editors(self) -> List[User]:
        if not getattr(self, "_editors", False):
            self._editors = list(filter(None, map(self.manager.bot.get_user, self.editor_ids)))
        return self._editors

    def init(self):
        # TODO remove after some time
        # making sure that it's a list
        self.editor_ids = list(self.editor_ids)

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

    def add(self, entry: Union[PlayableEntry, PlaylistEntry]) -> PlaylistEntry:
        if not isinstance(entry, PlaylistEntry):
            entry = PlaylistEntry(entry)
        if entry in self:
            raise ValueError(f"{entry} is already in {self}")

        entry.playlist = self
        bisect.insort_left(self.entries, entry)
        self.save()
        return entry

    def remove(self, entry: PlaylistEntry):
        if entry not in self:
            raise KeyError(f"{entry} isn't in {self}")
        self.entries.remove(entry)
        self.save()

    def reorder_entry(self, entry: PlaylistEntry):
        if entry not in self:
            raise KeyError(f"{entry} isn't in {self}")

        index = self.index_of(entry)
        _entry = self.entries.pop(index)
        bisect.insort_left(self.entries, _entry)
        self.save()

    def has(self, entry: PlaylistEntry) -> bool:
        return entry in self.entries

    def index_of(self, entry: PlaylistEntry) -> int:
        return self.entries.index(entry)

    def search_entry(self, target: str, *, threshold: float = .8) -> Optional[PlaylistEntry]:
        return search_entry(self.entries, target, threshold=threshold)

    def search_all_entries(self, target: str, *, threshold: float = .8) -> Iterator[Tuple[PlaylistEntry, float]]:
        return search_entries(self.entries, target, threshold=threshold)

    def rename(self, name: str):
        self.name = name
        self.save()

    def set_description(self, description: str):
        self.description = description
        self.save()

    async def set_cover(self, cover: str = None, *, no_upload: bool = False) -> bool:
        if cover:
            if not no_upload:
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
        log.debug(f"saved {self}")

    def edit(self) -> "EditPlaylistProxy":
        return EditPlaylistProxy(self)

    def delete(self):
        self.manager.remove_playlist(self)
        log.debug(f"deleted playlist {self}")

    def transfer(self, new_author: User):
        # noinspection PyAttributeOutsideInit
        self.author = new_author
        self.save()

    def add_editor(self, user: User):
        if self.is_editor(user):
            return
        self.editor_ids.append(user.id)
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

    async def play(self, queue: "EntryQueue", requester: User, front: bool = False):
        entries = [pl_entry.get_wrapper() for pl_entry in self]
        queue.add_entries(entries, requester, front=front)

    async def generate_cover(self) -> Optional[str]:
        return await mosaic.generate_playlist_cover(self)


class EditChange:
    ADDED = 1
    REMOVED = 2
    EDITED = 3

    ALL_TYPES = (ADDED, REMOVED, EDITED)

    success: Optional[bool]

    def __init__(self, change_type: int, *, pl_entry: PlaylistEntry, new_entry: Optional[PlayableEntry] = None):
        if change_type not in self.ALL_TYPES:
            raise ValueError(f"Unknown change type {change_type}")

        self.success = None
        self.pl_entry = pl_entry
        self.new_entry = new_entry
        self.change_type = change_type

    def __repr__(self) -> str:
        return f"EditChange(EditChange.{self.name(self.change_type).upper()}, {self.pl_entry})"

    def __str__(self) -> str:
        action = self.name(self.change_type)
        success = "❌" if self.success is False else ""

        return f"{success}{action} \"{self.pl_entry.entry}\""

    @property
    def symbol(self) -> str:
        return self.get_symbol(self.change_type)

    @classmethod
    def added(cls, pl_entry: PlaylistEntry):
        return cls(EditChange.ADDED, pl_entry=pl_entry)

    @classmethod
    def removed(cls, pl_entry: PlaylistEntry):
        return cls(EditChange.REMOVED, pl_entry=pl_entry)

    @classmethod
    def edited(cls, pl_entry: PlaylistEntry, new_entry: PlayableEntry):
        return cls(EditChange.EDITED, pl_entry=pl_entry, new_entry=new_entry)

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
                playlist.add(self.pl_entry)
            elif self.change_type == self.REMOVED:
                playlist.remove(self.pl_entry)
            elif self.change_type == self.EDITED:
                self.pl_entry.replace(self.new_entry)
        except (KeyError, ValueError):
            self.success = False
            return False
        else:
            self.success = True
            return True


class EditPlaylistProxy:
    _playlist: Playlist
    _pl_entries: List[PlaylistEntry]
    _entry_map: Dict[PlaylistEntry, EditChange]

    _changes: Deque[EditChange]

    def __init__(self, playlist: Playlist):
        self._playlist = playlist
        self._pl_entries = playlist.entries.copy()
        self._entry_map = {}

        self._changes = deque()
        self._undo_stack = deque(maxlen=25)

    def __str__(self) -> str:
        return ", ".join(self.simple_changelog())

    def __getattr__(self, item):
        return getattr(self._playlist, item)

    @property
    def pl_entries(self) -> List[PlaylistEntry]:
        return self._pl_entries

    @property
    def pl_entry_map(self) -> Dict[PlaylistEntry, EditChange]:
        return self._entry_map

    def rebuild_entries(self):
        pl_entries = self._playlist.entries.copy()
        self._entry_map.clear()

        for change in self._changes:
            self._entry_map[change.pl_entry] = change
            if change.change_type == change.ADDED:
                bisect.insort_left(pl_entries, change.pl_entry)
            elif change.change_type == change.EDITED:
                index = self.index_of(change.pl_entry)
                pl_entries.pop(index)
                entry = change.pl_entry.copy()
                entry.replace(change.new_entry)
                bisect.insort_left(pl_entries, entry)

        self._pl_entries = pl_entries

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

    def find_change(self, change_type: int, pl_entry: PlaylistEntry) -> EditChange:
        for change in self._changes:
            if change.change_type == change_type and change.pl_entry == pl_entry:
                return change
        raise KeyError(f"Couldn't find that change: {EditChange.name(change_type)} {pl_entry}")

    def resort_entry(self, entry: PlaylistEntry):
        index = self.index_of(entry)
        self._pl_entries.pop(index)
        bisect.insort_left(self._pl_entries, entry)

    def index_of(self, entry: PlaylistEntry) -> int:
        return self._pl_entries.index(entry)

    def search_entry(self, target: str, *, threshold: float = .2) -> Optional[PlaylistEntry]:
        return search_entry(self._pl_entries, target, threshold=threshold)

    def add_entry(self, entry: PlayableEntry) -> PlaylistEntry:
        pl_entry = PlaylistEntry(entry)

        self._undo_stack.clear()
        try:
            change = self.find_change(EditChange.REMOVED, pl_entry)
        except KeyError:
            change = EditChange.added(pl_entry)
            self._changes.append(change)
            self._entry_map[pl_entry] = change
        else:
            self._changes.remove(change)
            self._entry_map.pop(pl_entry)

        bisect.insort_left(self._pl_entries, pl_entry)
        return pl_entry

    def remove_entry(self, pl_entry: Union[int, PlaylistEntry]) -> PlaylistEntry:
        if isinstance(pl_entry, int):
            pl_entry = self._pl_entries[pl_entry]

        if pl_entry not in self._pl_entries:
            raise KeyError(f"{pl_entry} not in {self._playlist}")

        self._undo_stack.clear()
        try:
            change = self.find_change(EditChange.ADDED, pl_entry)
        except KeyError:
            change = EditChange.removed(pl_entry)
            self._changes.append(change)
            self._entry_map[pl_entry] = change
        else:
            self._changes.remove(change)
            self._entry_map.pop(pl_entry)

        return pl_entry

    def edit_entry(self, pl_entry: [int, PlaylistEntry], new_entry: PlayableEntry) -> PlaylistEntry:
        if isinstance(pl_entry, int):
            index = pl_entry
            pl_entry = self._pl_entries[pl_entry]
        else:
            index = self.index_of(pl_entry)

        self._undo_stack.clear()
        change = EditChange.edited(pl_entry, new_entry)
        self._changes.append(change)
        self._entry_map[pl_entry] = change

        edited_entry = pl_entry.copy()
        edited_entry.replace(new_entry)
        self._pl_entries[index] = edited_entry
        self.resort_entry(edited_entry)

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
            text = f" {symbol} \"{change.pl_entry.entry}\""
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
            try:
                playlist = self.storage[gpl_id]
            except Exception:
                log.exception(f"Couldn't load playlist {gpl_id}")
            else:
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
        return inst

    def close(self):
        log.info("closing playlists")
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
        self.storage.sync()

    def save_playlist(self, playlist: Playlist):
        self._playlists[playlist.gpl_id] = playlist
        self.storage[playlist.gpl_id.hex] = playlist
        self.storage.sync()

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
