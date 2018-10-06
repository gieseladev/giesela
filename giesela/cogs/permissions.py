import asyncio
import logging
from typing import Union

from discord import Colour, Embed, Member, Role, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PermManager, PermissionDenied

log = logging.getLogger(__name__)


class Permissions:
    def __init__(self, bot: Giesela) -> None:
        self.bot = bot
        self.perm_manager = PermManager(bot)

        bot.store_reference("perm_manager", self.perm_manager)
        bot.store_reference("has_permission", self.has_permission)
        bot.store_reference("ensure_permission", self.ensure_permission)

    async def ensure_permission(self, ctx: Context, *keys: str):
        perm = await asyncio.gather(*(self.perm_manager.has(ctx.author, key) for key in keys), loop=self.bot.loop)
        if all(perm):
            return True
        else:
            keys_str = ", ".join(f"\"{key}\"" for key in keys)
            raise PermissionDenied(f"Permission {keys_str} required!")

    async def has_permission(self, ctx: Context, *keys: str) -> bool:
        try:
            await self.ensure_permission(ctx, *keys)
        except PermissionDenied:
            return False
        else:
            return True

    # TODO: find better solution for help command
    async def __global_check_once(self, ctx: Context) -> bool:
        try:
            required_permissions = getattr(ctx.command, "_required_permissions")
        except AttributeError:
            log.debug(f"no required permissions for {ctx.command}")
            return True
        else:
            log.debug(f"checking permissions {required_permissions}")
            await self.ensure_permission(ctx, *required_permissions)
            return True

    @commands.is_owner()
    @commands.command("permreload")
    async def reload_perms_from_file(self, ctx: Context) -> None:
        """Reload permissions from file."""
        try:
            await self.perm_manager.load_from_file()
        except Exception as e:
            raise commands.CommandError(f"Couldn't load permission file: `{e}`")

        await ctx.send(embed=Embed(title="Loaded permission file!", colour=Colour.green()))

    @commands.command("permroles")
    async def permission_roles(self, ctx: Context, target: Union[Member, User, Role] = None) -> None:
        """Show your roles"""
        target = target or ctx.author

        embed = Embed(title="Roles", colour=Colour.blue())
        embed.set_author(name=target.name, icon_url=target.avatar_url if not isinstance(target, Role) else Embed.Empty)

        try:
            guild_id = target.guild.id
        except AttributeError:
            guild_id = None

        roles = await self.perm_manager.get_roles_for(target, guild_id=guild_id)

        if roles:
            role_text = "\n".join(f"- {role.name}" for role in roles)
            embed.description = f"```css\n{role_text}```"
        else:
            embed.title = "No roles"
            embed.description = ("You aren't" if ctx.author == target else f"{target} isn't") + " part of any roles"

        await ctx.send(embed=embed)


def setup(bot: Giesela):
    bot.add_cog(Permissions(bot))
