import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from aioredis import Redis
from motor.core import AgnosticCollection
from motor.motor_asyncio import AsyncIOMotorClient

from .app import Application
from .errors import ConfigError
from .guild import _AsyncGuild
from .utils import *

log = logging.getLogger(__name__)


class FlattenProxy:
    def __init__(self, config, key: List[str] = None):
        self._config = config
        self._key = key or []

    def __await__(self):
        return self.resolve().__await__()

    def __getattr__(self, item: str):
        self._key.append(item)
        return self

    def get_key(self) -> str:
        return ".".join(self._key)

    async def resolve(self):
        key = self.get_key()
        return await self._config.get(key)

    async def set(self, value):
        key = self.get_key()
        await self._config.set(key, value)


class GuildConfig(_AsyncGuild):
    def __init__(self, guild_id: int, redis: Redis, config_coll: AgnosticCollection):
        self.guild_id = guild_id

        self._redis = redis
        self._mongodb = config_coll

    def __getattr__(self, item):
        return FlattenProxy(self, key=[item])

    def __setattr__(self, key, value):
        raise Exception("Can't set guild config like that!")

    async def dump_to_redis(self, document: Dict[str, Any]):
        redis_document = to_redis(document)
        log.debug(f"writing to redis: {redis_document}")
        await self._redis.mset(*redis_document.items())

    async def set(self, key: str, value):
        # TODO should maybe run some value checks?

        mongodb_update = self._mongodb.update_one(dict(_id=self.guild_id), {"$set": {key: value}}, upsert=True)
        redis_update = self._redis.set(key, value)

        await asyncio.gather(mongodb_update, redis_update)

    async def get(self, key: str):
        value = await self._redis.get(key)
        return from_redis(value)


class Config:
    app: Application
    guilds: Dict[int, GuildConfig]

    def __init__(self, app: Application):
        self.app = app
        self.mongo_client = AsyncIOMotorClient(self.app.mongodb.uri)
        self.redis = None  # TODO create

        self.mongodb = self.mongo_client[self.app.mongodb.database]

        self.guilds = None

    @property
    def loaded_guild_config(self) -> bool:
        return self.guilds is not None

    @classmethod
    def load(cls, fp: Union[str, Path]):
        if isinstance(fp, str):
            fp = Path(fp)

        raw_config = {}

        if fp.is_file():
            text = fp.read_text()
            raw_config = lower_data(yaml.safe_load(text))

        env_config = lower_data(get_env_config())

        # environment config takes precedence over yaml config
        depth_update(raw_config, env_config)

        app = Application.from_config(raw_config)
        return cls(app)

    async def load_guild_config(self):
        guilds = {}

        config_coll = self.mongodb.guild_config

        tasks = []

        async for guild_config in config_coll.find():
            guild_id = guild_config["id"]
            guild = GuildConfig(guild_id, self.redis, config_coll)
            tasks.append(guild.dump_to_redis(guild_config))

            guilds[guild_id] = guild

        await asyncio.wait(tasks)

        self.guilds = guilds

    def get_guild(self, guild_id: int) -> GuildConfig:
        if not self.loaded_guild_config:
            raise ConfigError("Guild configurations haven't been loaded yet!")

        if guild_id not in self.guilds:
            # TODO check mongodb first
            self.guilds[guild_id] = GuildConfig()
        return self.guilds[guild_id]
