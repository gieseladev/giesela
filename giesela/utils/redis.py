import hashlib
import logging

from aioredis import Redis, ReplyError

__all__ = ["RedisCode"]

log = logging.getLogger(__name__)


class RedisCode:
    def __init__(self, code: bytes):
        self.code = code
        self._code_hash = None

    def __repr__(self) -> str:
        return self.code.decode()

    def __str__(self) -> str:
        return f"RedisCode {self.code_hash}"

    @property
    def code_hash(self) -> str:
        if not self._code_hash:
            self._code_hash = hashlib.sha1(self.code).hexdigest()

        return self._code_hash

    async def force_load(self, redis: Redis):
        self._code_hash = await redis.script_load(self.code)

    async def eval(self, redis: Redis, *, args: list = None, keys: list = None):
        args = args or []
        keys = keys or []

        try:
            return await redis.evalsha(self.code_hash, keys=keys, args=args)
        except ReplyError:
            log.debug(f"{self} not cached in redis!")
            return await redis.eval(self.code, keys=keys, args=args)
