import logging
from typing import List, Optional, Tuple

from discord import Client, Colour, Embed, Message, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import PermManager, Role, perm_tree, utils
from giesela.ui import VerticalTextViewer
from .. import text as text_utils
from ..help import AutoHelpEmbed
from ..interactive import MessageableEmbed, emoji_handler

log = logging.getLogger(__name__)


class RoleEditor(AutoHelpEmbed, VerticalTextViewer, MessageableEmbed):
    _flat_perms: List[Tuple[str, bool]]

    def __init__(self, channel: TextChannel, *,
                 perm_manager: PermManager,
                 role: Role,
                 bot: Client,
                 user: Optional[User],
                 message: Message = None,
                 delete_msgs: bool = True,
                 **kwargs) -> None:
        super().__init__(channel, bot=bot, user=user, message=message, delete_msgs=delete_msgs, **kwargs)

        self.perm_manager = perm_manager
        self.role = role

    @property
    def help_title(self) -> str:
        return "Role Editor"

    @property
    def help_description(self) -> str:
        return "Edit your favourite role today for just $9.99."

    @property
    def embed_frame(self) -> Embed:
        embed = Embed(title=self.role.name, colour=Colour.blue())
        embed.add_field(name="Description", value=self.role.description or "No Description")
        embed.add_field(name="Inherits", value=", ".join(base.name for base in self.role.bases) or "No bases")

        embed.set_footer(text=f"id: {self.role.absolute_role_id}")

        if self.error:
            embed.colour = Colour.red()
            embed.add_field(name="Error", value=f"**{self.error}**", inline=False)
            self.error = None

        return embed

    @property
    def flat_permissions(self) -> List[Tuple[str, bool]]:
        try:
            return self._flat_perms
        except AttributeError:
            self._flat_perms = sorted(self.role.flat_permissions.items())
            return self._flat_perms

    @flat_permissions.setter
    def flat_permissions(self, _) -> None:
        del self._flat_perms

    @property
    def total_lines(self) -> int:
        return len(self.flat_permissions)

    async def get_line(self, line: int) -> str:
        table = {True: "🗸", False: "⨯"}
        key, value = self.flat_permissions[line]
        return f"{table[value]} {key}"

    async def on_command_error(self, ctx: Optional[Context], exception: Exception):
        await super().on_command_error(ctx, exception)
        await self.show_window()

    async def on_emoji_handler_error(self, error: Exception, *args) -> None:
        await self.on_command_error(None, error)

    async def find_role(self, ctx: Context, role: str) -> Role:
        kwargs = dict(guild_id=ctx.guild.id if ctx.guild else None, match_global=self.role.is_global or None)
        _role = await self.perm_manager.get_role(role, **kwargs) or await self.perm_manager.search_role(role, **kwargs)
        if not _role:
            raise commands.CommandError(f"Couldn't find role {role}")
        return _role

    async def check_role(self) -> List[str]:
        missing: List[str] = []

        roles = await self.perm_manager.find_roles(dict(name=self.role.name), guild_id=self.role.guild_id, match_global=self.role.is_global)
        for role in roles:
            if role != self.role:
                missing.append("**role name already exists**")
                break

        if not self.flat_permissions:
            missing.append("no permissions set")

        return missing

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_) -> bool:
        """Close and save"""
        missing = await self.check_role()
        if missing:
            raise commands.CommandError(text_utils.fluid_list_join(missing))

        return await self.perm_manager.save_role(self.role)

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Close without saving"""
        self.stop_listener()
        return None

    @commands.command("description", aliases=["describe"])
    async def set_description(self, _, *, description: str) -> None:
        """Set the description"""
        self.role.description = description
        await self.show_window()

    @commands.command("members", aliases=["targets"])
    async def show_members(self, ctx: Context) -> None:
        """Show members of role"""
        pass

    @commands.command("grant", aliases=["allow"])
    async def grant_permission(self, _, permission: str) -> None:
        """Grant a permission"""
        if not perm_tree.has(permission):
            raise commands.CommandError(f"`{permission}` doesn't exist!")

        self.role.set_perm(permission, True)
        self.flat_permissions = None
        await self.show_window()

    @commands.command("deny", aliases=["revoke"])
    async def deny_permission(self, _, permission: str) -> None:
        """Deny a permission"""
        if not perm_tree.has(permission):
            raise commands.CommandError(f"`{permission}` doesn't exist!")

        self.role.set_perm(permission, False)
        self.flat_permissions = None
        await self.show_window()

    @commands.command("inherit")
    async def inherit_role(self, ctx: Context, *, role: str) -> None:
        """Add base to role"""
        role = await self.find_role(ctx, role)
        if role == self.role:
            raise commands.CommandError("Cannot inherit from the same role...")

        self.role.bases.append(role)
        self.flat_permissions = None
        await self.show_window()

    @commands.command("removebase", aliases=["rmbase", "uninherit"])
    async def remove_base(self, _, *, role: str) -> None:
        """Remove base from role"""
        base = None
        similarity = 0
        for _base in self.role.bases:
            if _base.role_id == role:
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

        self.role.bases.remove(base)
        self.flat_permissions = None
        await self.show_window()
