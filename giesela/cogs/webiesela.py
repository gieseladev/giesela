import logging

from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PlaylistManager, RadioStationManager, WebieselaServer

log = logging.getLogger(__name__)

LOAD_ORDER = 2


class Webiesela:
    playlist_manager: PlaylistManager
    radio_station_manager: RadioStationManager

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.config = bot.config

        self.get_player = self.bot.get_player
        self.playlist_manager = self.bot.playlist_manager
        self.radio_station_manager = self.bot.radio_station_manager

    async def on_ready(self):
        if self.config.app.webiesela.start:
            log.info("starting Webiesela")
            WebieselaServer.run(self)

    async def on_shutdown(self):
        if self.config.app.webiesela.start and WebieselaServer.server:
            log.debug("stopping Webiesela")
            WebieselaServer.server.close()

    @commands.guild_only()
    @commands.command()
    async def register(self, ctx: Context, token: str):
        """Use this command in order to use Webiesela."""

        if WebieselaServer.register_information(ctx.guild.id, ctx.author.id, token.lower()):
            await ctx.send("You've successfully registered yourself. Go back to your browser and check it out")
        else:
            await ctx.send("Something went wrong while registering."
                           f"It could be that your code `{token.upper()}` is wrong."
                           "Please make sure that you've entered it correctly.")


def setup(bot: Giesela):
    bot.add_cog(Webiesela(bot))
