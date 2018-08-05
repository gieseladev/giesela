import logging

from giesela import Giesela, MusicPlayer, WebieselaServer
from .player import Player

log = logging.getLogger(__name__)


class Webiesela:
    bot: Giesela
    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.get_cog("Player")

    async def get_player(self, *args, **kwargs) -> MusicPlayer:
        return await self.player_cog.get_player(*args, **kwargs)

    async def on_ready(self):
        if self.bot.config.start_webiesela:
            log.info("starting Webiesela")
            WebieselaServer.run(self)


def setup(bot: Giesela):
    bot.add_cog(Webiesela(bot))
