from discord.ext.commands import Bot


class Misc:
    def __init__(self, bot: Bot):
        self.bot = bot


def setup(bot: Bot):
    bot.add_cog(Misc(bot))
