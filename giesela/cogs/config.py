import yaml
from discord import Embed, Guild
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela
from giesela.config import TraverseError, abstract
from giesela.config.abstract import ConfigObject


class Config:
    def __init__(self, bot: Giesela):
        self.bot = bot
        self.config = bot.config

    @commands.group("config", invoke_without_command=True)
    async def config_command(self, ctx: Context, key: str = None):
        """Config stuff"""
        guild_config = await self.config.get_guild(ctx.guild.id).load()

        if key:
            try:
                config = abstract.traverse_config(guild_config, key)
            except TraverseError as e:
                parent = e.key or "Config"
                raise commands.CommandError(f"**{key}** doesn't exist. ({parent} doesn't have \"{e.target}\")")
        else:
            config = guild_config

        if not isinstance(config, ConfigObject):
            em = Embed(title=key, description=f"`{config}`")
            await ctx.send(embed=em)
            return

        em = Embed(title=key or "Guild Config")

        lines = []

        for key, value in abstract.config_items(config):
            if isinstance(value, ConfigObject):
                keys = abstract.config_keys(value)
                em.add_field(name=key, value="\n".join(keys))
            else:
                value = f"`{value}`" if value else "~"
                lines.append(f"**{key}** : {value}")

        em.description = "\n".join(lines)
        await ctx.send(embed=em)

    @config_command.command("set")
    async def config_set(self, ctx: Context, key: str, *, value: str):
        """Set a config"""
        guild_config = self.config.get_guild(ctx.guild.id)
        try:
            value = yaml.safe_load(value)
        except yaml.YAMLError:
            raise commands.CommandError("Couldn't parse value")

        # TODO make sure not overriding ConfigObject
        try:
            await guild_config.set(key, value)
        except KeyError:
            raise commands.CommandError(f"Cannot set \"{key}\" directly")
        except TraverseError as e:
            parent = e.key or "Config"
            raise commands.CommandError(f"**{key}** doesn't exist. ({parent} doesn't have \"{e.target}\")")

        em = Embed(description=f"Set **{key}** to {value}")
        await ctx.send(embed=em)

    async def on_guild_remove(self, guild: Guild):
        await self.config.remove_guild(guild.id)


def setup(bot: Giesela):
    bot.add_cog(Config(bot))
