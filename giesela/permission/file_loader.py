"""Load permissions from the config file"""

import dataclasses
import itertools
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union

import yaml

from .errors import PermissionFileError
from .role import Role, RoleContext, RoleOrder
from .role_target import RoleTarget, Target
from .tree import perm_tree
from .tree_utils import PermSpecType

__all__ = ["FileRole", "load_from_file"]


@dataclass
class FileRole:
    """Representation of a role as it can be found in the config file"""
    role_id: str
    name: str
    targets: List[RoleTarget]
    guild_id: Optional[int]
    base_ids: List[str]

    grant: List[PermSpecType]
    deny: List[PermSpecType]

    def __str__(self) -> str:
        return self.name


T = TypeVar("T")


def _ensure_type(obj: Union[Any, None], cls: Type[T], msg: str = None) -> Union[T, None]:
    """Ensure the type of the passed data.

    Raises a `PermissionFileError` if the types don't match,
    otherwise it's a no-op.
    The passed message is formatted with the following keyword arguments:
    - obj:      obj
    - cls:      cls
    - obj_cls   type(obj)
    - obj_type  obj_cls.__name__

    If no message is passed, a default message is used.
    """
    if obj is None:
        return None

    if not isinstance(obj, cls):
        obj_cls = type(obj)
        obj_type = obj_cls.__name__
        msg = msg.format(obj=obj, cls=cls, obj_cls=obj_cls, obj_type=obj_type) if msg else f"Expected type {cls}, found {obj_type}: {obj}"
        raise PermissionFileError(msg)

    return obj


def _make_list(data: Union[None, T, List[T]]) -> List[T]:
    """Convert the passed data to a list if it isn't already."""
    if data is None:
        return []

    if not isinstance(data, list):
        return [data]

    return data


def _get_synonym(data: Dict[str, T], *synonyms: str) -> Optional[T]:
    """Return the first value from the given keys."""
    for synonym in synonyms:
        try:
            return data[synonym]
        except KeyError:
            continue

    return None


def check_permissions(permissions: List[PermSpecType]) -> None:
    """Check whether the given permission specifications are valid"""
    for permission in permissions:
        if isinstance(permission, dict):
            try:
                perm_tree.resolve_permission_selector(permission)
            except Exception as e:
                raise PermissionFileError(f"Invalid permission selector ({e}): {permission}")
        elif isinstance(permission, str):
            if not perm_tree.has(permission):
                raise PermissionFileError(f"Unknown permission: {permission}")
        else:
            raise PermissionFileError(
                f"Permission specifier must either be a permission selector or a permission name, not {type(permission)}: {permission}")


def load_role(role_data: Dict[str, Any], guild_context: bool) -> FileRole:
    """Build a `FileRole` from the raw config data."""
    role_id = _ensure_type(role_data.get("id"), str, "id needs to be a string, not {obj_type}")
    name = _ensure_type(role_data.get("name"), str, "name needs to be a string, not {obj_type}")
    if not name:
        id_str = f"(id: {role_id})" if role_id else ""
        raise PermissionFileError(f"Role needs to have a name. {id_str}")

    if not role_id:
        role_id = uuid.uuid4().hex

    guild_id = _ensure_type(_get_synonym(role_data, "guild", "server"), int, "guild needs to be an id (number), not {obj_type}")
    if guild_id and not guild_context:
        raise PermissionFileError(f"Role {name} cannot be bound to guild {guild_id} because it's in a non-guild context")

    raw_targets = _make_list(_get_synonym(role_data, "targets", "target"))
    targets = []

    for i, raw_target in enumerate(raw_targets, 1):
        try:
            target = RoleTarget(raw_target)
            target.check()
        except Exception as e:
            raise PermissionFileError(f"Role {name} target {raw_target} (nr. {i}) is invalid!") from e
        else:
            if target.guild_context:
                if not guild_context:
                    raise PermissionFileError(f"Role {name} cannot use non-guild target {target}!")

                if target.has_guild_id:
                    if not guild_id:
                        raise PermissionFileError(f"Role {name} is not bound to a guild yet targets a guild-specific target: {target}")

                    elif guild_id != target.guild_id:
                        raise PermissionFileError(f"Role {name} is bound to guild {guild_id} but has a target in another guild: {target}")

            elif guild_context:
                raise PermissionFileError(f"Role {name} is in a guild context and mustn't target non-guild context {target}")

            targets.append(target)

    base_ids = _make_list(_get_synonym(role_data, "base", "bases", "inherit"))

    grant = _make_list(_get_synonym(role_data, "grant", "grants", "allow", "allows"))
    check_permissions(grant)

    deny = _make_list(_get_synonym(role_data, "deny", "denies", "forbid", "forbids"))
    check_permissions(deny)

    if not any((base_ids, grant, deny)):
        raise PermissionFileError(f"Role {name} doesn't grant or deny any permissions and should be deleted!")

    return FileRole(role_id, name, targets, guild_id, base_ids, grant, deny)


def check_roles(roles: List[FileRole]) -> None:
    """Ensure that the given roles are valid.

    Makes sure that the roles have unique ids and names and
    that the bases can be resolved.
    """
    role_ids: Set[str] = set()
    role_names: Set[str] = set()
    for role in roles:
        if role.role_id in role_ids:
            raise PermissionFileError(f"Duplicate role id in shared context! {role.role_id} \"{role.name}\"")
        elif role.name in role_names:
            raise PermissionFileError(f"Duplicate role name in shared context! {role.role_id} \"{role.name}\"")
        else:
            role_ids.add(role.role_id)
            role_names.add(role.name)

    available_role_ids: Set[str] = set()

    for role in reversed(roles):
        for base_id in role.base_ids:
            if base_id not in role_ids:
                raise PermissionFileError(f"Base {base_id} (for {role}) does not exist.")

            if base_id == role.role_id:
                raise PermissionFileError(f"Role {role} is using itself ({base_id}) as a base which is not allowed!")

            if base_id not in available_role_ids:
                raise PermissionFileError(f"Base {base_id} cannot be used by {role}! Bases must always be below the role.")

        available_role_ids.add(role.role_id)


def load_roles(role_datas: Optional[List[Dict[str, Any]]], guild_context: bool) -> List[FileRole]:
    """Load `LoadedRoles` from a list of raw roles."""
    if not role_datas:
        return []

    roles = [load_role(role, guild_context) for role in role_datas]
    check_roles(roles)

    return roles


ROLE_FIELD_NAMES = set(field.name for field in dataclasses.fields(Role))


def build_loaded_role_from_file_role(loaded_role: FileRole, context: RoleContext) -> Role:
    absolute_role_id = f"{loaded_role.guild_id}:{loaded_role.role_id}" if loaded_role.guild_id else loaded_role.role_id

    data = dataclasses.asdict(loaded_role)

    kwargs = {key: value for key, value in data.items() if key in ROLE_FIELD_NAMES}
    kwargs.update(_id=absolute_role_id, context=context.value)

    return Role(**kwargs)


def _build_roles(roles_to_load: List[FileRole], context: RoleContext, roles: List[Role], role_orders: List[RoleOrder]) -> None:
    orders: Dict[str, Tuple[RoleContext, List[str]]] = {}

    for loaded_role in roles_to_load:
        if loaded_role.guild_id:
            context = RoleContext.GUILD
            order_key = str(loaded_role.guild_id)
        else:
            order_key = context.value

        role = build_loaded_role_from_file_role(loaded_role, context)
        roles.append(role)

        order_item = orders.get(order_key)
        if order_item:
            order_item[1].append(role.absolute_role_id)
        else:
            orders[order_key] = (context, [role.absolute_role_id])

    for order_id, (context, role_ids) in orders.items():
        role_orders.append(RoleOrder(order_id, context.value, context.order_value, role_ids))


def load_from_data(data: Dict[str, Any]) -> Tuple[List[Role], List[RoleOrder], List[Target]]:
    """Build permissions"""
    superglobal_roles = load_roles(_get_synonym(data, "superglobal_roles", "superglobal"), False)
    guild_roles = load_roles(_get_synonym(data, "guild_roles", "guild"), True)
    global_roles = load_roles(_get_synonym(data, "global_roles", "global"), False)

    roles: List[Role] = []
    role_orders: List[RoleOrder] = []

    _build_roles(superglobal_roles, RoleContext.SUPERGLOBAL, roles, role_orders)
    _build_roles(guild_roles, RoleContext.GUILD_DEFAULT, roles, role_orders)
    _build_roles(global_roles, RoleContext.GLOBAL, roles, role_orders)

    target_roles: Dict[str, List[str]] = defaultdict(list)
    for role in itertools.chain(superglobal_roles, guild_roles, global_roles):
        for target in role.targets:
            target_roles[str(target)].append(role.role_id)

    targets: List[Target] = [Target(target, role_ids) for target, role_ids in target_roles.items()]

    return roles, role_orders, targets


def load_from_file(location: str) -> Tuple[List[Role], List[RoleOrder], List[Target]]:
    with open(location, "r") as f:
        data = yaml.safe_load(f)

    return load_from_data(data)
