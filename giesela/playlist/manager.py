import json
import logging
import uuid
from pathlib import Path
from shelve import DbfilenameShelf, Shelf
from typing import Any, Dict, Iterable, Optional, Union

from discord import User

from giesela import Giesela
from . import utils
from .playlist import Playlist

__all__ = ["PlaylistManager"]

log = logging.getLogger(__name__)

_DEFAULT = object()


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

    def get_playlist(self, gpl_id: utils.UUIDType, default: Any = _DEFAULT) -> Optional[Playlist]:
        try:
            gpl_id = utils.get_uuid(gpl_id)
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
