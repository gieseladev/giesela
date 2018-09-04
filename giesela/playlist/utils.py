import logging
import uuid
from typing import Iterable, Iterator, Optional, TYPE_CHECKING, Tuple, Union

from giesela import BaseEntry, utils

if TYPE_CHECKING:
    from .playlist_entry import PlaylistEntry

__all__ = ["get_uuid", "search_entries", "search_entry"]

log = logging.getLogger(__name__)

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
            if similarity == 1:
                return pl_entry
            _entry = pl_entry
            _similarity = similarity

    if _similarity <= threshold:
        return None

    return _entry
