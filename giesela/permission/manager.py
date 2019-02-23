import asyncio
import dataclasses
import logging
from collections import defaultdict
from itertools import chain
from typing import Any, Callable, Dict, Iterable, List, TypeVar, Union

from aioredis import Redis
from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import DeleteOne, IndexModel, InsertOne, UpdateOne

from giesela import Config, Giesela, perm_tree, utils
from .file_loader import load_from_file
from .redis_lua import REDIS_DEL_NS, REDIS_HAS_ALL_PERMISSIONS, REDIS_HAS_PERMISSION
from .role import Role, RoleOrder
from .role_target import RoleTargetType, Target, get_role_targets_for
from .tree_utils import PermissionType

log = logging.getLogger(__name__)

PERM_ROLES_INDEXES = [
    IndexModel([("name", "text")], name="role name search"),
    IndexModel([("guild_id", 1), ("name", 1)], name="unique role name in guild", unique=True)
]

T = TypeVar("T")


class PermManager:
    _config: Config

    def __init__(self, bot: Giesela) -> None:
        self._bot = bot
        self._config = bot.config

        perm_coll_name = self._config.app.mongodb.collections.permissions

        self._roles_coll = self._config.mongodb[f"{perm_coll_name}_roles"]
        self._role_orders_coll = self._config.mongodb[f"{perm_coll_name}_role_orders"]
        self._targets_coll = self._config.mongodb[f"{perm_coll_name}_targets"]

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    @property
    def _redis_prefix(self) -> str:
        return self._config.app.redis.namespaces.permissions

    async def _dump_to_redis(self, targets: Iterable[Target], role_pool: Union[Dict[str, Role], List[Role]]) -> None:
        await REDIS_DEL_NS.eval(self._redis, args=[f"{self._redis_prefix}:*"])

        futures = []

        for target in targets:
            if not target.role_ids:
                log.warning(f"Skipping target {target} because it has no roles")
                continue

            key = f"{self._redis_prefix}:targets:{target.target_id}"
            self._redis.rpush(key, *target.role_ids)

        if isinstance(role_pool, list):
            role_pool = {role.absolute_role_id: role for role in role_pool}

        for role in role_pool.values():
            compiled_perms = role.compile_permissions(role_pool)
            if compiled_perms:
                perms_key = f"{self._redis_prefix}:roles:{role.absolute_role_id}:permissions"
                futures.append(self._redis.hmset_dict(perms_key, compiled_perms))
            else:
                log.warning(f"Skipping role {role} because its compiled permissions are empty")

        await asyncio.gather(*futures)

    async def load(self) -> None:
        role_pool: Dict[str, Role] = {}

        async for role_document in self._roles_coll.find():
            role = Role(**role_document)
            role_pool[role.absolute_role_id] = role

        if not role_pool:
            await self.load_from_file()
            return

        sort_map = {}
        async for order_document in self._role_orders_coll.find():
            order = RoleOrder(**order_document)
            for role_id, value in order.build_order_map().items():
                if role_id in sort_map:
                    role_str = str(role_pool.get(role_id, role_id))
                    raise ValueError(f"role {role_str} appears has multiple orderings! (Last found in {order})")

                sort_map[role_id] = value

        targets = []
        async for target_document in self._targets_coll.find():
            target = Target(**target_document)
            target.sort_roles(sort_map)
            targets.append(target)

        await self._dump_to_redis(targets, role_pool)

    async def load_from_file(self) -> None:
        """Load the permissions from the permission config file"""
        # FIXME don't mess with ids, it causes issues with other roles that aren't updated!
        log.info("preparing database for permissions")
        await utils.ensure_indexes(self._roles_coll, PERM_ROLES_INDEXES)

        log.info("Loading permission file")
        roles, role_orders, targets = load_from_file(self._config.app.files.permissions)

        async def _perform_bulk_update(collection: AsyncIOMotorCollection,
                                       update_targets: List[T],
                                       target_filter: Union[str, Callable[[T], Dict[str, Any]]],
                                       *,
                                       delete_first: bool = False,
                                       ) -> None:
            updates = []

            for target in update_targets:
                if isinstance(target_filter, str):
                    selector = dict(_id=getattr(target, target_filter))
                else:
                    selector = target_filter(target)

                document = dataclasses.asdict(target)

                if delete_first:
                    updates.extend((
                        DeleteOne(selector),
                        InsertOne(document)
                    ))
                else:
                    operation = defaultdict(dict)

                    if "_id" in document:
                        operation["$setOnInsert"]["_id"] = document.pop("_id")

                    operation["$set"] = document

                    updates.append(UpdateOne(selector, operation, upsert=True))

            if updates:
                await collection.bulk_write(updates, ordered=delete_first)

        log.debug(f"saving {len(roles)} loaded roles to the database")
        await asyncio.gather(
            _perform_bulk_update(self._roles_coll, roles, lambda role: {"$or": [
                {"_id": role.absolute_role_id},
                {"name": role.name, "guild_id": role.guild_id}
            ]}, delete_first=True),
            _perform_bulk_update(self._role_orders_coll, role_orders, "order_id"),
            _perform_bulk_update(self._targets_coll, targets, "target_id"),
        )

        log.debug(f"dumping to redis")
        await self._dump_to_redis(targets, roles)

    async def has(self, target: RoleTargetType, *perms: PermissionType, global_only: bool = False) -> bool:
        perms = list(chain.from_iterable(map(perm_tree.unfold_perm, perms)))

        if len(perms) > 1:
            return await self.has_many(target, perms, global_only=global_only)
        elif len(perms) == 1:
            return await self.has_one(target, perms[0], global_only=global_only)
        else:
            # you can always have no permissions
            return True

    async def has_one(self, target: RoleTargetType, perm: str, *, global_only: bool = False) -> bool:
        targets = list(map(str, await get_role_targets_for(self._bot, target, global_only=global_only)))

        perm = await REDIS_HAS_PERMISSION.eval(self._redis, keys=targets, args=[self._redis_prefix, perm])
        return perm == b"1"

    async def has_many(self, target: RoleTargetType, perms: List[str], *, global_only: bool = False) -> bool:
        targets = list(map(str, await get_role_targets_for(self._bot, target, global_only=global_only)))

        perm = await REDIS_HAS_ALL_PERMISSIONS.eval(self._redis, keys=targets, args=[self._redis_prefix, *perms])
        return perm == b"1"
