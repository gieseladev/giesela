import asyncio
import contextlib
import itertools
import logging
from typing import List, Union

from discord import Colour, Embed, Forbidden, Member, Role, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PermManager, PermRole, PermissionDenied, perm_tree
from giesela.permission.tree_utils import PermissionType
from giesela.ui import PromptYesNo, VerticalTextViewer
from giesela.ui.custom import RoleEditor

log = logging.getLogger(__name__)


class Permissions:
    def __init__(self, bot: Giesela) -> None:
        self.bot = bot
        self.perm_manager = PermManager(bot)

        bot.store_reference("perm_manager", self.perm_manager)
        bot.store_reference("has_permission", self.has_permission)
        bot.store_reference("ensure_permission", self.ensure_permission)

    async def ensure_permission(self, ctx: Context, *keys: PermissionType, global_only: bool = False) -> bool:
        perm = await asyncio.gather(*(self.perm_manager.has(ctx.author, key, global_only=global_only) for key in keys), loop=self.bot.loop)
        if all(perm):
            return True
        else:
            keys_str = ", ".join(f"\"{key}\"" for key in keys)
            if global_only:
                text = f"Global permission {keys_str} required!"
            else:
                text = f"Permission {keys_str} required!"

            raise PermissionDenied(text)

    async def has_permission(self, ctx: Context, *keys: str, global_only: bool = False) -> bool:
        try:
            await self.ensure_permission(ctx, *keys, global_only=global_only)
        except PermissionDenied:
            return False
        else:
            return True

    async def _command_check(self, ctx: Context, attribute: str, global_only: bool) -> bool:
        try:
            required_permissions = getattr(ctx.command, attribute)
        except AttributeError:
            log.debug(f"no required permissions for {ctx.command}")
            return True
        else:
            log.debug(f"checking permissions {required_permissions}")
            await self.ensure_permission(ctx, *required_permissions, global_only=global_only)
            return True

    async def __global_check_once(self, ctx: Context) -> bool:
        return all(await asyncio.gather(
            self._command_check(ctx, "_required_permissions", False),
            self._command_check(ctx, "_required_global_permissions", True)
        ))

    async def get_roles_for(self, ctx: Context) -> List[PermRole]:
        guild_id = ctx.guild.id if ctx.guild else None
        return await self.perm_manager.get_roles_for(ctx.author, guild_id=guild_id)

    async def find_role(self, query: str, ctx: Context = None) -> PermRole:
        guild_id = ctx.guild.id if ctx and ctx.guild else None
        role = await self.perm_manager.get_role(query) or await self.perm_manager.search_role(query, guild_id=guild_id)

        if not role:
            raise commands.CommandError(f"Couldn't find role \"{query}\"")

        return role

    async def ensure_can_edit_role(self, ctx: Context, role: PermRole) -> None:
        # you may edit a role under two conditions:
        # - you are part of the role and the role has edit_self enabled
        # - you have a higher role which grants edit

        in_role = False

        for user_role in await self.perm_manager.get_roles_for(ctx.author, global_only=role.is_global):
            if user_role == role:
                in_role = True
                if role.has(perm_tree.permissions.roles.self):
                    return
            else:
                if user_role.position >= role.position:
                    return

        if in_role:
            raise PermissionDenied(f"Role \"{role.name}\" may not edit itself. \"{perm_tree.permissions.roles.self}\" required!")
        else:
            raise PermissionDenied(f"Permission \"{perm_tree.permissions.roles.edit}\" required!")

    @commands.is_owner()
    @commands.command("permreload")
    async def reload_perms_from_file(self, ctx: Context) -> None:
        """Reload permissions from file."""
        try:
            await self.perm_manager.load_from_file()
        except Exception as e:
            raise commands.CommandError(f"Couldn't load permission file: `{e}`")

        await ctx.send(embed=Embed(title="Loaded permission file!", colour=Colour.green()))

    @commands.command("roles")
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

    @commands.command("allroles")
    async def all_roles(self, ctx: Context) -> None:
        """Show all roles"""
        embed = Embed(title="Roles", colour=Colour.blue())
        if ctx.guild:
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon_url)

        try:
            guild_id = ctx.guild.id
        except AttributeError:
            guild_id = None

        roles = await self.perm_manager.get_guild_roles(guild_id, match_global=None if ctx.guild else True)

        if roles:
            role_text = "\n".join(f"- {role.name}" for role in roles)
            embed.description = f"```css\n{role_text}```"
        else:
            raise commands.CommandError("There are no roles")

        await ctx.send(embed=embed)

    @commands.command("permissions", aliases=["perms"])
    async def show_permissions(self, ctx: Context, *, target: Union[Member, User, Role, str] = None) -> None:
        """Show permissions"""
        icon = None

        if isinstance(target, str):
            role = await self.find_role(target, ctx)
            name = role.name
            roles = [role]
        elif isinstance(target, (Member, User, Role)):
            name = target.name
            roles = await self.perm_manager.get_roles_for(target)
        else:
            name = ctx.author.name
            icon = ctx.author.avatar_url
            roles = await self.get_roles_for(ctx)

        perm_trees = (role.permission_tree for role in roles)
        perms = perm_tree.prepare_permissions(itertools.chain.from_iterable(perm_trees))
        keys = sorted(key for key, value in perms.items() if value)

        if not keys:
            raise commands.CommandError(f"{name} doesn't have any permissions")

        frame = Embed(title="Permissions", colour=Colour.blue())
        frame.set_author(name=name, icon_url=icon or Embed.Empty)

        await VerticalTextViewer(ctx.channel, bot=self.bot, user=ctx.author, content=keys, embed_frame=frame).display()
        with contextlib.suppress(Forbidden):
            await ctx.message.delete()

    @commands.command("removerole", aliases=["rmrole"])
    async def remove_role(self, ctx: Context, *, role: str) -> None:
        """Delete a role"""
        role = await self.find_role(role, ctx)
        await self.ensure_can_edit_role(ctx, role)

        prompt = PromptYesNo(ctx.channel, bot=self.bot, user=ctx.author, text=f"Do you really want to delete \"{role.name}\"")
        if await prompt:
            await self.perm_manager.delete_role(role)

    @commands.command("createrole", aliases=["mkrole"])
    async def create_role(self, ctx: Context, *, name: str) -> None:
        """Create a new role"""
        await self.ensure_permission(ctx, perm_tree.permissions.roles.edit, global_only=ctx.guild is None)
        role = PermRole(role_id=None, name=name, position=None, guild_id=ctx.guild.id if ctx.guild else None)
        editor = RoleEditor(ctx.channel, bot=self.bot, user=ctx.author, perm_manager=self.perm_manager, role=role)
        await editor.display()

    @commands.command("editrole")
    async def edit_role(self, ctx: Context, *, role: str) -> None:
        """Edit a role"""
        role = await self.find_role(role, ctx)
        await self.ensure_can_edit_role(ctx, role)

        editor = RoleEditor(ctx.channel, bot=self.bot, user=ctx.author, perm_manager=self.perm_manager, role=role)
        await editor.display()


def setup(bot: Giesela):
    bot.add_cog(Permissions(bot))
