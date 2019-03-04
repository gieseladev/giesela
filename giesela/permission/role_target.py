import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Union, cast

from discord import Client, Member, Role, User
from discord.ext.commands.bot import BotBase

from .role import RoleOrderValue

__all__ = ["RoleTargetType", "RoleTarget", "get_role_targets_for", "sort_targets_by_specificity", "Target"]

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

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, RoleTarget):
            return self._target == other._target
        else:
            return NotImplemented

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
    def guild_specific(self) -> bool:
        return self.has_guild_id

    @property
    def guild_context(self) -> bool:
        return self.has_guild_id or (self.is_special and self.special_name in GUILD_CONTEXT_ROLE_TARGETS)

    @property
    def guild_id(self) -> int:
        if self.is_user:
            raise TypeError("Users aren't associated with a guild!")

        try:
            target, _ = self._target.split(GUILD_SPLIT, 1)
        except ValueError:
            raise TypeError(f"{self} isn't associated with a guild")

        try:
            return int(target)
        except ValueError:
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
            return None

        if self.is_role:
            guild = bot.get_guild(self.guild_id)
            return guild.get_role(self.id) if guild else None
        elif self.is_member:
            guild = bot.get_guild(self.guild_id)
            return guild.get_member(self.id) if guild else None
        elif self.is_user:
            return bot.get_user(self.id)
        else:
            return None


__special_target_value_table: Dict[str, int] = {
    "owner": 0,
    "guild_owner": 2,
    "guild_admin": 3,
    "everyone": 6,
}


def sort_targets_by_specificity(targets: Iterable[RoleTarget]) -> List[RoleTarget]:
    """Sort targets by specificity.

    Order:
        0. #owner
        1. user
        2. #guild_owner
        3. #guild_admin
        4. member
        5. @role
        6. #everyone
    """

    def sort_key(target: RoleTarget) -> int:
        if target.is_special:
            return __special_target_value_table[target.special_name]
        elif target.is_user:
            return 1
        elif target.is_member:
            return 4
        elif target.is_role:
            return 5
        else:
            raise TypeError(f"Can't sort unknown target: {target}")

    return sorted(targets, key=sort_key)


async def get_role_targets_for(bot: BotBase, target: RoleTargetType, *, global_only: bool = False, guild_only: bool = False) -> List[RoleTarget]:
    """Get all role targets the provided target belongs to."""
    targets: List[RoleTarget] = []

    if isinstance(target, Role):
        if not global_only:
            if target.permissions.administrator:
                # targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}guild_admin"))
                targets.append(RoleTarget("#guild_admin"))

            targets.append(RoleTarget(target))
    else:
        if not guild_only:
            if await bot.is_owner(target):
                targets.append(RoleTarget("#owner"))

            targets.append(RoleTarget(str(target.id)))

        if not global_only and isinstance(target, Member):
            targets.append(RoleTarget(target))

            if target.guild.owner == target:
                # targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}guild_owner"))
                targets.append(RoleTarget("#guild_owner"))

            for role in reversed(target.roles):
                role = cast(Role, role)
                targets.extend(await get_role_targets_for(bot, role))

            # targets.append(RoleTarget(f"#{target.guild.id}{GUILD_SPLIT}everyone"))

        if not guild_only:
            targets.append(RoleTarget("#everyone"))

    return targets


# noinspection PyUnresolvedReferences
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
