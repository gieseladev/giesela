import bisect
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, TYPE_CHECKING, Union

from discord import User

from giesela import PlayableEntry
from giesela.ui import text as text_utils
from . import utils
from .entry import PlaylistEntry

if TYPE_CHECKING:
    from .playlist import Playlist

__all__ = ["EditPlaylistProxy"]

log = logging.getLogger(__name__)


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

    def apply(self, playlist: "Playlist") -> bool:
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
    _pl_entries: List[PlaylistEntry]
    _entry_map: Dict[PlaylistEntry, EditChange]

    _changes: Deque[EditChange]

    def __init__(self, playlist: "Playlist"):
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
        return utils.search_entry(self._pl_entries, target, threshold=threshold)

    def add_entry(self, entry: PlayableEntry, author: User) -> PlaylistEntry:
        pl_entry = PlaylistEntry(entry, author_id=author.id)

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
