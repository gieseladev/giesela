from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from .tree import perm_tree
from .tree_utils import CompiledPerms, PermSpecType

__all__ = ["RoleContext", "Role", "RoleOrder", "RoleOrderValue"]


class RoleContext(Enum):
    GUILD = "guild"
    GUILD_DEFAULT = "guild_default"
    GLOBAL = "global"
    SUPERGLOBAL = "superglobal"

    @property
    def context_value(self) -> int:
        return ROLE_CONTEXT_ORDER[self]

    @property
    def order_value(self) -> int:
        return ROLE_CONTEXT_ORDER[self]


ROLE_CONTEXT_ORDER = {context: i for i, context in enumerate((
    RoleContext.SUPERGLOBAL,
    RoleContext.GUILD,
    RoleContext.GUILD_DEFAULT,
    RoleContext.GLOBAL
))}


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
        return self.role_context != RoleContext.GUILD

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

        perms.update(perm_tree.compile_permissions(self.grant, self.deny))

        return perms


RoleOrderValue = Tuple[int, int]


def build_role_order_value(context: Union[RoleContext, int], position: int) -> RoleOrderValue:
    if isinstance(context, RoleContext):
        context = context.order_value

    return context, position


@dataclass
class RoleOrder:
    _id: str
    order: List[str]

    @property
    def order_id(self) -> str:
        return self._id

    def get_context(self) -> RoleContext:
        try:
            return RoleContext(self._id)
        except ValueError:
            return RoleContext.GUILD_DEFAULT

    def build_order_map(self) -> Dict[str, RoleOrderValue]:
        order_map = {}

        context = self.get_context()

        for i, role_id in enumerate(self.order):
            order_map[role_id] = build_role_order_value(context, i)

        return order_map
