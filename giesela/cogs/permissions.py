import asyncio
import contextlib
import logging
from typing import List, Union, overload

from discord import Colour, Embed, Forbidden, Guild, Member, Role, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PermManager, PermissionDenied, Role as PermRole, perm_tree
from giesela.permission import RoleTargetType
from giesela.permission.tree_utils import PermissionType, calculate_final_permissions
from giesela.ui import PromptYesNo, VerticalTextViewer
from giesela.ui.custom import RoleEditor

log = logging.getLogger(__name__)


class Permissions:
    def __init__(self, bot: Giesela) -> None:
        self.bot = bot
        self.perm_manager = PermManager(bot)

        bot.store_reference("perm_manager", self.perm_manager)
        bot.store_reference("ensure_permission", self.ensure_permission)

    async def ensure_permission(self, ctx: Context, *keys: PermissionType, global_only: bool = False) -> bool:
        """Make sure the ctx has the given permissions, raise PermissionDenied otherwise."""
        has_perm = await self.perm_manager.has(ctx.author, *keys, global_only=global_only)
        if has_perm:
            return True
        else:
            keys_str = ", ".join(f"\"{key}\"" for key in keys)
            if global_only:
                text = f"Global permission {keys_str} required!"
            else:
                text = f"Permission {keys_str} required!"

            raise PermissionDenied(text)

    async def ensure_can_edit_role(self, ctx: Context, role: PermRole) -> None:
        can_edit = await self.perm_manager.can_edit_role(ctx.author, role)
        if not can_edit:
            raise PermissionDenied(f"Cannot edit role {role.name}!")

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

    @overload
    async def get_roles_for(self, ctx: Member) -> List[PermRole]:
        ...

    @overload
    async def get_roles_for(self, ctx: User, guild_id: int = None) -> List[PermRole]:
        ...

    @overload
    async def get_roles_for(self, ctx: Context) -> List[PermRole]:
        ...

    async def get_roles_for(self, ctx: Union[Context, Member, User], guild_id: int = None) -> List[PermRole]:
        """Get all roles for the target."""
        if isinstance(ctx, Context):
            ctx = ctx.author

        if isinstance(ctx, Member):
            guild_id = ctx.guild.id
            target = ctx
        else:
            target = ctx

        return await self.perm_manager.get_target_roles_for_guild(target, guild_id=guild_id)

    async def get_role(self, query: str, guild_id: Union[Context, Guild, int] = None) -> PermRole:
        """Get a role either by its id or its name.
        Raises:
            `CommandError`: No role was found
        """
        if isinstance(guild_id, Context):
            guild_id = guild_id.guild

        if isinstance(guild_id, Guild):
            guild_id = guild_id.id

        role = await self.perm_manager.get_or_search_role_for_guild(query, guild_id)

        if not role:
            raise commands.CommandError(f"Couldn't find role \"{query}\"")

        return role

    @commands.group("role", invoke_without_command=True, aliases=["roles"])
    async def role_group(self, ctx: Context, target: RoleTargetType) -> None:
        """"""
        pass

    @role_group.group("list", aliases=["show"])
    async def role_list_group(self, ctx: Context) -> None:
        """"""
        pass

    @role_list_group.command("me")
    async def role_list_me_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_list_group.command("guild")
    async def role_list_guild_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_list_group.command("all")
    async def role_list_all_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_group.command("create", aliases=["make", "mk"])
    async def role_create_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_group.command("remove", aliases=["rm", "delete", "del"])
    async def role_remove_cmd(self, ctx: Context, role: str) -> None:
        """"""
        role = await self.get_role(role, ctx)
        await self.ensure_can_edit_role(ctx, role)
        await self.perm_manager.delete_role(role)

        embed = Embed(description=f"Role **{role.name}** deleted!", colour=Colour.green())
        await ctx.send(embed=embed)

    @role_group.command("move", aliases=["mv", "setpriority", "setprio"])
    async def role_move_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_group.command("edit", aliases=["change"])
    async def role_edit_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_group.command("assign", aliases=["addtarget", "target+", "@+"])
    async def role_assign_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @role_group.command("retract", aliases=["removetarget", "rmtarget", "target-", "@-"])
    async def role_retract_cmd(self, ctx: Context) -> None:
        """"""
        pass

    @commands.is_owner()
    @commands.command("permreload")
    async def reload_perms_from_file(self, ctx: Context) -> None:
        """Reload permissions from file."""
        try:
            await self.perm_manager.load_from_file()
        except Exception as e:
            raise commands.CommandError(f"Couldn't load permission file: `{e}`")

        await ctx.send(embed=Embed(title="Loaded permission file!", colour=Colour.green()))

    @commands.command("legacyroles")
    async def permission_roles(self, ctx: Context, target: Union[Member, User, Role] = None) -> None:
        """Show your roles"""
        target = target or ctx.author

        embed = Embed(title="Roles", colour=Colour.blue())
        embed.set_author(name=target.name, icon_url=target.avatar_url if not isinstance(target, Role) else Embed.Empty)

        try:
            guild_id = target.guild.id
        except AttributeError:
            guild_id = None

        roles = await self.get_roles_for(target, guild_id=guild_id)

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

        roles = await self.perm_manager.get_all_roles_for_guild(guild_id)

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
            role = await self.get_role(target, ctx)
            name = role.name
            roles = [role]
        elif isinstance(target, (Member, User, Role)):
            name = target.name
            roles = await self.get_roles_for(target)
        else:
            name = ctx.author.name
            icon = ctx.author.avatar_url
            roles = await self.get_roles_for(ctx)

        perms = calculate_final_permissions(role.compile_own_permissions() for role in roles)
        keys = sorted(perm_tree.find_shortest_representation(perms))

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
        role = await self.get_role(role, ctx)
        await self.ensure_can_edit_role(ctx, role)

        prompt = PromptYesNo(ctx.channel, bot=self.bot, user=ctx.author, text=f"Do you really want to delete \"{role.name}\"")
        if await prompt:
            await self.perm_manager.delete_role(role)

    @commands.command("createrole", aliases=["mkrole"])
    async def create_role(self, ctx: Context, *, name: str) -> None:
        """Create a new role"""
        await self.ensure_permission(ctx, perm_tree.permissions.roles.edit, global_only=ctx.guild is None)
        # role = PermRole(role_id=None, name=name, position=None, guild_id=ctx.guild.id if ctx.guild else None)
        # editor = RoleEditor(ctx.channel, bot=self.bot, user=ctx.author, perm_manager=self.perm_manager, role=role)
        # await editor.display()

    @commands.command("editrole")
    async def edit_role(self, ctx: Context, *, role: str) -> None:
        """Edit a role"""
        role = await self.get_role(role, ctx)
        await self.ensure_can_edit_role(ctx, role)

        editor = RoleEditor(ctx.channel, bot=self.bot, user=ctx.author, perm_manager=self.perm_manager, role=role)
        await editor.display()


def setup(bot: Giesela):
    bot.add_cog(Permissions(bot))
