import logging
import time
import uuid
from typing import Optional, TYPE_CHECKING, Union

from discord import User

from giesela import EntryWrapper, PlayableEntry, load_entry_from_dict
from . import utils

if TYPE_CHECKING:
    from .playlist import Playlist
    from .manager import PlaylistManager

__all__ = ["LoadedPlaylistEntry", "PlaylistEntry"]

log = logging.getLogger(__name__)


class LoadedPlaylistEntry(EntryWrapper):
    def __init__(self, *, playlist: Union["Playlist", str], playlist_entry: Union["PlaylistEntry", str], **kwargs):
        super().__init__(**kwargs)

        if isinstance(playlist, str):
            self._playlist = None
            self._gpl_id = playlist
        else:
            self._playlist = playlist
            self._gpl_id = playlist.gpl_id.hex

        if isinstance(playlist_entry, str):
            self._playlist_entry = None
            self._entry_id = playlist_entry
        else:
            self._playlist_entry = playlist_entry
            self._entry_id = playlist_entry.entry_id.hex

    @property
    def playlist_manager(self) -> "PlaylistManager":
        queue = self.highest_wrapper.get("queue")
        return queue.player.bot.cogs["Playlist"].playlist_manager

    @property
    def playlist(self) -> "Playlist":
        if not self._playlist:
            self._playlist = self.playlist_manager.get_playlist(self._gpl_id)
        return self._playlist

    @property
    def playlist_entry(self) -> "PlaylistEntry":
        if not self._playlist_entry:
            # MAYBE remove this wrapper if it isn't part of a playlist anymore!
            self._playlist_entry = self.playlist.get_entry(self._entry_id)
        return self._playlist_entry

    @classmethod
    def create(cls, playlist_entry: "PlaylistEntry") -> "LoadedPlaylistEntry":
        return cls(playlist_entry=playlist_entry, playlist=playlist_entry.playlist, entry=playlist_entry.entry)

    def to_dict(self):
        data = super().to_dict()
        data.update(playlist=self._gpl_id, playlist_entry=self._entry_id)
        return data


class PlaylistEntry:
    playlist: "Playlist" = None

    def __init__(self, entry: PlayableEntry, entry_id: utils.UUIDType = None, author_id: User = None, *,
                 added_at: int = None, last_editor_id: User = None, last_edit_at: int = None):
        self._dirty = False

        self._entry = entry

        if entry_id:
            entry_id = utils.get_uuid(entry_id)
        else:
            entry_id = uuid.uuid4()
            self._dirty = True

        self._entry_id = entry_id

        self._author_id = author_id
        self._added_at = added_at or round(time.time())
        self._last_editor_id = last_editor_id
        self._last_edit_at = last_edit_at

    def __repr__(self) -> str:
        playlist = repr(self.playlist)
        me = repr(self._entry)
        uid = self._entry_id
        return f"{me} ({uid}) - {playlist}"

    def __hash__(self) -> int:
        return hash(self._entry_id)

    def __eq__(self, other) -> bool:
        if isinstance(other, PlaylistEntry):
            return self is other
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
    def entry_id(self):
        return self._entry_id

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
        entry = self._entry.to_dict()
        data = dict(entry=entry, entry_id=self._entry_id.hex, author_id=self._author_id,
                    added_at=self._added_at, last_editor_id=self._last_editor_id, last_edit_at=self._last_edit_at)
        return {key: value for key, value in data.items() if value is not None}

    def replace(self, entry: PlayableEntry, editor: User = None):
        before_sort_attr = self.sort_attr
        self._entry = entry
        if editor:
            self._last_editor_id = editor.id
            self._last_edit_at = round(time.time())

        self.save(reorder=self.sort_attr != before_sort_attr)

    def is_dirty(self) -> bool:
        return self._dirty

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
