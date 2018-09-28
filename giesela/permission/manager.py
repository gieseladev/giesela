import logging
from typing import Any, List, Optional, Union

from aioredis import Redis
from discord import Member, Role, User

from giesela import Config, utils
from .loader import LoadedRole, PermLoader

log = logging.getLogger(__name__)

# language=lua
REDIS_RETURN_FIRST = utils.RedisCode(b"""
for _, key in ipairs(KEYS) do
    local perm = redis.call("get", key)
    if perm then return perm end
end
""")


class PermManager:
    _config: Config

    def __init__(self, config: Config) -> None:
        self._config = config
        self._permission_coll = config.mongodb[config.app.mongodb.collections.permissions]

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    def _prefix_key(self, key: str) -> str:
        prefix = self._config.app.redis.namespaces.permissions
        return f"{prefix}:{key}"

    async def has(self, user: Union[Member, User], perm: str, default: Any = False) -> bool:
        keys = [f"RUNTIME:u:{user.id}:{perm}"]

        if isinstance(user, Member):
            guild_id = user.guild.id
            keys.append(f"{guild_id}:u:{user.id}:{perm}")
            keys.extend(f"{guild_id}:r:{role.id}:{perm}" for role in reversed(user.roles))

        prefixed_keys = list(map(self._prefix_key, keys))
        log.debug(f"checking keys {prefixed_keys}")
        perm = await REDIS_RETURN_FIRST.eval(self._redis, keys=prefixed_keys)
        log.debug(f"got {perm}")

        if perm is not None:
            return perm == b"1"

        return default

    async def get_perm_loader(self) -> PermLoader:
        return await PermLoader.load_db(self._permission_coll)

    async def get_roles(self) -> List[LoadedRole]:
        loader = await self.get_perm_loader()
        return loader.roles

    async def get_role(self, role_id: str) -> Optional[LoadedRole]:
        for role in await self.get_roles():
            if role.role_id == role_id:
                return role

        return None

    async def roles_with_permission(self, perm: str) -> List[LoadedRole]:
        roles = []

        for role in await self.get_roles():
            if role.has(perm):
                roles.append(role)

        return roles

    async def assign_role(self, target: Union[Member, Role], role_id: str):
        pass
