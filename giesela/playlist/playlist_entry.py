import logging
import time
from typing import Optional, TYPE_CHECKING

from discord import User

from giesela import EntryWrapper, PlayableEntry, load_entry_from_dict

if TYPE_CHECKING:
    from .playlist import Playlist

__all__ = ["LoadedPlaylistEntry", "PlaylistEntry"]

log = logging.getLogger(__name__)


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

    def __init__(self, entry: PlayableEntry, *, author_id: User, added_at: int = None, last_editor_id: User = None, last_edit_at: int = None):
        self._entry = entry
        self._author_id = author_id
        self._added_at = added_at or time.time()
        self._last_editor_id = last_editor_id
        self._last_edit_at = last_edit_at

    def __repr__(self) -> str:
        playlist = repr(self.playlist)
        me = repr(self._entry)
        return f"{me} - {playlist}"

    def __getstate__(self) -> dict:
        return dict(entry=self._entry, author_id=self._author_id,
                    added_at=self._added_at, last_editor_id=self._last_editor_id, last_edit_at=self._last_edit_at)

    def __setstate__(self, state: dict):
        self._entry = state["entry"]
        self._author_id = state.get("author_id")
        self._added_at = state.get("added_at") or time.time()
        self._last_editor_id = state.get("last_editor_id")
        self._last_edit_at = state.get("last_edit_at")

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
        data["entry"] = load_entry_from_dict(data["entry"])
        return cls(**data)

    @property
    def author(self) -> Optional[User]:
        if self._author_id:
            return self.playlist.manager.bot.get_user(self._author_id)

    @property
    def added_at(self) -> int:
        return self._added_at

    @property
    def last_editor(self) -> Optional[User]:
        if self._last_editor_id:
            editor = self.playlist.manager.bot.get_user(self._last_editor_id)
        else:
            editor = None
        return editor or self.author

    @property
    def last_edit_at(self) -> int:
        return self._last_edit_at or self.added_at

    def to_gpl(self):
        data = self.__getstate__()
        entry = self._entry.to_dict()
        data["entry"] = entry
        return {key: value for key, value in data.items() if value is not None}

    def replace(self, entry: PlayableEntry, editor: User = None):
        before_sort_attr = self.sort_attr
        self._entry = entry
        if editor:
            self._last_editor_id = editor.id
            self._last_edit_at = time.time()

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
