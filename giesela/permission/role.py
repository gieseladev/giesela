import uuid
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterator, List, Mapping, Optional, Tuple, Union

from .tree import perm_tree
from .tree_utils import CompiledPerms, PermSpecType

__all__ = ["RoleContext", "Role", "create_new_role", "RoleOrder", "RoleOrderValue", "get_role_context_from_order_id", "get_higher_role_contexts",
           "get_higher_or_equal_role_contexts", "GLOBAL_ROLE_CONTEXTS", "GUILD_ROLE_CONTEXTS"]


class RoleContext(Enum):
    GUILD = "guild"
    GUILD_DEFAULT = "guild_default"
    GLOBAL = "global"
    SUPERGLOBAL = "superglobal"

    @property
    def order_value(self) -> int:
        return ROLE_CONTEXT_POSITIONS[self]

    @property
    def is_global(self) -> bool:
        """Whether the role exists outside of a guild"""
        return self in GLOBAL_ROLE_CONTEXTS

    @property
    def is_guild(self) -> bool:
        """Whether the role is specific to a guild"""
        return self in GUILD_ROLE_CONTEXTS

    @property
    def is_guild_specific(self) -> bool:
        """Check whether context is bound to a guild"""
        return self == RoleContext.GUILD

    @property
    def is_default(self) -> bool:
        """Check whether this context is default"""
        return self == RoleContext.GUILD_DEFAULT

    def get_order_id(self, guild_id: Optional[int]) -> str:
        if self == RoleContext.GUILD:
            if not guild_id:
                raise ValueError(f"guild_id is required for {self}")

            return str(guild_id)
        else:
            return self.value


ROLE_CONTEXT_ORDER = [
    RoleContext.SUPERGLOBAL,
    RoleContext.GUILD,
    RoleContext.GUILD_DEFAULT,
    RoleContext.GLOBAL
]

ROLE_CONTEXT_POSITIONS = {context: i for i, context in enumerate(ROLE_CONTEXT_ORDER)}

GLOBAL_ROLE_CONTEXTS = {RoleContext.GLOBAL, RoleContext.SUPERGLOBAL}
GUILD_ROLE_CONTEXTS = {RoleContext.GUILD, RoleContext.GUILD_DEFAULT}

ContextHierarchy = Mapping[RoleContext, Union["ContextHierarchy", None]]
ROLE_CONTEXT_HIERARCHY: ContextHierarchy = OrderedDict([
    (RoleContext.SUPERGLOBAL, OrderedDict([
        (RoleContext.GUILD_DEFAULT, OrderedDict([
            (RoleContext.GUILD, None)
        ])),
        (RoleContext.GLOBAL, None)
    ]))
])


def get_role_context_from_order_id(_id: str) -> RoleContext:
    """Get the `RoleContext` from the id of a role order document.

    This works because the id happens to be the role context unless it's for a specific guild
    in which case it's the id of said guild (as a string).
    """
    if _id.isdigit():
        return RoleContext.GUILD
    else:
        return RoleContext(_id)


def get_higher_role_contexts(context: RoleContext) -> Iterator[RoleContext]:
    """Get all contexts that are "higher" (in the hierarchy) than the given one.

    +------------------------+
    |                        |
    |       ++SUPERGLOBAL+   |
    |       |            |   |
    |       v            v   |
    | GUILD_DEFAULT   GLOBAL |
    |       +                |
    |       |                |
    |       v                |
    |     GUILD              |
    |                        |
    +------------------------+

    The results are ordered from highest to lowest.

    THIS IS NOT THE ORDER PERMISSIONS ARE CONSIDERED IN!
    The order reflects the permission to edit the following roles.
    """
    contexts: List[RoleContext] = []

    def recursive_hierarchy_traverse(level: ContextHierarchy) -> bool:
        if context in level:
            return True

        for level_context, value in level.items():
            if value is None:
                continue

            if recursive_hierarchy_traverse(value):
                contexts.append(level_context)
                return True

        return False

    recursive_hierarchy_traverse(ROLE_CONTEXT_HIERARCHY)

    yield from reversed(contexts)


def get_higher_or_equal_role_contexts(context: RoleContext) -> Iterator[RoleContext]:
    """Get contexts that are at least as high as the given one.

    In reality this is just `get_higher_role_contexts` with the given
    `RoleContext` added to the end.
    """
    yield from get_higher_role_contexts(context)
    yield context


@dataclass
class Role:
    """A group of permissions which can be assigned to a target."""
    _id: str
    role_id: str

    name: str

    context: str
    guild_id: Optional[int]

    grant: List[PermSpecType]
    deny: List[PermSpecType]

    base_ids: List[str]

    @property
    def absolute_role_id(self) -> str:
        return self._id

    @property
    def role_context(self) -> RoleContext:
        return RoleContext(self.context)

    @property
    def is_global(self) -> bool:
        return self.role_context.is_global

    @property
    def is_guild(self) -> bool:
        return self.role_context.is_guild

    @property
    def is_default(self) -> bool:
        """Check whether role is default

        Currently this is only true for role context `RoleContext.GUILD_DEFAULT`
        """
        return self.role_context.is_default

    def compile_own_permissions(self) -> CompiledPerms:
        return perm_tree.compile_permissions(self.grant, self.deny)

    def compile_permissions(self, base_pool: Dict[str, "Role"]) -> CompiledPerms:
        perms = {}

        for base_id in reversed(self.base_ids):
            base = base_pool.get(base_id)
            if not base:
                raise KeyError(f"Base bool is missing base {base_id} for {self}")

            try:
                perms.update(base.compile_permissions(base_pool))
            except Exception as e:
                raise ValueError(f"Couldn't load base {base_id} of {self}") from e

        perms.update(self.compile_own_permissions())

        return perms


def create_new_role(name: str, context: RoleContext, guild_id: Optional[int]) -> Role:
    role_id = uuid.uuid4().hex
    abs_role_id = f"{guild_id}:{role_id}" if guild_id else role_id

    return Role(abs_role_id, role_id, name, context.value, guild_id, [], [], [])


RoleOrderValue = Tuple[int, int]


def build_role_order_value(context: Union[RoleContext, int], position: int) -> RoleOrderValue:
    """Construct a role order value"""
    if isinstance(context, RoleContext):
        context = context.order_value

    return context, position


@dataclass
class RoleOrder:
    _id: str
    context: str
    order_value: int
    order: List[str]

    @property
    def order_id(self) -> str:
        return self._id

    @property
    def role_context(self) -> RoleContext:
        return RoleContext(self.context)

    def build_order_map(self) -> Dict[str, RoleOrderValue]:
        order_map = {}

        for i, role_id in enumerate(self.order):
            order_map[role_id] = build_role_order_value(self.order_value, i)

        return order_map

    def index_of(self, role_id: str) -> int:
        return self.order.index(role_id)
