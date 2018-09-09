import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from aredis import StrictRedis
from aredis.sentinel import Sentinel
from motor.core import AgnosticCollection
from motor.motor_asyncio import AsyncIOMotorClient

from . import abstract
from .app import Application
from .errors import ConfigError, TraverseError
from .guild import Guild, _AsyncGuild
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
    __slots__ = ("guild_id", "defaults", "_redis", "_prefix", "_mongodb", "__frozen__")

    def __init__(self, guild_id: int, defaults: Guild, redis: StrictRedis, prefix: str, config_coll: AgnosticCollection):
        self.guild_id = guild_id
        self.defaults = defaults

        self._redis = redis
        self._prefix = f"{prefix}:{guild_id}:"
        self._mongodb = config_coll
        self.__frozen__ = True

    def __getattr__(self, item):
        return FlattenProxy(self, key=[item])

    def _prefix_key(self, key: str) -> str:
        return self._prefix + key

    async def dump_to_redis(self, document: Dict[str, Any]):
        redis_document = to_redis(document, self._prefix)
        log.debug(f"writing to redis: {redis_document}")
        await self._redis.mset(redis_document)

    async def remove(self):
        await self._mongodb.delete_one(dict(_id=self.guild_id))

    async def set(self, key: str, value):
        # just let the exception bubble xD
        *_parent, target = key.split(".")
        parent = abstract.traverse_config(self.defaults, _parent)
        if not isinstance(parent, abstract.ConfigObject):
            raise KeyError(f"{_parent} isn't a config object")

        try:
            _target = abstract.traverse_config(parent, target)
        except TraverseError as e:
            e.trace_key(".".join(_parent))
            raise e

        if isinstance(_target, abstract.ConfigObject):
            raise KeyError(f"Cannot set {key} as it's a config object!")

        cls = abstract.config_type(parent, target)
        try:
            value = abstract.convert(value, cls)
        except ConfigError as e:
            e.trace_key(key)
            raise e

        log.debug(f"{self.guild_id} setting {key} to {value}")

        mongodb_update = self._mongodb.update_one(dict(_id=self.guild_id), {"$set": {key: value}}, upsert=True)
        redis_update = self._redis.set(self._prefix_key(key), value)

        await asyncio.gather(mongodb_update, redis_update)

    async def load(self) -> Guild:
        document = await self._mongodb.find_one(self.guild_id)
        if document:
            data = abstract.config_dict(self.defaults)
            data.update(document)
            return Guild.from_config(data)
        else:
            # MAYBE protect from edits
            return self.defaults

    async def get(self, key: str):
        value = await self._redis.get(self._prefix_key(key))
        if value is None:
            value = abstract.traverse_config(self.defaults, key)
            if isinstance(value, abstract.ConfigObject):
                raise AttributeError(f"{key} points to a ConfigObject {value}")
            return value

        return from_redis(value)


class Config:
    app: Application
    guilds: Dict[int, GuildConfig]

    def __init__(self, app: Application):
        self.app = app
        self.mongo_client = AsyncIOMotorClient(self.app.mongodb.uri)

        sentinel = Sentinel([(sentinel.host, sentinel.port) for sentinel in self.app.redis.sentinels])
        self.redis = sentinel.master_for(self.app.redis.master)

        self.mongodb = self.mongo_client[self.app.mongodb.database]
        self.config_coll = self.mongodb.guild_config

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

    def _create_guild(self, guild_id: int) -> GuildConfig:
        return GuildConfig(guild_id, self.app.guild_defaults, self.redis, self.app.redis.databases.config, self.config_coll)

    async def load_guild_config(self):
        guilds = {}
        tasks = []

        async for guild_config in self.config_coll.find():
            guild_id = guild_config.pop("_id")
            guild = self._create_guild(guild_id)
            tasks.append(guild.dump_to_redis(guild_config))

            guilds[guild_id] = guild

        if tasks:
            await asyncio.gather(*tasks)

        self.guilds = guilds

    async def remove_guild(self, guild_id: int):
        log.info(f"removing guild {guild_id}")
        guild = self.guilds.pop(guild_id, None)
        if guild:
            await guild.remove()

    def get_guild(self, guild_id: int) -> GuildConfig:
        if not self.loaded_guild_config:
            raise ConfigError("Guild configurations haven't been loaded yet!")

        if guild_id not in self.guilds:
            self.guilds[guild_id] = self._create_guild(guild_id)
        return self.guilds[guild_id]
