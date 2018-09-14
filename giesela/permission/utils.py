from discord.ext.commands import Command

__all__ = ["has_permission"]


def has_permission(*permissions: str):
    permissions = set(map(str, permissions))

    def decorator(command: Command):
        command._required_permissions = permissions
        return command

    return decorator
