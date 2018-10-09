import asyncio
import logging
import operator
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import yaml
from aioredis import Redis
from discord import Member, Role, User
from pymongo import IndexModel

from giesela import Config, Giesela, utils
from .loader import PermRole, RoleTarget

log = logging.getLogger(__name__)

# language=lua
REDIS_HAS_PERMISSION = utils.RedisCode(b"""
local prefix = ARGV[1]
local perm = ARGV[2]

for _, target in ipairs(KEYS) do
    local roles = redis.call("LRANGE", prefix .. ":targets:" .. target, 0, -1)

    if roles then
        for _, role in ipairs(roles) do
            local role_key = prefix .. ":roles:" .. role
            local has_perm = redis.call("HGET", role_key, perm)
            
            if has_perm then return has_perm end
        end
    end
end
""")

# language=lua
REDIS_DEL_NS = utils.RedisCode(b"""
redis.replicate_commands()

for _, target in ipairs(ARGV) do
    local cursor = "0"

    repeat
        local result = redis.call("SCAN", cursor, "MATCH", target)
        cursor = result[1]
        local keys = result[2]
        
        if #keys > 0 then
            redis.call("DEL", unpack(keys))
        end
    until (cursor == "0")
end
""")

PERM_ROLES_INDEXES = [
    IndexModel([("name", "text")], name="role name search"),
    IndexModel([("guild_id", 1), ("name", 1)], name="unique role name in guild", unique=True)
]


class PermManager:
    _config: Config

    def __init__(self, bot: Giesela) -> None:
        self._bot = bot
        self._config = bot.config
        self._perm_roles_coll = self._config.mongodb[self._config.app.mongodb.collections.perm_roles]

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    @property
    def _redis_prefix(self) -> str:
        return self._config.app.redis.namespaces.permissions

    async def _dump(self, roles: List[PermRole]) -> None:
        await REDIS_DEL_NS.eval(self._redis, args=[f"{self._redis_prefix}:*"])
        await asyncio.gather(*(role.dump_to_redis(self._redis, self._redis_prefix) for role in roles))

    async def load(self) -> None:
        await utils.ensure_indexes(self._perm_roles_coll, PERM_ROLES_INDEXES)

        log.info("loading permissions")
        roles = await self.get_all_roles(raw=True)

        if roles:
            await self._dump(roles)
        else:
            await self.load_from_file()

    async def load_from_file(self) -> None:
        with open(self._config.app.files.permissions, "r") as fp:
            data = yaml.safe_load(fp)

        _roles = data["roles"]
        roles = [PermRole.load(_role, ignore_errors=False) for _role in _roles]

        for i, role in enumerate(roles):
            role.position = i

        documents = [role.to_dict() for role in roles]

        await self._perm_roles_coll.delete_many({})

        await asyncio.gather(
            self._dump(roles),
            self._perm_roles_coll.insert_many(documents, ordered=False)
        )

    async def search_role_gen(self, query: str, guild_id: int = None, match_global: bool = None) -> AsyncIterator["PermRole"]:
        query = {"$text": {"$search": query}}

        if guild_id:
            query["guild_id"] = {"$in": [guild_id, None]}

        if match_global is not None:
            query["global"] = match_global

        cursor = self._perm_roles_coll.find(query,
                                            projection=dict(score={"$meta": "textScore"}),
                                            sort=[("score", {"$meta": "textScore"}), ("position", 1)])

        async for document in cursor:
            role = PermRole.load(document)
            yield role

    async def search_role(self, query: str, guild_id: int = None, match_global: bool = None) -> Optional["PermRole"]:
        async for role in self.search_role_gen(query, guild_id, match_global):
            return role

        return None

    async def find_roles(self, query: Union[Dict[str, Any], str, None], guild_id: int = None, match_global: bool = None) -> List["PermRole"]:
        if not query:
            query = {}
        elif isinstance(query, str):
            query = dict(_id=query)

        if guild_id:
            query["guild_id"] = {"$in": [guild_id, None]}

        if match_global is not None:
            query["global"] = match_global

        pipeline = [
            {"$match": query},
            {"$graphLookup": {
                "from": "perm_roles",
                "startWith": "$bases",
                "connectFromField": "bases",
                "connectToField": "_id",
                "as": "__base_hierarchy"
            }}
        ]

        cursor = self._perm_roles_coll.aggregate(pipeline)
        documents: List[Dict[str, Any]] = await cursor.to_list(None)

        roles = {}

        targets = documents.copy()
        while targets:
            target = targets.pop()
            role_id = target["_id"]
            if role_id in roles:
                continue

            base_hierarchy = target.get("__base_hierarchy")
            if base_hierarchy:
                targets.extend(base_hierarchy)

            role = PermRole.load(target)
            roles[role.role_id] = role

        for role in roles.values():
            role.load_bases(roles)

        return sorted(roles.values(), key=operator.attrgetter("position"))

    async def get_role(self, role_id: str) -> Optional["PermRole"]:
        roles = await self.find_roles(role_id)
        if roles:
            return roles[0]
        return None

    async def get_all_roles(self, raw: bool = False) -> List["PermRole"]:
        if raw:
            documents = await self._perm_roles_coll.find().to_list(None)
            return list(map(PermRole.load, documents))
        else:
            return await self.find_roles(None)

    async def get_guild_roles(self, guild_id: int, **kwargs) -> List["PermRole"]:
        return await self.find_roles(None, guild_id=guild_id, **kwargs)

    async def get_roles_for(self, targets: Union[List[RoleTarget], User, Member, Role], **kwargs) -> List["PermRole"]:
        if not isinstance(targets, list):
            targets = await RoleTarget.get_all(self._bot, targets)

        return await self.find_roles({"targets": {"$in": [str(target) for target in targets]}}, **kwargs)

    async def has(self, user: Union[Member, User], perm: str, default: Any = False, *, global_only: bool = False) -> bool:
        targets = list(map(str, await RoleTarget.get_all(self._bot, user, global_only=global_only)))

        log.debug(f"checking keys {targets}")
        perm = await REDIS_HAS_PERMISSION.eval(self._redis, keys=targets, args=[self._redis_prefix, perm])
        log.debug(f"got {perm}")

        if perm is not None:
            return perm == b"1"

        return default

    async def delete_role(self, role: Union[PermRole, str]) -> None:
        if not isinstance(role, PermRole):
            role = await self.get_role(role)

        role_id = role.absolute_role_id

        role_key = f"{self._redis_prefix}:roles:{role_id}"
        target_keys = [f"{self._redis_prefix}:targets:{target}" for target in role.targets]

        await asyncio.gather(
            self._perm_roles_coll.delete_one(dict(_id=role_id)),
            self._perm_roles_coll.update_many(dict(bases=role_id), {"$pull": dict(bases=role_id)}),
            self._redis.delete(role_key),
            *(self._redis.lrem(target_key, 0, role_id) for target_key in target_keys)
        )
