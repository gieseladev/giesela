import dbm
import logging
import rapidjson
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from discord import User

from giesela import Giesela, utils as giesela_utils
from . import compat, utils
from .playlist import Playlist

__all__ = ["PlaylistManager"]

log = logging.getLogger(__name__)

_DEFAULT = object()


class PlaylistManager:
    _playlists: Dict[uuid.UUID, Playlist]
    _broken_playlists: List[compat.PlaylistRecovery]

    def __init__(self, bot: Giesela, storage):
        self.bot = bot
        self.storage = storage
        self._playlists = {}
        self._broken_playlists = []

        to_delete = []

        for gpl_id in self.storage:
            gpl_data = self.storage[gpl_id]
            try:
                gpl_data = rapidjson.loads(gpl_data)
            except ValueError:
                log.warning(f"Couldn't decode data for playlist {gpl_id}. removing!")
                to_delete.append(gpl_id)
                continue

            try:
                playlist = Playlist.from_gpl(gpl_data)
            except Exception:
                log.exception(f"Couldn't load playlist {gpl_id}")

                recovery = compat.get_recovery_plan(self, gpl_data)

                if recovery:
                    self._broken_playlists.append(recovery)
                else:
                    log.warning(f"Can't recover playlist {gpl_id}")
                    to_delete.append(gpl_id)

                continue

            playlist.manager = self
            self._playlists[playlist.gpl_id] = playlist

        if to_delete:
            log.info(f"removing {len(to_delete)} playlists")
            for gpl_id in to_delete:
                del self.storage[gpl_id]

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
        storage = dbm.open(str(storage_location), flag="c")
        inst = cls(bot, storage)
        return inst

    def close(self):
        log.info("closing playlists")
        self.storage.close()

    def import_from_gpl(self, playlist: Union[dict, str], *, author: User = None) -> Optional[Playlist]:
        if isinstance(playlist, str):
            try:
                playlist = rapidjson.loads(playlist)
            except ValueError:
                return

        try:
            playlist = Playlist.from_gpl(playlist)
        except Exception as e:
            log.warning("Couldn't import playlist", exc_info=e)
            return

        if author:
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
        gpl_data = playlist.to_gpl()
        self.storage[playlist.gpl_id.hex] = rapidjson.dumps(gpl_data)
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
            similarity = giesela_utils.similarity(name, (playlist.name, playlist.description), lower=True)
            if similarity > _similarity:
                _playlist = playlist
                _similarity = similarity

        if _similarity <= threshold:
            return None

        return _playlist
