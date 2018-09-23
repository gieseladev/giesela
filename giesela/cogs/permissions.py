import asyncio
import logging

from discord.ext.commands import Context

from giesela import Giesela, PermManager, PermissionDenied

log = logging.getLogger(__name__)


class Permissions:
    def __init__(self, bot: Giesela):
        self.bot = bot
        self.perm_manager = PermManager(bot.config)

        bot.store_reference("has_permission", self.has_permission)
        bot.store_reference("ensure_permission", self.ensure_permission)

    async def ensure_permission(self, ctx: Context, *keys: str):
        perm = await asyncio.gather(*(self.perm_manager.has(ctx.author, key) for key in keys), loop=self.bot.loop)
        if all(perm):
            return True
        else:
            keys_str = ", ".join(f"\"{key}\"" for key in keys)
            raise PermissionDenied(f"Permission {keys_str} required!")

    async def has_permission(self, ctx: Context, *keys: str) -> bool:
        try:
            await self.ensure_permission(ctx, *keys)
        except PermissionDenied:
            return False
        else:
            return True

    # TODO: find better solution for help command
    async def __global_check_once(self, ctx: Context) -> bool:
        try:
            required_permissions = getattr(ctx.command, "_required_permissions")
        except AttributeError:
            log.debug(f"no required permissions for {ctx.command}")
            return True
        else:
            log.debug(f"checking permissions {required_permissions}")
            await self.ensure_permission(ctx, *required_permissions)
            return True


def setup(bot: Giesela):
    bot.add_cog(Permissions(bot))
