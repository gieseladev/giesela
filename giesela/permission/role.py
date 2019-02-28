from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from .tree import perm_tree
from .tree_utils import CompiledPerms, PermSpecType

__all__ = ["RoleContext", "Role", "RoleOrder", "RoleOrderValue", "get_higher_role_contexts", "get_higher_or_equal_role_contexts"]


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
        return self != RoleContext.GUILD

    @property
    def is_guild(self) -> bool:
        """Whether the role is specific to a guild"""
        return self == RoleContext.GUILD

    def get_order_id(self, guild_id: Optional[int]) -> str:
        if self == RoleContext.GUILD:
            if not guild_id:
                raise ValueError(f"guild_id is required for {self}")

            return str(guild_id)
        else:
            return self.value


ROLE_CONTEXT_ORDER = (
    RoleContext.SUPERGLOBAL,
    RoleContext.GUILD,
    RoleContext.GUILD_DEFAULT,
    RoleContext.GLOBAL
)

ROLE_CONTEXT_POSITIONS = {context: i for i, context in enumerate(ROLE_CONTEXT_ORDER)}


def get_higher_role_contexts(context: RoleContext) -> List[RoleContext]:
    position = context.order_value

    return list(ROLE_CONTEXT_ORDER[:position])


def get_higher_or_equal_role_contexts(context: RoleContext) -> List[RoleContext]:
    contexts = get_higher_role_contexts(context)
    contexts.append(context)
    return contexts


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


RoleOrderValue = Tuple[int, int]


def build_role_order_value(context: Union[RoleContext, int], position: int) -> RoleOrderValue:
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
