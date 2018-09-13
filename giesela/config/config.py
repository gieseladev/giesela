import abc
import asyncio
import itertools
import logging
import rapidjson
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

import aioredis
import yaml
from aioredis import Redis
# noinspection PyProtectedMember
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from . import abstract
from .app import Application
from .errors import ConfigError, TraverseError
from .guild import Guild, _AsyncGuild
from .runtime import Runtime, _AsyncRuntime
from .utils import *

log = logging.getLogger(__name__)


class FlattenProxy:
    __slots__ = ("_config", "_virtual_parent", "_virtual_target", "_key")

    _virtual_parent: Optional[Type[abstract.ConfigObject]]
    _virtual_target: Type[abstract.ConfigObject]
    _key: List[str]

    def __init__(self, config: "_RedisConfig", key: List[str] = None):
        self._config = config
        self._virtual_parent = None
        self._virtual_target = config.PROXY
        self._key = []

        if key:
            self.traverse(*key)

        # TODO handle lists by converting them to dictionaries and using __getitem__ hook

    def __await__(self):
        return self.resolve().__await__()

    def __getattr__(self, item: str):
        return self.traverse(*item.split("."))

    def traverse(self, *keys: str):
        parent = self._virtual_target
        for i, key in enumerate(keys[:-1]):
            try:
                parent = parent[key]
            except KeyError:
                parent_key = ".".join((*self._key, *keys[:i]))
                raise TraverseError("{key} doesn't have {target}", parent_key, key)

        self._virtual_parent = parent
        key = keys[-1]

        try:
            self._virtual_target = self._virtual_parent[key]
        except KeyError:
            parent = [*self._key, *keys[:-1]]
            raise TraverseError("{key} doesn't have {target}", ".".join(parent), key)

        self._key.extend(keys)
        return self

    def get_qualified_key(self) -> str:
        return ".".join(self._key)

    async def resolve(self):
        key = self.get_qualified_key()
        return await self._config.get(key)

    async def set(self, value):
        key = self.get_qualified_key()

        if not self._virtual_parent or isinstance(self._virtual_target, abstract.ConfigObject):
            raise KeyError(f"Cannot set {key}! It's a config object!")

        cls = abstract.config_type(self._virtual_parent, self._key[-1])
        try:
            value = abstract.convert(value, cls)
        except ConfigError as e:
            e.trace_key(key)
            raise e

        config = self._config

        config_id = config._id
        log.debug(f"{config_id} setting {key} to {value}")

        mongodb_update = config._mongodb.update_one(dict(_id=config._id), {"$set": {key: value}}, upsert=True)
        redis_update = config._redis.set(config._prefix_key(key), rapidjson.dumps(value))

        await asyncio.gather(mongodb_update, redis_update)

    async def reset(self):
        key = self.get_qualified_key()

        if not self._virtual_parent or isinstance(self._virtual_target, abstract.ConfigObject):
            raise KeyError(f"Cannot set {key}! It's a config object!")

        config_id = self._config._id
        log.debug(f"{config_id} resetting {key}")

        await self._config._reset(key)


class _RedisConfig(metaclass=abc.ABCMeta):
    PROXY: Type[abstract.ConfigObject]

    __slots__ = ("_id", "_redis", "_prefix", "_mongodb")

    def __init__(self, *, _id: Any, redis: Redis, prefix: str, config_coll: AsyncIOMotorCollection):
        self._id = _id

        self._redis = redis
        self._prefix = f"{prefix}:{_id}:"
        self._mongodb = config_coll

    def __getattr__(self, item):
        return FlattenProxy(self, key=item.split("."))

    def _prefix_key(self, key: str) -> str:
        return self._prefix + key

    async def dump_to_redis(self, document: Dict[str, Any]):
        redis_document = to_redis(document, self._prefix)
        if not redis_document:
            return

        log.debug(f"writing to redis: {redis_document}")
        args = itertools.chain.from_iterable(redis_document.items())

        await self._redis.mset(*args)

    async def remove(self):
        await self._mongodb.delete_one(dict(_id=self._id))

    async def set(self, key: str, value):
        proxy = FlattenProxy(self, key.split("."))
        await proxy.set(value)

    async def reset(self, key: str):
        proxy = FlattenProxy(self, key.split("."))
        await proxy.reset()

    async def _reset(self, key: str):
        await asyncio.gather(self._mongodb.update_one(dict(_id=self._id), {"$unset": {key: True}}),
                             self._redis.delete(self._prefix_key(key)))

    @abc.abstractmethod
    async def load(self) -> abstract.ConfigObject:
        pass

    async def handle_nil_value(self, key: str):
        raise AttributeError(f"{key} doesn't exist")

    async def get(self, key: str):
        prefixed_key = self._prefix_key(key)
        log.debug(f"getting from redis {prefixed_key}")
        value = await self._redis.get(prefixed_key)
        if value is None:
            log.debug(f"key not in redis, using nil handler {key}")
            return await self.handle_nil_value(key)

        return rapidjson.loads(value)


class RuntimeConfig(_RedisConfig, _AsyncRuntime):
    PROXY = Runtime

    __slots__ = ("default",)

    def __init__(self, default: Runtime, **kwargs):
        super().__init__(**kwargs)
        self.default = default

    async def dump_to_redis(self, document: Dict[str, Any]):
        data = abstract.config_dict(self.default)
        data.update(document)
        await super().dump_to_redis(data)

    async def _reset(self, key: str):
        # delete the value from mongodb but set it to the default in redis!
        value = abstract.traverse_config(self.default, key)

        await asyncio.gather(self._mongodb.update_one(dict(_id=self._id), {"$unset": {key: True}}),
                             self._redis.set(self._prefix_key(key), rapidjson.dumps(value)))

    async def load(self) -> Runtime:
        log.debug("getting runtime config from mongo")
        document = await self._mongodb.find_one(self._id)
        if document:
            data = abstract.config_dict(self.default)
            data.update(document)
            return Runtime.from_config(data)
        else:
            log.debug("config didn't exist, using default")
            return self.default


class GuildConfig(_RedisConfig, _AsyncGuild):
    PROXY = Guild

    __slots__ = ("runtime",)

    def __init__(self, runtime: RuntimeConfig, **kwargs):
        super().__init__(**kwargs)
        self.runtime = runtime

    async def load(self) -> Guild:
        log.debug(f"getting guild {self._id} config from mongo")
        defaults, document = await asyncio.gather(self.runtime.load(),
                                                  self._mongodb.find_one(self._id))

        if document:
            data = abstract.config_dict(defaults.guild)
            data.update(document)
            return Guild.from_config(data)
        else:
            log.debug("not found, returning default")
            return defaults.guild

    async def handle_nil_value(self, key: str):
        return await self.runtime.get(f"guild.{key}")


class Config:
    RUNTIME_ID = "RUNTIME"

    runtime: RuntimeConfig
    guilds: Dict[int, GuildConfig]
    redis: Redis

    def __init__(self, app: Application):
        self.app = app
        self.mongo_client = AsyncIOMotorClient(self.app.mongodb.uri)
        self.redis = None

        self.mongodb = self.mongo_client[self.app.mongodb.database]
        self.config_coll = self.mongodb.config

        self.runtime = None
        self.guilds = None

    @property
    def loaded_config(self) -> bool:
        return self.guilds is not None and self.runtime is not None

    @classmethod
    def load_app(cls, fp: Union[str, Path]):
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

    async def connect_redis(self):
        log.debug("connecting to redis")
        pool = await aioredis.create_pool(self.app.redis.uri)
        self.redis = Redis(pool)

        db = self.app.redis.database
        log.debug(f"selecting database {db}")
        await self.redis.select(db)

    def _create_guild(self, guild_id: int) -> GuildConfig:
        return GuildConfig(self.runtime, _id=guild_id, redis=self.redis, prefix=self.app.redis.namespaces.config, config_coll=self.config_coll)

    async def _load_runtime(self):
        log.info("loading runtime")

        self.runtime = RuntimeConfig(self.app.runtime, _id=self.RUNTIME_ID, redis=self.redis, prefix=self.app.redis.namespaces.config,
                                     config_coll=self.config_coll)

        runtime_config = await self.config_coll.find_one(self.RUNTIME_ID)
        if runtime_config:
            del runtime_config["_id"]
            await self.runtime.dump_to_redis(runtime_config)

    async def _load_guild(self):
        log.info("loading guild")

        guilds = {}
        tasks = []

        async for guild_config in self.config_coll.find():
            guild_id = guild_config.pop("_id")
            if guild_id == self.RUNTIME_ID:
                continue

            guild = self._create_guild(guild_id)
            tasks.append(guild.dump_to_redis(guild_config))

            guilds[guild_id] = guild

        if tasks:
            await asyncio.gather(*tasks)

        self.guilds = guilds

    async def load_config(self):
        if not self.redis:
            await self.connect_redis()

        await asyncio.gather(self._load_runtime(), self._load_guild())

    async def remove_guild(self, guild_id: int):
        log.info(f"removing guild {guild_id}")
        guild = self.guilds.pop(guild_id, None)
        if guild:
            await guild.remove()

    def get_guild(self, guild_id: int) -> GuildConfig:
        if not self.loaded_config:
            raise ConfigError("Guild configurations haven't been loaded yet!")

        if guild_id not in self.guilds:
            self.guilds[guild_id] = self._create_guild(guild_id)
        return self.guilds[guild_id]
