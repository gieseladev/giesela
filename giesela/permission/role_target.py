import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from discord import Client, Member, Role, User
from discord.ext.commands.bot import BotBase

from .role import RoleOrderValue

__all__ = ["RoleTargetType", "RoleTarget", "get_role_targets_for", "Target"]

log = logging.getLogger(__name__)

GUILD_CONTEXT_ROLE_TARGETS = {"guild_owner", "guild_admin"}
SPECIAL_ROLE_TARGETS = {"owner", "everyone"} | GUILD_CONTEXT_ROLE_TARGETS

GUILD_SPLIT = ":"

RoleTargetType = Union[User, Member, Role]


class RoleTarget:
    def __init__(self, target: Union[str, RoleTargetType]) -> None:
        if isinstance(target, Role):
            self._target = f"@{target.guild.id}{GUILD_SPLIT}{target.id}"
        elif isinstance(target, User):
            self._target = str(target.id)
        elif isinstance(target, Member):
            self._target = f"{target.guild.id}{GUILD_SPLIT}{target.id}"
        else:
            self._target = str(target)

    def __repr__(self) -> str:
        return f"RoleTarget {self._target}"

    def __str__(self) -> str:
        return self._target

    @property
    def is_role(self) -> bool:
        return self._target.startswith("@")

    @property
    def is_user(self) -> bool:
        return self._target.isdigit()

    @property
    def is_member(self) -> bool:
        if GUILD_SPLIT in self._target:
            return all(x.isdigit() for x in self._target.split(GUILD_SPLIT, 1))
        return False

    @property
    def is_special(self) -> bool:
        return self._target.startswith("#")

    @property
    def special_name(self) -> str:
        if not self.is_special:
            raise TypeError(f"{self} isn't special")
        try:
            return self._target.rsplit(GUILD_SPLIT, 1)[1]
        except IndexError:
            return self._target[1:]

    @property
    def id(self) -> int:
        if self.is_special:
            raise TypeError("Special targets don't have an id")

        if self.is_user:
            target = self._target
        else:
            _, target = self._target.rsplit(GUILD_SPLIT, 1)

        return int(target)

    @property
    def has_guild_id(self) -> bool:
        try:
            guild_id = self.guild_id
        except (TypeError, ValueError):
            return False
        else:
            return bool(guild_id)

    @property
    def guild_context(self) -> bool:
        return self.has_guild_id or (self.is_special and self.special_name in GUILD_CONTEXT_ROLE_TARGETS)

    @property
    def guild_id(self) -> int:
        if self.is_user:
            raise TypeError("Users aren't associated with a guild!")

        target, _ = self._target.split(GUILD_SPLIT, 1)
        return int(target[1:])

    def check(self) -> None:
        if self.is_member:
            pass
        elif self.is_role:
            pass
        elif self.is_special:
            if self.special_name not in SPECIAL_ROLE_TARGETS:
                raise ValueError(f"Special target {self.special_name} doesn't exist")
        elif self.is_user:
            pass
        else:
            raise TypeError(f"Unknown target type: {self}")

    def resolve(self, bot: Client) -> Optional[RoleTargetType]:
        if self.is_special:
            raise TypeError("Special targets can't be resolved")

        if self.is_role:
            guild = bot.get_guild(self.guild_id)
            return guild.get_role(self.id) if guild else None
        elif self.is_member:
            guild = bot.get_guild(self.guild_id)
            return guild.get_member(self.id) if guild else None
        else:
            return bot.get_user(self.id)


async def get_role_targets_for(bot: BotBase, target: RoleTargetType, *, global_only: bool = False) -> List[RoleTarget]:
    """Get all role targets the provided target belongs to."""
    targets: List[RoleTarget] = []

    if isinstance(target, Role):
        if not global_only:
            if target.permissions.administrator:
                targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}guild_admin"))
                targets.append(RoleTarget("#guild_admin"))

            targets.append(RoleTarget(target))
    else:
        if await bot.is_owner(target):
            targets.append(RoleTarget("#owner"))

        targets.append(RoleTarget(str(target.id)))

        if isinstance(target, Member) and not global_only:
            targets.append(RoleTarget(target))

            if target.guild.owner == target:
                targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}guild_owner"))
                targets.append(RoleTarget("#guild_owner"))

            for role in reversed(target.roles):
                targets.extend(await get_role_targets_for(bot, role))

            targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}everyone"))

        targets.append(RoleTarget("#everyone"))

    return targets


@dataclass
class Target:
    """Represents the mapping from `RoleTarget` to `Role`.

    Attributes:
        role_ids: **UNSORTED** list of roles that belong to this target.
    """
    _id: str
    role_ids: List[str]

    @property
    def role_target(self) -> RoleTarget:
        return RoleTarget(self._id)

    @property
    def target_id(self) -> str:
        return self._id

    def sort_roles(self, sort_map: Dict[str, RoleOrderValue]) -> None:
        """Sort the role_ids to reflect the actual order"""
        self.role_ids.sort(key=lambda role_id: sort_map[role_id])
