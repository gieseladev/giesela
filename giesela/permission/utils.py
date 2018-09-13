from discord.ext.commands import Context

__all__ = ["has_permission", "expect_permission"]


def has_permission(*permissions: str):
    # prepare perms
    def decorator(func):
        pass

    return decorator


async def expect_permission(ctx: Context, *permissions: str):
    pass
