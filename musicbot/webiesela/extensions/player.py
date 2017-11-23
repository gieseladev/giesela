"""Module for the player extension."""

import logging

from ..extension import Extension, command
from ..models.exceptions import ParamError

log = logging.getLogger(__name__)


class Player(Extension):
    """The actual extension."""

    async def get_player(self, server):
        """Return the player for a server."""
        return await self.bot.get_player(server)

    @command("volume")
    async def volume(self, message, server, value):
        """Volume endpoint to set the volume."""
        assert (0 <= value <= 1), ParamError("volume must be between 0 and 1 (inclusive)", "value")

        player = await self.get_player(server)

        player.volume = value
