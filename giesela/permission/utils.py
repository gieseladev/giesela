from discord.ext.commands import Command

__all__ = ["has_permission"]


def has_permission(*permissions: str):
    perms = set(map(str, permissions))

    def decorator(command: Command):
        command._required_permissions = perms
        return command

    return decorator
