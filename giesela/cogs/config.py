import yaml
from discord import Colour, Embed, Guild
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela
from giesela.config import TraverseError, abstract
from giesela.config.abstract import ConfigObject


async def show_config(ctx: Context, config: ConfigObject, key: str, default_name: str):
    if key:
        try:
            config = abstract.traverse_config(config, key)
        except TraverseError as e:
            parent = e.key or "Config"
            raise commands.CommandError(f"**{key}** doesn't exist. ({parent} doesn't have \"{e.target}\")")

    em = Embed(title=key or default_name, colour=Colour.blue())

    if not isinstance(config, ConfigObject):
        em.description = f"`{config}`"
        await ctx.send(embed=em)
        return

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


async def set_config_value(ctx: Context, config, key: str, value: str):
    try:
        value = yaml.safe_load(value)
    except yaml.YAMLError:
        raise commands.CommandError("Couldn't parse value")

    try:
        await config.set(key, value)
    except KeyError:
        raise commands.CommandError(f"Cannot set \"{key}\" directly")
    except TraverseError as e:
        parent = e.key or "Config"
        raise commands.CommandError(f"**{key}** doesn't exist. ({parent} doesn't have \"{e.target}\")")

    em = Embed(description=f"Set **{key}** to {value}", colour=Colour.green())
    await ctx.send(embed=em)


async def reset_config_value(ctx: Context, config, key: str):
    try:
        await config.reset(key)
    except KeyError:
        raise commands.CommandError(f"Cannot set \"{key}\" directly")
    except TraverseError as e:
        parent = e.key or "Config"
        raise commands.CommandError(f"**{key}** doesn't exist. ({parent} doesn't have \"{e.target}\")")

    value = await config.get(key)

    em = Embed(description=f"Reset **{key}** to default value: {value}", colour=Colour.dark_green())
    await ctx.send(embed=em)


class Config:
    def __init__(self, bot: Giesela):
        self.bot = bot
        self.config = bot.config

    async def on_guild_remove(self, guild: Guild):
        await self.config.remove_guild(guild.id)

    @commands.guild_only()
    @commands.group("config", invoke_without_command=True)
    async def config_command(self, ctx: Context, key: str = None):
        """Config stuff"""
        guild_config = await self.config.get_guild(ctx.guild.id).load()
        await show_config(ctx, guild_config, key, "Guild Config")

    @config_command.group("global", invoke_without_command=True, aliases=["runtime"])
    async def config_global(self, ctx: Context, key: str = None):
        """Global config"""
        global_config = await self.config.runtime.load()
        await show_config(ctx, global_config, key, "Global Config")

    @commands.is_owner()
    @commands.guild_only()
    @config_command.command("set")
    async def config_set(self, ctx: Context, key: str, *, value: str):
        """Set a config value"""
        guild_config = self.config.get_guild(ctx.guild.id)
        await set_config_value(ctx, guild_config, key, value)

    @commands.is_owner()
    @config_global.command("set")
    async def config_global_set(self, ctx: Context, key: str, *, value: str):
        """Set a global config value"""
        await set_config_value(ctx, self.config.runtime, key, value)

    @commands.is_owner()
    @commands.guild_only()
    @config_command.command("reset")
    async def config_reset(self, ctx: Context, key: str):
        """Reset a config value"""
        guild_config = self.config.get_guild(ctx.guild.id)
        await reset_config_value(ctx, guild_config, key)

    @commands.is_owner()
    @config_global.command("reset")
    async def config_global_reset(self, ctx: Context, key: str):
        """Reset a global config value"""
        await reset_config_value(ctx, self.config.runtime, key)


def setup(bot: Giesela):
    bot.add_cog(Config(bot))
