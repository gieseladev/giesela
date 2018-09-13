from discord import VoiceChannel
from discord.ext import commands
from discord.ext.commands import Bot, Context


class Tools:
    bot: Bot

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.guild_only()
    @commands.command()
    async def moveus(self, ctx: Context, target: VoiceChannel):
        """Move everyone in your current channel to another one!"""
        author_channel = ctx.author.voice.channel
        voice_members = author_channel.members

        for voice_member in voice_members:
            await voice_member.edit(voice_channel=target)


def setup(bot: Bot):
    bot.add_cog(Tools(bot))
