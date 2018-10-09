from discord.ext.commands import Command

__all__ = ["has_permission", "has_global_permission"]


def has_permission(*permissions: str, global_only: bool = False):
    perms = set(map(str, permissions))

    def decorator(command: Command):
        if global_only:
            command._required_global_permissions = perms
        else:
            command._required_permissions = perms
        return command

    return decorator


def has_global_permission(*permissions: str):
    return has_permission(*permissions, global_only=True)
