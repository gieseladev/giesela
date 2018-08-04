import logging

from giesela import Giesela, WebieselaServer

log = logging.getLogger(__name__)


class Webiesela:
    bot: Giesela

    def __init__(self, bot: Giesela):
        self.bot = bot

    async def on_ready(self):
        if self.bot.config.start_webiesela:
            log.info("starting Webiesela")
            WebieselaServer.run(self)


def setup(bot: Giesela):
    bot.add_cog(Webiesela(bot))
