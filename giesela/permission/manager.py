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
        self._perm_roles_coll = config.mongodb[config.app.mongodb.collections.perm_roles]

        self._loaded = False

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    async def load(self) -> None:
        log.info("loading permissions")
        loader = await self.get_perm_loader()
        if not loader:
            loader = PermLoader.load(self._config.app.files.permissions)

        await loader.dump(self._redis)

        self._loaded = True

    async def ensure_loaded(self) -> None:
        if not self._loaded:
            await self.load()

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
        return await PermLoader.load_db(self._perm_roles_coll)

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
