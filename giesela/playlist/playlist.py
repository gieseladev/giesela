import bisect
import logging
import random
import uuid
from typing import Iterator, List, Optional, TYPE_CHECKING, Tuple, Type

from discord import User

from giesela import PlayableEntry, utils
from giesela.lib import mosaic
from giesela.lib.api import imgur
from . import utils
from .editor import EditPlaylistProxy
from .entry import PlaylistEntry

if TYPE_CHECKING:
    from giesela.queue import EntryQueue
    from .manager import PlaylistManager

__all__ = ["Playlist"]

log = logging.getLogger(__name__)

PLAYLIST_SLOTS = ("gpl_id", "name", "description", "author_id", "cover", "entries", "editor_ids")


class Playlist:
    manager: "PlaylistManager"

    gpl_id: uuid.UUID
    name: str
    author_id: int

    description: Optional[str]
    cover: Optional[str]
    editor_ids: List[int]

    entries: List[PlaylistEntry]

    _author: User
    _editors: List[User]

    def __init__(self, *, gpl_id: utils.UUIDType = None, name: str, author_id: int,
                 description: str = None, cover: str = None, editor_ids: List[int] = None, entries: List[PlaylistEntry] = None):
        self.manager = None
        self._dirty = False

        if gpl_id:
            gpl_id = utils.get_uuid(gpl_id)
        else:
            gpl_id = uuid.uuid4()
            log.info(f"Assigning uuid {gpl_id} to playlist {author_id}-{name}")
            self._dirty = True

        self.gpl_id = gpl_id
        self.name = name
        self.author_id = author_id

        self.description = description
        self.cover = cover
        self.editor_ids = editor_ids or []

        self.entries = entries or []

        self.init()

    def __repr__(self) -> str:
        return f"Playlist {self.gpl_id}"

    def __str__(self) -> str:
        return f"Playlist \"{self.name}\""

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, entry: PlaylistEntry) -> bool:
        return self.has(entry)

    def __iter__(self) -> Iterator[PlaylistEntry]:
        return iter(self.entries)

    def __reversed__(self) -> Iterator[PlaylistEntry]:
        return reversed(self.entries)

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
        # making sure that it's a list
        self.editor_ids = list(self.editor_ids)

        self.entries.sort()
        for entry in self.entries:
            entry.playlist = self

    @classmethod
    def from_gpl(cls, data: dict) -> "Playlist":
        _entries = data.pop("entries")
        entries = []
        for _entry in _entries:
            entry = PlaylistEntry.from_gpl(_entry)
            entries.append(entry)

        inst = cls(entries=entries, **data)
        return inst

    def to_gpl(self) -> dict:
        data = dict(gpl_id=self.gpl_id.hex, name=self.name, description=self.description, author_id=self.author_id, cover=self.cover,
                    editor_ids=self.editor_ids)
        data["entries"] = [entry.to_gpl() for entry in self.entries]
        return {key: value for key, value in data.items() if value}

    def add(self, entry: PlaylistEntry) -> PlaylistEntry:
        if entry in self:
            raise ValueError(f"{entry} is already in {self}")

        entry.playlist = self
        bisect.insort_left(self.entries, entry)
        self.save()
        return entry

    def add_entry(self, entry: PlayableEntry, author: User) -> PlaylistEntry:
        pl_entry = PlaylistEntry(entry, author_id=author.id)
        return self.add(pl_entry)

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

    def get_entry(self, entry_id: utils.UUIDType) -> Optional[PlaylistEntry]:
        entry_id = utils.get_uuid(entry_id)
        return next((entry for entry in self if entry.entry_id == entry_id), None)

    def search_entry(self, target: str, *, threshold: float = .8) -> Optional[PlaylistEntry]:
        return utils.search_entry(self.entries, target, threshold=threshold)

    def search_all_entries(self, target: str, *, threshold: float = .8) -> Iterator[Tuple[PlaylistEntry, float]]:
        return utils.search_entries(self.entries, target, threshold=threshold)

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

    def is_dirty(self) -> bool:
        if self._dirty:
            return True
        else:
            return any(entry.is_dirty() for entry in self.entries)

    def save(self):
        if hasattr(self, "__opened__"):
            log.debug("not saving playlist because it's open")
            return
        self.manager.save_playlist(self)

        self._dirty = False
        for entry in self.entries:
            entry._dirty = False

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

    async def play(self, queue: "EntryQueue", requester: User, *, position: int = None, shuffle: bool = True):
        entries = [pl_entry.get_wrapper() for pl_entry in self]
        if shuffle:
            random.shuffle(entries)
        queue.add_entries(entries, requester, position=position)

    async def generate_cover(self) -> Optional[str]:
        return await mosaic.generate_playlist_cover(self)
