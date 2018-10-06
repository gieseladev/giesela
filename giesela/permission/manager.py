import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import yaml
from aioredis import Redis
from discord import Member, Role, User
from pymongo import IndexModel

from giesela import Config, Giesela, utils
from .loader import PermRole, RoleTarget

log = logging.getLogger(__name__)

# language=lua
REDIS_RETURN_FIRST = utils.RedisCode(b"""
for _, key in ipairs(KEYS) do
    local perm = redis.call("GET", key)
    if perm then return perm end
end
""")

# language=lua
REDIS_HAS_PERMISSION = utils.RedisCode(b"""
local prefix = ARGV[1]
local perm = ARGV[2]

for _, target in ipairs(KEYS) do
    local roles = redis.call("LRANGE", prefix .. ":targets:" .. target, 0, -1)

    if roles then
        for _, role in ipairs(roles) do
            local perm_key = prefix .. ":roles:" .. role .. ":" .. perm
            local has_perm = redis.call("GET", perm_key)
            
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
    IndexModel([("name", "text")], name="role name search", unique=True)
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
        roles = await self.get_all_roles()

        if roles:
            await self._dump(roles)
        else:
            await self.load_from_file()

    async def load_from_file(self) -> None:
        with open(self._config.app.files.permissions, "r") as fp:
            data = yaml.safe_load(fp)

        _roles = data["roles"]
        roles = list(map(PermRole.load, _roles))

        for i, role in enumerate(roles):
            role.position = i

        documents = [role.to_dict() for role in roles]

        await self._perm_roles_coll.delete_many({})

        await asyncio.gather(
            self._dump(roles),
            self._perm_roles_coll.insert_many(documents, ordered=False)
        )

    async def search_role_gen(self, query: str, guild_id: int = None, is_global: bool = None) -> AsyncIterator["PermRole"]:
        query = {"$text": {"$search": query}}

        if guild_id:
            query["guild_id"] = guild_id
        if is_global is not None:
            query["global"] = is_global

        cursor = self._perm_roles_coll.find(query,
                                            projection=dict(score={"$meta": "textScore"}),
                                            sort=[("score", {"$meta": "textScore"}), ("position", 1)])

        async for document in cursor:
            role = PermRole.load(document)
            yield role

    async def search_role(self, query: str, guild_id: int = None, is_global: bool = None) -> Optional["PermRole"]:
        async for role in self.search_role_gen(query, guild_id, is_global):
            return role

        return None

    async def get_role(self, role_id: str) -> Optional["PermRole"]:
        return await PermRole.get(self._perm_roles_coll, role_id)

    async def find_roles(self, query: Optional[Dict[str, Any]], guild_id: int = None, is_global: bool = None) -> List["PermRole"]:
        query = query or {}

        if guild_id:
            query["guild_id"] = guild_id
        if is_global is not None:
            query["global"] = is_global

        documents = await self._perm_roles_coll.find(query, sort=[("position", 1)]).to_list(None)

        return list(map(PermRole.load, documents))

    async def get_all_roles(self) -> List["PermRole"]:
        return await self.find_roles(None)

    async def get_global_roles(self) -> List["PermRole"]:
        return await self.find_roles({"global": True})

    async def get_guild_roles(self, guild_id: int, is_global: bool = None) -> List["PermRole"]:
        return await self.find_roles({}, guild_id, is_global)

    async def get_roles_for(self, targets: Union[List[RoleTarget], User, Member, Role],
                            guild_id: int = None, is_global: bool = None) -> List["PermRole"]:
        if not isinstance(targets, list):
            targets = await RoleTarget.get_all(self._bot, targets)

        return await self.find_roles({"targets": {"$in": [str(target) for target in targets]}}, guild_id, is_global)

    async def has(self, user: Union[Member, User], perm: str, default: Any = False) -> bool:
        targets = list(map(str, await RoleTarget.get_all(self._bot, user)))

        log.debug(f"checking keys {targets}")
        perm = await REDIS_HAS_PERMISSION.eval(self._redis, keys=targets, args=[self._redis_prefix, perm])
        log.debug(f"got {perm}")

        if perm is not None:
            return perm == b"1"

        return default
