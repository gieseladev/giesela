from typing import Any, List

from discord.ext.commands import Command

from .tree_utils import PermissionType

__all__ = ["has_permission", "has_global_permission", "get_decorated_permissions"]


def has_permission(*permissions: PermissionType, global_only: bool = False):
    """Command decorator which requires certain permissions"""
    perms = set(permissions)

    def decorator(command: Command):
        if global_only:
            command._required_global_permissions = perms
        else:
            command._required_permissions = perms
        return command

    return decorator


def has_global_permission(*permissions: PermissionType):
    """Command decorator which requires permission in a global role."""
    return has_permission(*permissions, global_only=True)


def get_decorated_permissions(command: Any, global_only: bool) -> List[PermissionType]:
    """Get the permissions previously added by `has_permission`"""
    if global_only:
        attr = "_required_global_permissions"
    else:
        attr = "_required_permissions"

    try:
        return list(getattr(command, attr))
    except AttributeError:
        return []
