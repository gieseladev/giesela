import logging

from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PlaylistManager, RadioStationManager, WebieselaServer
from .player import Player
from .playlist import PlaylistCog
from .radio import Radio

log = logging.getLogger(__name__)

LOAD_ORDER = 2


class Webiesela:
    bot: Giesela

    player_cog: Player
    playlist_cog: PlaylistCog
    playlist_manager: PlaylistManager
    radio_cog: Radio
    radio_station_manager: RadioStationManager

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.cogs["Player"]
        self.playlist_cog = bot.cogs["Playlist"]

        self.get_player = self.player_cog.get_player

        self.playlist_manager = self.playlist_cog.playlist_manager
        self.radio_cog = bot.cogs["Radio"]
        self.radio_station_manager = self.radio_cog.station_manager

    async def on_ready(self):
        if self.bot.config.start_webiesela:
            log.info("starting Webiesela")
            WebieselaServer.run(self)

    async def on_shutdown(self):
        if self.bot.config.start_webiesela:
            log.debug("stopping Webiesela")
            WebieselaServer.server.close()

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
