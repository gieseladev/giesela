from discord import VoiceChannel
from discord.ext import commands
from discord.ext.commands import Bot, Context

from giesela import permission
from giesela.permission import perm_tree


class Tools:
    bot: Bot

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @commands.guild_only()
    @permission.has_permission(perm_tree.summon, perm_tree.admin.control.impersonate)
    @commands.command()
    async def moveus(self, ctx: Context, target: VoiceChannel):
        """Move everyone in your current channel to another one!"""
        author_channel = ctx.author.voice.channel
        voice_members = author_channel.members

        for voice_member in voice_members:
            await voice_member.edit(voice_channel=target)


def setup(bot: Bot):
    bot.add_cog(Tools(bot))
