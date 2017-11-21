"""Module for the player extension."""

import logging

from ..extension import Extension, command

log = logging.getLogger(__name__)


class Player(Extension):
    """The actual extension."""

    async def on_load(self):
        pass

    @command("volume")
    async def volume(self, connection, value):
        """Volume endpoint to set the volume."""
        pass
