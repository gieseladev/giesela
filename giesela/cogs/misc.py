from discord.ext import commands
from discord.ext.commands import Bot, Context

from giesela.webiesela import WebieselaServer


class Misc:
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.command()
    async def register(self, ctx: Context, token: str):
        """Use this command in order to use the [Giesela-Website]({web_url})."""

        if WebieselaServer.register_information(ctx.guild.id, ctx.author.id, token.lower()):
            await ctx.send("You've successfully registered yourself. Go back to your browser and check it out")
        else:
            await ctx.send("Something went wrong while registering."
                           f"It could be that your code `{token.upper()}` is wrong."
                           "Please make sure that you've entered it correctly.")


def setup(bot: Bot):
    bot.add_cog(Misc(bot))
