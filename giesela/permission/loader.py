import asyncio
import itertools
import logging
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Pattern, Union

from aioredis import Redis
from discord import Client, Member, Role, User
from discord.ext.commands.bot import BotBase
from motor.motor_asyncio import AsyncIOMotorCollection

from .errors import PermissionFileError
from .tree import perm_tree

__all__ = ["RoleTarget", "PermRole"]

log = logging.getLogger(__name__)

RE_ILLEGAL_ROLE_ID_CHAR: Pattern = re.compile(r"([^a-zA-Z0-9\-_])")

RoleTargetType = Union[User, Role]


def resolve_permission_selector(selector: Dict[str, str]) -> List[str]:
    target = perm_tree

    match = selector.get("match")
    if match:
        return target.match(match)

    raise Exception(f"Unknown permission selector {selector}")


def specify_permission(perms: Dict[str, bool], targets: Union[Iterable[str], Dict[str, str], None], grant: bool) -> None:
    if not targets:
        return None

    if isinstance(targets, dict):
        targets = resolve_permission_selector(targets)

    for target in targets:
        if not perm_tree.has(target):
            raise PermissionFileError(f"Permission \"{target}\" doesn't exist!")

        perms[target] = grant


SPECIAL_ROLE_TARGETS = {"owner", "guild_owner", "guild_admin", "everyone"}


class RoleTarget:
    def __init__(self, target: Union[str, RoleTargetType]) -> None:
        if isinstance(target, Role):
            self._target = f"@{target.guild.id}-{target.id}"
        elif isinstance(target, (User, Member)):
            self._target = str(target.id)
        else:
            self._target = target

        if self.is_special:
            if self.special_name not in SPECIAL_ROLE_TARGETS:
                raise ValueError(f"Special target {self.special_name} doesn't exist")

    def __repr__(self) -> str:
        return self._target

    @property
    def is_role(self) -> bool:
        return self._target.startswith("@")

    @property
    def is_user(self) -> bool:
        return not self.is_role

    @property
    def is_special(self) -> bool:
        return self._target.startswith("#")

    @property
    def special_name(self) -> str:
        if not self.is_special:
            raise TypeError(f"{self} isn't special")
        try:
            return self._target.rsplit("-", 1)[1]
        except IndexError:
            return self._target[1:]

    @property
    def id(self) -> int:
        if self.is_special:
            raise TypeError("Special targets don't have an id")

        if self.is_role:
            _, target = self._target.rsplit("-", 1)
        else:
            target = self._target

        return int(target)

    @property
    def guild_id(self) -> int:
        if not (self.is_role or self.is_special):
            raise TypeError("Users aren't associated with a guild!")

        target, _ = self._target.split("-", 1)
        return int(target[1:])

    @classmethod
    async def get_all(cls, bot: BotBase, target: Union[User, Member, Role]) -> List["RoleTarget"]:
        targets: List[RoleTarget] = []

        if isinstance(target, Role):
            if target.permissions.administrator:
                targets.extend((RoleTarget(f"#{target.guild.id}-guild_admin"), RoleTarget("#guild_admin")))

            targets.append(RoleTarget(target))
        else:
            if await bot.is_owner(target):
                targets.append(RoleTarget("#owner"))

            targets.append(RoleTarget(target))

            if isinstance(target, Member):
                if target.guild.owner == target:
                    targets.extend((RoleTarget(f"#{target.guild.id}-guild_owner"), RoleTarget("#guild_owner")))

                for role in reversed(target.roles):
                    targets.extend(await cls.get_all(bot, role))

            targets.append(RoleTarget("#everyone"))

            log.debug(f"targets for {target}: {targets}")

        return targets

    def resolve(self, bot: Client) -> Optional[RoleTargetType]:
        if self.is_special:
            raise TypeError("Special targets can't be resolved")

        if self.is_role:
            guild = bot.get_guild(self.guild_id)
            return guild.get_role(self.id) if guild else None
        else:
            return bot.get_user(self.id)


class PermRole:
    _base_ids = List[str]

    targets: List[RoleTarget]
    permissions: Dict[str, bool]
    bases: List["PermRole"]

    def __init__(self, *, role_id: str, role_name: str, position: Optional[int],
                 guild_id: int = None,
                 targets: List[Union[str, RoleTargetType]] = None,
                 base_ids: List[str] = None,
                 bases: List["PermRole"] = None,
                 permissions: Dict[str, bool] = None) -> None:

        match = RE_ILLEGAL_ROLE_ID_CHAR.search(role_id)
        if match:
            char = match.string
            raise PermissionFileError(f"Role {role_name} has an id which contains an illegal character: \"{char}\"! "
                                      f"Ids may only contain alphanumeric characters including \"-\", \"_\"")

        self.role_id = role_id
        self.role_name = role_name
        self.position = position
        self.guild_id = guild_id

        self.targets = [RoleTarget(target) if not isinstance(target, RoleTarget) else target for target in targets] if targets else []
        self._base_ids = base_ids or []
        self.permissions = permissions or {}

        self.bases = bases or []

    def __repr__(self) -> str:
        return f"Role {self.absolute_role_id}: {self.role_name}"

    def __str__(self) -> str:
        return self.role_name

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
    def permission_tree(self) -> List[Dict[str, bool]]:
        tree = [self.permissions]
        for role in self.bases:
            tree.extend(role.permission_tree)
        return tree

    @classmethod
    def load(cls, data: Dict[str, Any]) -> "PermRole":
        base_ids: Optional[List[Union[str, Dict[str, Any]]]] = data.get("bases") or data.get("base")
        bases: List[PermRole] = []

        if base_ids:
            if not isinstance(base_ids, list):
                base_ids = [base_ids]

            if isinstance(base_ids[0], dict):
                for base in base_ids:
                    base = cls.load(base)
                    bases.append(base)

                base_ids = None

        permissions = {}

        specify_permission(permissions, data.get("grant"), True)
        specify_permission(permissions, data.get("deny"), False)

        targets = data.get("targets") or []

        if targets and not isinstance(targets, list):
            targets = [targets]

        role_name = data["name"]
        role_id = data.get("role_id") or data.get("id") or uuid.uuid4().hex

        guild_id = data.get("guild_id")
        position = data.get("position")

        return cls(role_id=str(role_id), role_name=str(role_name), position=position, guild_id=guild_id,
                   targets=targets, base_ids=base_ids, bases=bases, permissions=permissions)

    @classmethod
    async def get(cls, collection: AsyncIOMotorCollection, role_id: str) -> Optional["PermRole"]:
        pipeline = [
            {"$match": dict(_id=role_id)},
            {"$lookup": {"from": collection.name, "localField": "bases", "foreignField": "_id", "as": "bases"}}
        ]
        cursor = collection.aggregate(pipeline)
        if not await cursor.fetch_next:
            return None

        document = cursor.next_object()
        return cls.load(document)

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

        return default

    def has_base(self, role_id: str) -> bool:
        for role in self.bases:
            if role.role_id == role_id:
                return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        grant = []
        deny = []

        for key, perm in self.permissions.items():
            if perm:
                grant.append(key)
            else:
                deny.append(key)

        data = dict(_id=self.absolute_role_id, role_id=self.role_id, name=self.role_name, position=self.position, guild_id=self.guild_id,
                    bases=self.base_ids, grant=grant, deny=deny, targets=[str(target) for target in self.targets])

        return data

    async def _dump_roles_redis(self, redis: Redis, prefix: str) -> None:
        prefix = f"{prefix}:roles:{self.absolute_role_id}"

        pairs = []

        for key, perm in self.permissions.items():
            abs_key = f"{prefix}:{key}"
            pairs.append((abs_key, int(perm)))

        if pairs:
            await redis.mset(*itertools.chain.from_iterable(pairs))

    async def _dump_targets_redis(self, redis: Redis, prefix: str) -> None:
        prefix = f"{prefix}:targets"

        coros = []

        for target in self.targets:
            abs_key = f"{prefix}:{target}"
            coros.append(redis.rpush(abs_key, self.absolute_role_id))

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
