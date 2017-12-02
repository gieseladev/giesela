"""The top level module for the playlist system."""

import logging
import os

log = logging.getLogger(__name__)


def _load_playlists():
    playlists = []

    for f_name in os.listdir("path"):
        pl = None
        playlists.append(pl)

    return playlists


class PlaylistManager:
    """Manager."""

    def __init__(self, playlists):
        """Initialise the playlist manager."""
        self.playlists = playlists

        log.info("playlist manager initialised.")

    @classmethod
    def setup(cls):
        """Sets-up the manager.

        Loads the existing playlists from disk.
        """
        return cls(_load_playlists())
