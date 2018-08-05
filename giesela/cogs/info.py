from discord import Embed
from discord.ext import commands
from discord.ext.commands import Bot, Context

from giesela.constants import VERSION as BOTVERSION
from giesela.utils import (get_dev_version,
                           get_version_changelog)


class Info:
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.command()
    async def version(self, ctx: Context):
        """Some more information about the current version and what's to come."""

        async with ctx.typing():
            v_code, v_name = BOTVERSION.split("_", 1)
            dev_code, dev_name = get_dev_version()
            if v_code == dev_code:
                changelog = "**Up to date!**"
            else:
                changelog = "**What's to come:**\n\n"
                changelog += "\n".join(
                    "● " + l for l in get_version_changelog()
                )

            desc = "Current Version is `{}`\nDevelopment is at `{}`\n\n{}".format(
                BOTVERSION, dev_code + "_" + dev_name, changelog)[:2000]

            em = Embed(title="Version \"{}\"".format(v_name.replace("_", " ").title()), description=desc,
                       url="https://gieseladev.github.io/Giesela", colour=0x67BE2E)

            await ctx.send(embed=em)


def setup(bot: Bot):
    bot.add_cog(Info(bot))
