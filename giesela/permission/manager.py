import asyncio
import dataclasses
import logging
from collections import defaultdict, deque
from itertools import chain
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Set, TypeVar, Union

from aioredis import Redis
from aioredis.commands import MultiExec
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorCursor
from pymongo import DeleteOne, IndexModel, InsertOne, UpdateOne
from pymongo.results import UpdateResult

from giesela import Giesela, utils
from giesela.config import Config
from .file_loader import load_from_file
from .redis_lua import REDIS_ANY_TARGET_HAS_ROLE, REDIS_DEL_NS, REDIS_HAS_ALL_PERMISSIONS, REDIS_HAS_PERMISSION
from .role import GUILD_ROLE_CONTEXTS, Role, RoleContext, RoleOrder, get_higher_or_equal_role_contexts, get_role_context_from_order_id
from .role_target import RoleTarget, RoleTargetType, Target, get_role_targets_for
from .tree import perm_tree
from .tree_utils import PermissionType

__all__ = ["PermManager"]

log = logging.getLogger(__name__)

PERM_ROLE_ORDERS_INDEXES = [
    IndexModel([("order_value", 1), ("context", 1)], name="order context"),
    IndexModel([("order", 1)], name="order list", unique=True),
]

PERM_ROLES_INDEXES = [
    IndexModel([("name", "text")], name="role name search"),
    IndexModel([("guild_id", 1), ("name", 1)], name="role name in guild", unique=True)
]

PERM_TARGETS_INDEXES = [
    IndexModel([("role_ids", 1)], name="role_ids")
]

T = TypeVar("T")

RoleOrId = Union[Role, str]


def get_guild_id_selector(guild_id: int = None, *,
                          include_global: bool = True,
                          include_guild_default: bool = True,
                          nested_prefix: str = None) -> Dict[str, Any]:
    """Build the selector for the guild"""
    selector: Dict[str, Any] = {}

    if nested_prefix:
        nested_prefix += "."
    else:
        nested_prefix = ""

    if guild_id and (include_global or include_guild_default):
        gid_selector = {"$in": [None, guild_id]}
    elif guild_id:
        gid_selector = {"$eq": guild_id}
    elif include_global:
        gid_selector = {"$eq": None}
    else:
        raise ValueError("Can't match roles with no guild which have to be in the guild context...")

    selector[nested_prefix + "guild_id"] = gid_selector

    if include_guild_default and not include_global:
        context_selector = {"$in": [context.value for context in GUILD_ROLE_CONTEXTS]}
    elif not include_guild_default:
        context_selector = {"$ne": RoleContext.GUILD_DEFAULT.value}
    else:
        context_selector = None

    if context_selector:
        selector[nested_prefix + "context"] = context_selector

    return selector


async def _collect_aggregated_targets(cursor: AsyncIOMotorCursor) -> List[Target]:
    """Collect the aggregated documents into a list of `Target`"""
    target_roles: Dict[str, List[str]] = defaultdict(list)

    async for target_doc in cursor:
        target_roles[target_doc["_id"]].append(target_doc["role_ids"])

    return [Target(target_id, role_ids) for target_id, role_ids in target_roles.items()]


class PermManager:
    _config: Config

    def __init__(self, bot: Giesela) -> None:
        self._bot = bot
        self._config = bot.config

        perm_coll_name = self._config.app.mongodb.collections.permissions

        self._mongo_client = self._config.mongo_client
        self._roles_coll = self._config.mongodb[f"{perm_coll_name}_roles"]
        self._role_orders_coll = self._config.mongodb[f"{perm_coll_name}_role_orders"]
        self._targets_coll = self._config.mongodb[f"{perm_coll_name}_targets"]

    @property
    def _redis(self) -> Redis:
        return self._config.redis

    @property
    def _redis_prefix(self) -> str:
        return self._config.app.redis.namespaces.permissions

    async def _dump_targets_to_redis(self, targets: Iterable[Target], *, tr: MultiExec = None) -> None:
        if tr:
            execute_after = False
        else:
            execute_after = True
            tr = self._redis.multi_exec()

        for target in targets:
            key = f"{self._redis_prefix}:targets:{target.target_id}"
            tr.delete(key)

            if not target.role_ids:
                log.warning(f"Ignoring target {target} because it has no roles")
                continue

            tr.rpush(key, *target.role_ids)

        if execute_after:
            await tr.execute()

    async def _dump_roles_to_redis(self, role_pool: Dict[str, Role], *, tr: MultiExec = None) -> None:
        if tr:
            execute_after = False
        else:
            execute_after = True
            tr = self._redis.multi_exec()

        for role in role_pool.values():
            compiled_perms = role.compile_permissions(role_pool)
            if compiled_perms:
                perms_key = f"{self._redis_prefix}:roles:{role.absolute_role_id}:permissions"
                tr.hmset_dict(perms_key, compiled_perms)
            else:
                log.warning(f"Skipping role {role} because its compiled permissions are empty")

        if execute_after:
            await tr.execute()

    async def _dump_to_redis(self, targets: Iterable[Target], role_pool: Union[Dict[str, Role], List[Role]]) -> None:
        await REDIS_DEL_NS.eval(self._redis, args=[f"{self._redis_prefix}:*"])

        tr = self._redis.multi_exec()

        if isinstance(role_pool, list):
            role_pool = {role.absolute_role_id: role for role in role_pool}

        await self._dump_targets_to_redis(targets, tr=tr)
        await self._dump_roles_to_redis(role_pool, tr=tr)

        await tr.execute()

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
        log.info("preparing database for permissions")
        await utils.ensure_indexes(self._role_orders_coll, PERM_ROLE_ORDERS_INDEXES)
        await utils.ensure_indexes(self._roles_coll, PERM_ROLES_INDEXES)
        await utils.ensure_indexes(self._targets_coll, PERM_TARGETS_INDEXES)

        log.info("Loading permission file")
        roles, role_orders, targets = load_from_file(self._config.app.files.permissions)

        # FIXME don't mess with ids, it causes issues with other roles that aren't updated!

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
                        document.pop("_id")
                        if "_id" not in target_filter:
                            raise ValueError("_id field can't be set when querying by something other than the _id!")

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
        """Check whether the given target has the given permissions."""
        perms = list(chain.from_iterable(map(perm_tree.unfold_perm, perms)))

        if len(perms) > 1:
            return await self._has_many(target, perms, global_only=global_only)
        elif len(perms) == 1:
            return await self._has_one(target, perms[0], global_only=global_only)
        else:
            # you can always have no permissions
            return True

    async def _has_one(self, target: RoleTargetType, perm: str, *, global_only: bool = False) -> bool:
        """Check whether a target has the given permission"""
        targets = list(map(str, await get_role_targets_for(self._bot, target, global_only=global_only)))

        perm = await REDIS_HAS_PERMISSION.eval(self._redis, keys=targets, args=[self._redis_prefix, perm])
        return perm == b"1"

    async def _has_many(self, target: RoleTargetType, perms: List[str], *, global_only: bool = False) -> bool:
        """Check whether a target has all the given permissions."""
        targets = list(map(str, await get_role_targets_for(self._bot, target, global_only=global_only)))

        perm = await REDIS_HAS_ALL_PERMISSIONS.eval(self._redis, keys=targets, args=[self._redis_prefix, *perms])
        return perm == b"1"

    async def has_role(self, target: RoleTargetType, role: RoleOrId) -> bool:
        """Check whether a target has a role"""
        targets = await get_role_targets_for(self._bot, target, global_only=role.is_global)
        target_keys = [f"{self._redis_prefix}:targets:{target}" for target in targets]

        role_id = role.absolute_role_id if isinstance(role, Role) else role
        res = await REDIS_ANY_TARGET_HAS_ROLE.eval(self._redis, keys=target_keys, args=[role_id])
        return res == b"1"

    async def target_has_role(self, target: RoleTarget, role: RoleOrId) -> bool:
        """Check whether a `RoleTarget` has a role"""
        role_id = role.absolute_role_id if isinstance(role, Role) else role
        target_key = f"{self._redis_prefix}:targets:{target}"

        res = await REDIS_ANY_TARGET_HAS_ROLE.eval(self._redis, keys=[target_key], args=[role_id])
        return res == b"1"

    async def role_has_permission(self, role: RoleOrId, perm: str, *, default: T = False) -> Union[bool, T]:
        """Check whether role has permission"""
        role_id = role.absolute_role_id if isinstance(role, Role) else role
        has_perm = await self._redis.hget(f"{self._redis_prefix}:roles:{role_id}:permissions", perm)
        if has_perm:
            return has_perm == b"1"

        return default

    async def can_edit_role(self, target: RoleTargetType, role: Role, *, assign: bool = False) -> bool:
        """Check whether a target is allowed to edit the given role."""

        async def has_edit_lower_perm() -> bool:
            global_only = role.is_global or (role.is_default and not assign)
            targets = await get_role_targets_for(self._bot, target, global_only=global_only)
            target_ids = [str(role_target) for role_target in targets]

            contexts: Set[RoleContext] = set(get_higher_or_equal_role_contexts(role.role_context))

            cursor = self._aggregate_ordered_targets(
                {"_id": {"$in": target_ids}},
                lookup_pipeline_match_context={"$in": [context.value for context in contexts]},
                group_by_role=True
            )

            async for document in cursor:
                role_id = document["role_ids"]
                if role_id == role.absolute_role_id:
                    log.debug(f"ignoring edit permission of role {role_id} because it's the role to be edited")
                    continue

                has_perm = await self.role_has_permission(role_id, perm_tree.permissions.roles.edit, default=None)
                if has_perm is not None:
                    return has_perm

            return False

        async def has_edit_self_perm() -> bool:
            # checks whether the target is part of the role and the role can edit itself!

            # default roles can not edit themselves!
            if role.is_default and not assign:
                return False

            # check permission first because redis is probably going to be faster
            if await self.role_has_permission(role, perm_tree.permissions.roles.self):
                if await self.has_role(target, role):
                    return True

            return False

        # accept either
        return any(await asyncio.gather(has_edit_lower_perm(), has_edit_self_perm()))

    def _aggregate_ordered_roles(self, match: Dict[str, Any] = None, *,
                                 pre_lookup: List[Dict[str, Any]] = None,
                                 post_lookup: List[Dict[str, Any]] = None,
                                 after_sort: List[Dict[str, Any]] = None,
                                 sort_by_order: bool = True) -> AsyncIOMotorCursor:
        """Aggregate roles in order.

        Results have the following structure:
        +----------+--------------------+--------------------------------------+
        |    key   |        type        |             description              |
        +----------+--------------------+--------------------------------------+
        | _id      | str                | absolute role id                     |
        +----------+--------------------+--------------------------------------+
        | role_id  | str                | relative role id                     |
        +----------+--------------------+--------------------------------------+
        | name     | str                | role name                            |
        +----------+--------------------+--------------------------------------+
        | context  | str                | role context                         |
        +----------+--------------------+--------------------------------------+
        | guild_id | Optional[int]      | id of bound guild                    |
        +----------+--------------------+--------------------------------------+
        | grant    | List[PermSpecType] | list of granted permissions          |
        +----------+--------------------+--------------------------------------+
        | deny     | List[PermSpecType] | list of denied permissions           |
        +----------+--------------------+--------------------------------------+
        | base_ids | List[str]          | list of absolute role ids which      |
        |          |                    | serve as a base for this role        |
        +----------+--------------------+--------------------------------------+
        | order    | order object       | see `PermManager._aggregate_ordered` |
        +----------+--------------------+--------------------------------------+
        """
        return self._aggregate_ordered(
            self._roles_coll, match,
            pre_lookup=pre_lookup,
            lookup_let={
                "role_id": "$_id",
                "context": "$context"
            },
            lookup_pipeline_match={"$expr": {"$and": [
                {"$eq": [
                    "$context", "$$context"
                ]},
                {"$in": [
                    "$$role_id", "$order"
                ]}
            ]}},
            post_lookup=post_lookup,
            after_sort=after_sort,
            sort_by_order=sort_by_order,
        )

    def _aggregate_ordered_targets(self, match: Dict[str, Any] = None, *,
                                   group_by_role: bool = False,
                                   pre_lookup: List[Dict[str, Any]] = None,
                                   lookup_pipeline_match_context: Any = None,
                                   post_lookup: List[Dict[str, Any]] = None,
                                   after_sort: List[Dict[str, Any]] = None,
                                   sort_by_order: bool = True) -> AsyncIOMotorCursor:
        """Aggregate targets.

        Results have the following structure.
        +----------+--------------+--------------------------------------+
        |    key   |     type     |              description             |
        +----------+--------------+--------------------------------------+
        | _id      | str          | role target                          |
        +----------+--------------+--------------------------------------+
        | role_ids | str          | role id                              |
        +----------+--------------+--------------------------------------+
        | order    | order object | see `PermManager._aggregate_ordered` |
        +----------+--------------+--------------------------------------+
        """
        _pre_lookup = [
            {"$unwind": {
                "path": "$role_ids"
            }}
        ]

        if group_by_role:
            _pre_lookup.append({"$group": {
                "_id": "$role_ids",
                "role_ids": {"$first": "$role_ids"},
            }})

        pre_lookup = _pre_lookup + (pre_lookup or [])

        lookup_pipeline_match = {
            "$expr": {"$in": ["$$role_id", "$order"]}
        }
        if lookup_pipeline_match_context is not None:
            lookup_pipeline_match["context"] = lookup_pipeline_match_context

        return self._aggregate_ordered(
            self._targets_coll, match,
            pre_lookup=pre_lookup,
            lookup_let={
                "role_id": "$role_ids"
            },
            lookup_pipeline_match=lookup_pipeline_match,
            post_lookup=post_lookup,
            after_sort=after_sort,
            sort_by_order=sort_by_order,
        )

    def _aggregate_ordered(self, collection: AsyncIOMotorCollection, match: Dict[str, Any] = None, *,
                           pre_lookup: List[Dict[str, Any]] = None,
                           lookup_let: Dict[str, Any],
                           lookup_pipeline_match: Dict[str, Any],
                           post_lookup: List[Dict[str, Any]] = None,
                           after_sort: List[Dict[str, Any]] = None,
                           sort_by_order: bool = True) -> AsyncIOMotorCursor:
        """Aggregate documents such that they include the order from the role orders collection.

        The added order object has the following structure:
        +-------------+------+-----------------------------------+
        |     key     | type |            description            |
        +-------------+------+-----------------------------------+
        | _id         | str  |                                   |
        |             |      | role order document id            |
        +-------------+------+-----------------------------------+
        | order_value | int  |                                   |
        |             |      | order value of order context      |
        +-------------+------+-----------------------------------+
        | index       | int  | position of role in order context |
        +-------------+------+-----------------------------------+

        Args:
            sort_by_order: if true the results are ordered properly by their value (order_value, index).
        """
        pipeline = []
        if match is not None:
            pipeline.append({"$match": match})

        if pre_lookup:
            pipeline.extend(pre_lookup)

        pipeline.extend([
            {"$lookup": {
                "from": self._role_orders_coll.name,
                "let": lookup_let,
                "pipeline": [
                    {"$match": lookup_pipeline_match},
                    {"$project": {
                        "_id": 1,
                        "order_value": 1,
                        "index": {"$indexOfArray": ["$order", "$$role_id"]}
                    }}
                ],
                "as": "order"
            }},
            {"$addFields": {
                "order": {"$arrayElemAt": ["$order", 0]}
            }},
            {"$match": {
                "order": {"$exists": True}
            }}
        ])

        if post_lookup:
            pipeline.extend(post_lookup)

        if sort_by_order:
            pipeline.append({"$sort": {
                "order.order_value": 1,
                "order.index": 1
            }})

            if after_sort:
                pipeline.extend(after_sort)

        return collection.aggregate(pipeline)

    async def _compile_targets_with_match(self, match: Dict[str, Any], *, tr: MultiExec = None) -> None:
        """Recompile targets which match the given conditions"""
        cursor = self._aggregate_ordered_targets(match)
        targets = await _collect_aggregated_targets(cursor)
        await self._dump_targets_to_redis(targets, tr=tr)

    async def _get_role_pool(self, match: Dict[str, Any]) -> Dict[str, Role]:
        """Get the roles that match the provided selector and all bases."""
        role_pool: Dict[str, Role] = {}
        cursor = self._roles_coll.aggregate([
            {"$match": match},
            {"$graphLookup": {
                "from": self._roles_coll.name,
                "startWith": "$base_ids",
                "connectFromField": "base_ids",
                "connectToField": "_id",
                "as": "bases"
            }}
        ])

        role_docs: Deque[Dict[str, Any]] = deque()

        async for doc in cursor:
            role_docs.append(doc)
            while role_docs:
                role_doc = role_docs.pop()
                role_id = role_doc["_id"]
                if role_id in role_pool:
                    continue

                bases = role_doc.pop("bases", None)
                if bases:
                    role_docs.extend(bases)

                role = Role(**role_doc)
                role_pool[role_id] = role

        return role_pool

    async def _compile_roles_with_match(self, match: Dict[str, Any], *, tr: MultiExec = None) -> None:
        """Compile and dump to redis all roles that match"""
        role_pool = await self._get_role_pool(match)
        await self._dump_roles_to_redis(role_pool, tr=tr)

    async def get_order_with_role(self, role: RoleOrId) -> Optional[RoleOrder]:
        """Get the order of a role"""
        role_id = role.absolute_role_id if isinstance(role, Role) else role

        doc = await self._role_orders_coll.find_one({"order": role_id})
        if doc:
            return RoleOrder(**doc)
        else:
            return None

    async def move_role(self, role: Role, position: int) -> None:
        """Move a role to a new position and recompile its targets"""
        role_id = role.absolute_role_id
        order_selector = {"_id": role.role_context.get_order_id(role.guild_id)}

        result = await self._role_orders_coll.bulk_write([
            UpdateOne(order_selector, {"$pull": {"order": role_id}}),
            UpdateOne(order_selector, {"$push": {
                "order": {
                    "$each": [role_id],
                    "$position": position
                }
            }})
        ])

        if result.modified_count < 1:
            raise KeyError(f"No role order found for {role}")

        log.debug(f"recompiling targets with role {role} after move")
        await self._compile_targets_with_match({"role_ids": role_id})

    async def get_role(self, role_id: str) -> Optional[Role]:
        """Get the role with the specified id"""
        doc = await self._roles_coll.find_one(role_id)
        if doc:
            return Role(**doc)
        else:
            return None

    async def get_roles(self, role_ids: Iterable[str]) -> List[Role]:
        """Get the roles with the specified ids"""
        role_ids = list(role_ids)
        if not role_ids:
            return []

        cursor = self._roles_coll.find({"_id": {"$in": role_ids}})

        return [Role(**doc) async for doc in cursor]

    async def get_roles_with_bases(self, *role_ids: str) -> Dict[str, Role]:
        """Get a role pool for all involved roles"""
        return await self._get_role_pool({"_id": {"$in": list(role_ids)}})

    async def search_role_for_guild(self, query: str, guild_id: int = None, *,
                                    include_global: bool = True,
                                    include_guild_default: bool = True) -> Optional[Role]:
        """Get the first role that matches the query."""
        guild_selector = get_guild_id_selector(guild_id, include_global=include_global, include_guild_default=include_guild_default)
        cursor = self._roles_coll.find(
            {
                "$text": {"$search": query},
                **guild_selector
            },
            projection={"score": {"$meta": "textScore"}},
            sort=[("score", {"$meta": "textScore"})],
            limit=1
        )

        async for doc in cursor:
            doc.pop("score")
            return Role(**doc)

        return None

    async def get_or_search_role_for_guild(self, query: str, guild_id: int = None) -> Optional[Role]:
        """Get the first role with the specified id or search for it otherwise"""
        return await self.get_role(query) or await self.search_role_for_guild(query, guild_id)

    async def get_targets_with_role(self, role: RoleOrId) -> List[Target]:
        """Get all targets that have the specified role"""
        role_id = role.absolute_role_id if isinstance(role, Role) else role
        cursor = self._aggregate_ordered_targets({"role_ids": role_id})
        return await _collect_aggregated_targets(cursor)

    async def can_move_role(self, target: RoleTargetType, role_context: RoleContext, index: int) -> bool:
        """Find out whether a target can move a role to the given position."""
        targets = await get_role_targets_for(self._bot, target)
        target_ids = [str(role_target) for role_target in targets]

        cursor = self._aggregate_ordered_targets({"_id": {"$in": target_ids}}, after_sort=[{"$limit": 1}], group_by_role=True)
        await cursor.fetch_next
        doc = cursor.next_object()

        if not doc:
            return False

        order = doc["order"]
        order_value = order["order_value"]
        if role_context.order_value > order_value:
            context = get_role_context_from_order_id(order["_id"])
            # make sure they're both either guild roles or global roles!
            return context.is_global == role_context.is_global

        order_index = order["index"]
        if index > order_index:
            return True

    async def get_target_roles_for_guild(self, target: RoleTargetType, guild_id: int = None, *,
                                         include_global: bool = True,
                                         include_guild_default: bool = True) -> List[Role]:
        """Get all roles the given target is in."""
        targets = await get_role_targets_for(self._bot, target, global_only=not guild_id, guild_only=guild_id and not include_global)
        target_ids = [str(role_target) for role_target in targets]

        guild_selector = get_guild_id_selector(guild_id, nested_prefix="role",
                                               include_global=include_global,
                                               include_guild_default=include_guild_default)

        cursor = self._aggregate_ordered_targets(
            {"_id": {"$in": target_ids}},
            pre_lookup=[
                {"$group": {
                    "_id": "$role_ids",
                    "role_ids": {"$first": "$role_ids"},
                }},
                {"$lookup": {
                    "from": self._roles_coll.name,
                    "localField": "role_ids",
                    "foreignField": "_id",
                    "as": "role",
                }},
                {"$addFields": {
                    "role": {"$arrayElemAt": ["$role", 0]}
                }},
                {"$match": guild_selector}
            ],
            group_by_role=True
        )

        roles = []
        async for doc in cursor:
            role_doc = doc["role"]
            role = Role(**role_doc)
            roles.append(role)

        return roles

    async def get_all_roles_for_guild(self, guild_id: int = None, *,
                                      include_global: bool = True,
                                      include_guild_default: bool = True) -> List[Role]:
        """Get all roles the specified guild."""
        cursor = self._aggregate_ordered_roles(get_guild_id_selector(guild_id,
                                                                     include_global=include_global,
                                                                     include_guild_default=include_guild_default))

        roles: List[Role] = []
        async for doc in cursor:
            doc.pop("order")
            role = Role(**doc)
            roles.append(role)

        return roles

    async def role_add_target(self, role: RoleOrId, target: RoleTarget) -> None:
        """Assign a role to a target"""
        if isinstance(role, Role):
            role_id = role.absolute_role_id

            # sanity check
            if target.guild_context and not role.is_guild:
                raise TypeError(f"Cannot assign {role} to {target}")
        else:
            role_id = role

        await self._targets_coll.update_one(
            {"_id": str(target)},
            {"$addToSet": {
                "role_ids": role_id
            }},
            upsert=True
        )

        await self._compile_targets_with_match({"_id": str(target)})

    async def role_remove_target(self, role: RoleOrId, target: RoleTarget) -> None:
        """Remove a role from a target"""
        role_id = role.absolute_role_id if isinstance(role, Role) else role

        await self._targets_coll.update_one(
            {"_id": str(target)},
            {"$pull": {
                "role_ids": role_id
            }}
        )

        await self._redis.lrem(f"{self._redis_prefix}:targets:{target}", 1, role_id)

    async def delete_role(self, role: RoleOrId) -> None:
        """Delete a role."""
        role_id = role.absolute_role_id if isinstance(role, Role) else role

        async with await self._mongo_client.start_session() as sess:
            inheriting_role_ids: List[str] = [doc["_id"] async for doc in self._roles_coll.find(
                {"base_ids": role_id},
                projection=["_id"],
                session=sess
            )]

            target_ids = [doc["_id"] async for doc in self._targets_coll.find(
                {"role_ids": role_id},
                projection=["_id"],
                session=sess
            )]

            async with sess.start_transaction():
                # remove role itself
                await self._roles_coll.delete_one({"_id": role_id}, session=sess)

                # remove role inheritors
                await self._roles_coll.update_many(
                    {"_id": {"$in": inheriting_role_ids}},
                    {"$pull": {
                        "base_ids": role_id
                    }},
                    session=sess
                )

                # remove role from targets
                await self._targets_coll.update_many(
                    {"_id": {"$in": target_ids}},
                    {"$pull": {
                        "role_ids": role_id
                    }},
                    session=sess
                )

                # remove role from orders
                await self._role_orders_coll.update_one(
                    {"order": role_id},
                    {"$pull": {
                        "order": role_id
                    }},
                    session=sess
                )

        tr = self._redis.multi_exec()

        # redis remove role
        tr.delete(f"{self._redis_prefix}:roles:{role_id}:permissions")

        # redis recompile roles with role as base
        await self._compile_roles_with_match({"_id": {"$in": inheriting_role_ids}}, tr=tr)

        # redis remove role from targets
        for target_id in target_ids:
            tr.lrem(f"{self._redis_prefix}:targets:{target_id}", 1, role_id)

        await tr.execute()

    async def save_role(self, role: Role) -> None:
        """Save a role.

        Can be used to save an edited role, but it will not
        allow for changes to the context, role_id, or the guild_id.
        """
        insert_only_keys = {"role_id", "context", "guild_id"}
        exclude_keys = {"_id"}

        data = dataclasses.asdict(role)

        set_op = {}
        set_on_insert_op = {}

        for key, value in data.items():
            if key in exclude_keys:
                continue
            elif key in insert_only_keys:
                set_on_insert_op[key] = value
            else:
                set_op[key] = value

        async with await self._mongo_client.start_session() as sess:
            async with sess.start_transaction():
                result: UpdateResult = await self._roles_coll.update_one(
                    {"_id": role.absolute_role_id},
                    {
                        "$set": set_op,
                        "$setOnInsert": set_on_insert_op
                    },
                    upsert=True,
                    session=sess
                )

                # role was created
                if result.upserted_id:
                    log.info("saving new role, adding to role orders")
                    context = role.role_context
                    order_id = context.get_order_id(role.guild_id)
                    await self._role_orders_coll.update_one(
                        {"_id": order_id},
                        {
                            "$setOnInsert": {
                                "context": context.value,
                                "order_value": context.order_value
                            },
                            "$push": {"order": result.upserted_id}
                        },
                        upsert=True,
                        session=sess
                    )

        await self._compile_roles_with_match({"_id": role.absolute_role_id})
