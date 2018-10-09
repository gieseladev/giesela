import asyncio
import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Pattern, Union

from aioredis import Redis
from discord import Client, Member, Role, User
from discord.ext.commands.bot import BotBase
from motor.motor_asyncio import AsyncIOMotorCollection

from .errors import PermissionFileError
from .tree import perm_tree

__all__ = ["RoleTarget", "PermRole"]

log = logging.getLogger(__name__)

RE_ILLEGAL_ROLE_ID_CHAR: Pattern = re.compile(r"([^a-zA-Z0-9\-_])")

RoleTargetType = Union[User, Member, Role]


def resolve_permission_selector(selector: Dict[str, str]) -> List[str]:
    target = perm_tree

    match = selector.get("match")
    if match:
        return target.match(match)

    raise Exception(f"Unknown permission selector {selector}")


def specify_permission(perms: Dict[str, bool], targets: Union[Iterable[Union[str, Dict[str, str]]], None], grant: bool) -> None:
    if not targets:
        return None

    _targets = list(targets)

    while _targets:
        target = _targets.pop()
        if isinstance(target, dict):
            _targets.extend(resolve_permission_selector(target))
            continue

        if not perm_tree.has(target):
            raise PermissionFileError(f"Permission \"{target}\" doesn't exist!")

        perms[target] = grant


def check_permissions(targets: Optional[Iterable[Union[Dict[str, Any], str]]], ignore_errors: bool = True) -> List[Union[Dict[str, Any], str]]:
    perms = []

    if not targets:
        return perms

    for target in targets:
        if isinstance(target, dict):
            try:
                resolve_permission_selector(target)
            except Exception:
                if ignore_errors:
                    log.exception("Invalid permission selector")
                else:
                    raise
            else:
                perms.append(target)

        elif isinstance(target, str):
            if perm_tree.has(target):
                perms.append(target)
            else:
                if ignore_errors:
                    log.warning(f"permission \"{target}\" doesn't exist")
                    continue
                else:
                    raise PermissionFileError(f"Permission \"{target}\" doesn't exist!")
        else:
            if ignore_errors:
                log.warning(f"unknown target type \"{target}\"")
            else:
                raise PermissionFileError(f"Permission target {type(target)} unknown")

    return perms


SPECIAL_ROLE_TARGETS = {"owner", "guild_owner", "guild_admin", "everyone"}

GUILD_SPLIT = ":"


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

        if self.is_special:
            if self.special_name not in SPECIAL_ROLE_TARGETS:
                raise ValueError(f"Special target {self.special_name} doesn't exist")

    def __repr__(self) -> str:
        return f"RoleTarget {self._target}"

    def __str__(self) -> str:
        return self._target

    @property
    def is_role(self) -> bool:
        return self._target.startswith("@")

    @property
    def is_user(self) -> bool:
        return self._target.isnumeric()

    @property
    def is_member(self) -> bool:
        if GUILD_SPLIT in self._target:
            return all(x.isnumeric() for x in self._target.split(GUILD_SPLIT, 1))
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
    def guild_id(self) -> int:
        if self.is_user:
            raise TypeError("Users aren't associated with a guild!")

        target, _ = self._target.split(GUILD_SPLIT, 1)
        return int(target[1:])

    @classmethod
    async def get_all(cls, bot: BotBase, target: Union[User, Member, Role], *, global_only: bool = False) -> List["RoleTarget"]:
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
                    targets.extend(await cls.get_all(bot, role))

            targets.append(RoleTarget("#everyone"))

        return targets

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


class PermRole:
    _base_ids = List[str]

    targets: List[RoleTarget]
    grant: List[Union[Dict[str, Any], str]]
    deny: List[Union[Dict[str, Any], str]]
    bases: List["PermRole"]

    def __init__(self, *, role_id: str, name: str, position: Optional[int],
                 description: str = None,
                 guild_id: int = None,
                 is_global: bool = False,
                 targets: List[Union[str, RoleTargetType]] = None,
                 base_ids: List[str] = None,
                 bases: List["PermRole"] = None,
                 grant: List[Union[Dict[str, Any], str]] = None,
                 deny: List[Union[Dict[str, Any], str]] = None) -> None:

        match = RE_ILLEGAL_ROLE_ID_CHAR.search(role_id)
        if match:
            char = match.string
            raise PermissionFileError(f"Role {name} has an id which contains an illegal character: \"{char}\"! "
                                      f"Ids may only contain alphanumeric characters including \"-\", \"_\"")

        self.role_id = role_id
        self.name = name
        self.description = description
        self.position = position

        self.is_global = is_global
        if is_global:
            self.guild_id = None
        else:
            self.guild_id = guild_id

        self.targets = [RoleTarget(target) if not isinstance(target, RoleTarget) else target for target in targets] if targets else []
        self._base_ids = base_ids or []

        self.grant = grant or {}
        self.deny = deny or {}

        self.bases = bases or []

    def __repr__(self) -> str:
        return f"Role {self.absolute_role_id}: {self.name}"

    def __str__(self) -> str:
        return self.name

    def __gt__(self, other: "PermRole") -> bool:
        if isinstance(other, PermRole):
            return self.position < other.position
        return NotImplemented

    def __lt__(self, other: "PermRole") -> bool:
        if isinstance(other, PermRole):
            return self.position > other.position
        return NotImplemented

    @property
    def absolute_role_id(self) -> str:
        if self.guild_id:
            return f"{self.guild_id}:{self.role_id}"
        return self.role_id

    @property
    def base_ids(self) -> List[str]:
        if self.bases:
            return [role.absolute_role_id for role in self.bases]

        return self._base_ids

    @property
    def permissions(self) -> Dict[str, bool]:
        permissions = {}
        specify_permission(permissions, self.grant, True)
        specify_permission(permissions, self.deny, False)
        return permissions

    @property
    def permission_tree(self) -> List[Dict[str, bool]]:
        tree = [self.permissions]
        for role in self.bases:
            tree.extend(role.permission_tree)
        return tree

    @classmethod
    def load(cls, data: Dict[str, Any], *, ignore_errors: bool = True) -> "PermRole":
        base_ids: Optional[List[Union[str, Dict[str, Any]]]] = data.get("bases") or data.get("base")
        bases: List[PermRole] = []

        if base_ids:
            if not isinstance(base_ids, list):
                base_ids = [base_ids]

            for i, base in enumerate(reversed(base_ids), 1):
                if isinstance(base, dict):
                    base = cls.load(base)
                    bases.append(base)

                    del base_ids[-i]

        grant = check_permissions(data.get("grant"), ignore_errors=ignore_errors)
        deny = check_permissions(data.get("deny"), ignore_errors=ignore_errors)

        targets = data.get("targets") or []

        if targets and not isinstance(targets, list):
            targets = [targets]

        role_id = data.get("role_id") or data.get("id") or uuid.uuid4().hex
        description = data.get("description")
        guild_id = data.get("guild_id")
        is_global = data.get("global", False)
        position = data.get("position")

        return cls(role_id=str(role_id), name=str(data["name"]), position=position, description=description, guild_id=guild_id, is_global=is_global,
                   targets=targets, base_ids=base_ids, bases=bases, grant=grant, deny=deny)

    def is_explicit(self, key: str, *, bubble: bool = True) -> bool:
        key = str(key)

        explicit = self.permissions.get(key) is not None

        if explicit:
            return True
        elif bubble:
            return next((True for role in self.bases if role.is_explicit(key)), False)
        else:
            return False

    def has(self, key: str, default: Any = False, *, bubble: bool = True) -> bool:
        key = str(key)

        if key in self.permissions:
            return self.permissions[key]

        elif bubble:
            for role in self.bases:
                perm = role.has(key, default=None)
                if perm is not None:
                    return perm

        prepared_perms = perm_tree.prepare_permissions(self.permission_tree)  # FIXME this doesn't return the same as redis!
        if key in prepared_perms:
            return prepared_perms[key]

        return default

    def has_base(self, role_id: str) -> bool:
        return role_id in self.base_ids

    def load_bases(self, bases: Mapping[str, "PermRole"]) -> None:
        for base_id in self.base_ids:
            self.bases.append(bases[base_id])

    def to_dict(self) -> Dict[str, Any]:
        data = dict(_id=self.absolute_role_id, role_id=self.role_id, name=self.name, position=self.position, guild_id=self.guild_id,
                    bases=self.base_ids, grant=self.grant, deny=self.deny, targets=[str(target) for target in self.targets])

        data["global"] = self.is_global

        return data

    async def _dump_roles_redis(self, redis: Redis, prefix: str) -> None:
        prefix = f"{prefix}:roles:{self.absolute_role_id}"
        # noinspection PyTypeChecker
        prepared_perms = perm_tree.unfold_perms(self.permissions.items())

        for key, value in prepared_perms.items():
            # noinspection PyTypeChecker
            prepared_perms[key] = int(value)

        if prepared_perms:
            await redis.hmset_dict(prefix, prepared_perms)

    async def _dump_targets_redis(self, redis: Redis, prefix: str) -> None:
        prefix = f"{prefix}:targets"

        coros = []

        for target in self.targets:
            abs_key = f"{prefix}:{target}"
            coros.append(redis.rpush(abs_key, self.absolute_role_id, *self.base_ids))

        if coros:
            await asyncio.gather(*coros)

    async def dump_to_redis(self, redis: Redis, prefix: str) -> None:
        await asyncio.gather(
            self._dump_roles_redis(redis, prefix),
            self._dump_targets_redis(redis, prefix)
        )

    async def dump_to_mongo(self, collection: AsyncIOMotorCollection) -> None:
        document = self.to_dict()
        await collection.insert_one(document)

    async def save(self, redis: Redis, prefix: str, collection: AsyncIOMotorCollection) -> None:
        await asyncio.gather(
            self.dump_to_mongo(collection),
            self.dump_to_redis(redis, prefix)
        )
