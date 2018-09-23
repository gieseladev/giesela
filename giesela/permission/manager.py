import logging
from typing import Any, Union

from aioredis import Redis
from discord import Member, User

from giesela import Config

log = logging.getLogger(__name__)


class PermManager:
    _config: Config

    def __init__(self, config: Config):
        self._config = config

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    def _prefix_key(self, key: str) -> str:
        prefix = self._config.app.redis.namespaces.permissions
        return f"{prefix}:{key}"

    async def has(self, user: Union[Member, User], key: str, default: Any = False) -> bool:
        keys = [f"RUNTIME:u:{user.id}:{key}"]

        if isinstance(user, Member):
            guild_id = user.guild.id
            keys.append(f"{guild_id}:u:{user.id}:{key}")
            keys.extend(f"{guild_id}:r:{role.id}:{key}" for role in reversed(user.roles))

        prefixed_keys = list(map(self._prefix_key, keys))
        log.debug(f"checking keys {prefixed_keys}")

        perms = await self._redis.mget(*prefixed_keys)

        log.debug(f"got {perms}")

        for perm in perms:
            if perm is not None:
                return perm == b"1"

        return default
