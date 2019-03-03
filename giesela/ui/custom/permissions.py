import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from discord import Client, Colour, Embed, Message, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import PermissionDenied, utils
from giesela.permission import PermManager, PermissionType, Role, perm_tree
from giesela.ui import VerticalTextViewer
from .. import text as text_utils
from ..help import AutoHelpEmbed
from ..interactive import MessageableEmbed, emoji_handler

log = logging.getLogger(__name__)


class RoleViewer(AutoHelpEmbed, VerticalTextViewer):
    bases: Optional[List[Role]]
    permissions: List[Tuple[str, int]]
    showing_simplified: bool
    showing_base_permissions: bool

    _role_pool: Dict[str, Role]

    def __init__(self, channel: TextChannel, *,
                 perm_manager: PermManager,
                 role: Role,
                 bot: Client,
                 user: Optional[User],
                 message: Message = None,
                 **kwargs) -> None:
        super().__init__(channel, bot=bot, user=user, message=message, **kwargs)

        self.perm_manager = perm_manager
        self.role = role
        self._role_pool = {role.absolute_role_id: role}
        self.bases = None

        self.showing_simplified = True
        self.showing_base_permissions = False
        self.compile_permissions()

        self._load_bases()

    @property
    def help_title(self) -> str:
        return "Role Viewer"

    @property
    def help_description(self) -> str:
        return "Look at your favourite role today for just $5.49."

    @property
    def embed_frame(self) -> Embed:
        embed = Embed(title=self.role.name,
                      description="No permissions yet",
                      colour=Colour.dark_gold() if self.showing_simplified else Colour.blue())

        if self.bases is None:
            base_value = "Loading"
        elif self.bases:
            base_value = ", ".join(base.name for base in self.bases)
        else:
            base_value = "None"

        bases_name = "Bases"
        if self.showing_base_permissions:
            bases_name += " (shown)"
        embed.add_field(name=bases_name, value=base_value)

        embed.set_footer(text=f"id: {self.role.absolute_role_id}")

        return embed

    @property
    def total_lines(self) -> int:
        return len(self.permissions)

    def _add_role_pool(self, role_pool: Dict[str, Role]) -> None:
        """Add a new role pool to the internal one"""
        for role_id, role in role_pool.items():
            self._role_pool.setdefault(role_id, role)

    def _load_bases(self) -> None:
        """Start the loading process for the bases"""

        async def loader():
            base_ids = self.role.base_ids
            role_pool = await self.perm_manager.get_roles_with_bases(*base_ids)
            self._add_role_pool(role_pool)

            self.bases = [self._role_pool[base_id] for base_id in base_ids]

            await self.show_window()

        _ = asyncio.ensure_future(loader())

    async def get_line(self, line: int) -> str:
        table = {1: "🗸", 0: "⨯"}
        key, value = self.permissions[line]
        return f"{table[value]} {key}"

    def compile_permissions(self) -> None:
        """Update`permissions`."""
        if self.showing_base_permissions and self.bases is not None:
            compiled = self.role.compile_permissions(self._role_pool)
        else:
            compiled = {}
            perm_tree.resolve_permission_specifiers(compiled, self.role.grant, 1)
            perm_tree.resolve_permission_specifiers(compiled, self.role.deny, 0)

        if self.showing_simplified:
            clean_rep = perm_tree.find_shortest_representation(compiled)
            permissions = [(key, int(clean_rep[key])) for key in sorted(clean_rep.keys())]
        else:
            permissions = [(key, compiled[key]) for key in sorted(compiled.keys())]

        self.permissions = permissions

    @emoji_handler("🔎", pos=500)
    async def show_simplified(self, *_) -> None:
        """Show simplified permissions"""
        self.showing_simplified = not self.showing_simplified
        self.compile_permissions()
        await self.show_window()

    @emoji_handler("📥", pos=501)
    async def show_base_permissions(self, *_) -> None:
        """Include bases' permissions"""
        self.showing_base_permissions = not self.showing_base_permissions
        self.compile_permissions()
        await self.show_window()

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Close without saving"""
        self.stop_listener()
        return None


class RoleEditor(RoleViewer, MessageableEmbed):
    def __init__(self, channel: TextChannel, *,
                 perm_manager: PermManager,
                 role: Role,
                 bot: Client,
                 user: User,
                 message: Message = None,
                 delete_msgs: bool = True,
                 **kwargs) -> None:
        super().__init__(channel, perm_manager=perm_manager, role=role, bot=bot, user=user, message=message, delete_msgs=delete_msgs, **kwargs)

        if not self.user:
            raise ValueError("Absolutely need user to be passed for permission checks!")

        self.showing_simplified = False

    @property
    def help_title(self) -> str:
        return "Role Editor"

    @property
    def help_description(self) -> str:
        return "Edit your favourite role today for just $9.99."

    @property
    def embed_frame(self) -> Embed:
        embed = super().embed_frame

        if self.error:
            embed.colour = Colour.red()
            embed.add_field(name="Error", value=f"**{self.error}**", inline=False)
            self.error = None

        return embed

    async def on_command_error(self, ctx: Optional[Context], exception: Exception):
        await super().on_command_error(ctx, exception)
        await self.show_window()

    async def on_emoji_handler_error(self, error: Exception, *args) -> None:
        await self.on_command_error(None, error)

    async def find_role(self, ctx: Context, query: str) -> Role:
        guild_id = ctx.guild.id if ctx.guild else None
        role = await self.perm_manager.get_or_search_role_for_guild(query, guild_id=guild_id)
        if not role:
            raise commands.CommandError(f"Couldn't find role \"{query}\"")
        return role

    async def check_role(self) -> List[str]:
        missing: List[str] = []

        role = await self.perm_manager.get_or_search_role_for_guild(self.role.name, guild_id=self.role.guild_id)
        if role and role.absolute_role_id != self.role.absolute_role_id:
            if role.name == self.role.name:
                missing.append("role name already exists")

        if not any((self.role.grant, self.role.deny, self.role.base_ids)):
            missing.append("no permissions set")

        return missing

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_) -> bool:
        """Close and save"""
        missing = await self.check_role()
        if missing:
            raise commands.CommandError(text_utils.fluid_list_join(missing))

        await self.perm_manager.save_role(self.role)
        self.stop_listener()
        return True

    async def _set_perm_cmd(self, permission: str, grant: Optional[bool]) -> None:
        if not perm_tree.has(permission):
            raise commands.CommandError(f"`{permission}` doesn't exist!")

        if not await self.perm_manager.has(self.user, permission, global_only=self.role.is_global):
            action = "grant" if grant else "deny"
            raise PermissionDenied(f"You need to have a permission to {action} it!")

        def _try_remove(perm_list: List[PermissionType]) -> bool:
            try:
                perm_list.remove(permission)
            except ValueError:
                return False
            else:
                return True

        if grant is None:
            if not any((_try_remove(self.role.grant), _try_remove(self.role.deny))):
                raise commands.CommandError(f"Permission {permission} isn't set")
        else:
            if grant:
                add_list = self.role.grant
                remove_list = self.role.deny
            else:
                add_list = self.role.deny
                remove_list = self.role.grant

            _try_remove(remove_list)
            add_list.append(permission)

        self.compile_permissions()
        await self.show_window()

    @commands.command("rename", aliases=["setname", "name"])
    async def rename_cmd(self, ctx: Context, name: str) -> None:
        """Rename the role"""
        if not name:
            raise commands.CommandError("Please provide a name")

        role = await self.perm_manager.get_or_search_role_for_guild(name, ctx.guild.id if ctx.guild else None)
        if role and self.role.name == role.name and role.absolute_role_id != self.role.absolute_role_id:
            raise commands.CommandError(f"Name **{name}** already assigned to a role")

        self.role.name = name

        await self.show_window()

    @commands.command("grant", aliases=["allow", "add"])
    async def grant_permission(self, _, permission: str) -> None:
        """Grant a permission"""
        await self._set_perm_cmd(permission, True)

    @commands.command("deny", aliases=["revoke"])
    async def deny_permission(self, _, permission: str) -> None:
        """Deny a permission"""
        await self._set_perm_cmd(permission, False)

    @commands.command("unset", aliases=["remove", "rm"])
    async def unset_permission_cmd(self, _, permission: str) -> None:
        """Unset a permission"""
        await self._set_perm_cmd(permission, None)

    def _ensure_bases_loaded(self) -> None:
        if self.bases is None:
            raise commands.CommandError("Please wait for the bases to finish loading")

    @commands.command("addbase", aliases=["inherit"])
    async def add_base(self, ctx: Context, *, role: str) -> None:
        """Add base to role"""
        self._ensure_bases_loaded()

        role = await self.find_role(ctx, role)
        if role.absolute_role_id == self.role.absolute_role_id:
            raise commands.CommandError("Cannot inherit from the same role...")

        if role.absolute_role_id in self.role.base_ids:
            raise commands.CommandError(f"Already inheriting from {role.name}")

        if not await self.perm_manager.can_edit_role(ctx.author, role, assign=True):
            raise PermissionDenied("You need to be able to assign a role to use it as a base!")

        if not role.is_default:
            if self.role.role_context != role.role_context:
                raise commands.CommandError(
                    f"Can't inherit across contexts! {self.role.name} is {self.role.role_context.value} and {role.name} is {role.role_context.value}")

            if self.role.guild_id != role.guild_id:
                raise commands.CommandError(f"Can't inherit roles from different guilds!")

        if role.absolute_role_id not in self._role_pool:
            role_pool = await self.perm_manager.get_roles_with_bases(*role.base_ids)
            role_pool.setdefault(role.absolute_role_id, role)

            if self.role.absolute_role_id in role_pool:
                raise commands.CommandError(f"Circular reference detected. You cannot inherit a base which inherits from this one.")

            self._add_role_pool(role_pool)

        self.bases.append(role)
        self.role.base_ids.append(role.absolute_role_id)

        if self.showing_base_permissions:
            self.compile_permissions()

        await self.show_window()

    @commands.command("removebase", aliases=["rmbase", "uninherit"])
    async def remove_base(self, _, *, role: str) -> None:
        """Remove base from role"""
        self._ensure_bases_loaded()

        base = None
        similarity = 0
        for _base in self.bases:
            if _base.absolute_role_id == role:
                sim = 1
            else:
                sim = utils.similarity(role, _base.name, lower=True)

            if sim > similarity:
                base = _base
                similarity = sim

            if similarity == 1:
                break

        if not base or similarity < .6:
            raise commands.CommandError(f"Couldn't find base \"{role}\"")

        self.bases.remove(base)
        self.role.base_ids.remove(base.absolute_role_id)

        if self.showing_base_permissions:
            self.compile_permissions()

        await self.show_window()
