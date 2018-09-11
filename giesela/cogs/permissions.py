from discord.ext.commands import Bot, Context


class Permissions:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def __global_check(self, ctx: Context) -> bool:
        return True


def setup(bot: Bot):
    bot.add_cog(Permissions(bot))
