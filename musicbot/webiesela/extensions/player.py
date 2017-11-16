import logging

from ..extension import Extension, command

log = logging.getLogger(__name__)


class Player(Extension):
    async def on_load(self):
        pass

    @command("volume")
    async def volume(self, connection, value):
        pass
