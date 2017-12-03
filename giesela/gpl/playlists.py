"""The top level module for the playlist system."""

import json
import logging
import os
import random
import string

from .models import Playlist, PlaylistEntry

log = logging.getLogger(__name__)


def _load_playlists(path):
    playlists = []

    for f_name in os.listdir(path):
        if not f_name.endswith(".gpl"):
            continue

        loc = os.path.join(path, f_name)

        with open(loc, "r") as f:
            pl = json.load(f)

        playlists.append(pl)

    return playlists


def _unique_id(length, existing_ids, *, custom_population=None):
    population = custom_population or string.hexdigits
    while True:
        tid = random.choices(population, k=length)

        if tid not in existing_ids:
            return tid


class PlaylistManager:
    """Manager."""

    def __init__(self, bot):
        """Initialise the playlist manager."""
        self.bot = bot
        self.loop = bot.loop

        self.playlists = None

        Playlist.manager = self
        PlaylistEntry.manager = self

        log.debug("playlist manager initialised.")

    def __str__(self):
        """Return string rep."""
        return "<PlaylistManager with {} playlist(s)>".format(len(self.playlists))

    def __getitem__(self, index):
        """Return playlist by id."""
        return next(playlist for playlist in self.playlists if playlist.gpl_id == index)

    async def setup(self):
        """Sets-up the manager.

        Loads the existing playlists from disk.
        """
        log.info("setting up playlist manager")
        log.debug("loading playlists")
        raw_pls = await self.loop.run_in_executor(None, _load_playlists, "data/playlists")
        log.debug("found {} raw playlists".format(len(raw_pls)))

        playlists = []

        for raw_pl in raw_pls:
            pl = Playlist.from_dict(raw_pl)
            playlists.append(pl)
            log.debug("loaded {}".format(pl))

        self.playlists = playlists
        log.info("playlist manager ready!")

    def get(*, name=None, gpl_id=None):
        """Search for a playlist by its name or by its id."""
        if not any(name, gpl_id):
            raise ValueError("Please provide a search criteria")
