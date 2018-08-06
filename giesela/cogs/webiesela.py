import logging

from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, MusicPlayer, WebieselaServer
from .player import Player

log = logging.getLogger(__name__)

LOAD_ORDER = 1


class Webiesela:
    bot: Giesela

    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.cogs["Player"]

    async def get_player(self, *args, **kwargs) -> MusicPlayer:
        return await self.player_cog.get_player(*args, **kwargs)

    async def on_ready(self):
        if self.bot.config.start_webiesela:
            log.info("starting Webiesela")
            WebieselaServer.run(self)

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
