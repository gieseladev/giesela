from typing import List, Optional, Tuple, Union

from discord import User
from discord.ext.commands import Context

from giesela import Giesela, GieselaPlayer, PlayableEntry
from giesela.permission import PermissionType, perm_tree

__all__ = ["has_permission", "ensure_has_permission", "ensure_entry_add_permissions", "ensure_skip_chapter_permission",
           "ensure_revert_chapter_permission"]

TargetType = Union[Context, User]


def _get_bot_and_target(ctx: TargetType, bot: Optional[Giesela]) -> Tuple[Giesela, TargetType]:
    if isinstance(ctx, Context) and not bot:
        bot = ctx.bot
        if not isinstance(bot, Giesela):
            raise TypeError("Bot from context isn't Giesela, compatible?")

        return bot, ctx

    elif bot:
        return bot, ctx
    else:
        raise TypeError("Bot must be passed if ctx is not a Context!")


async def has_permission(ctx: TargetType, *perms: PermissionType, bot: Giesela = None, global_only: bool = False) -> bool:
    """Check whether has permissions"""
    bot, target = _get_bot_and_target(ctx, bot)
    return await bot.has_permission(target, *perms, global_only=global_only)


async def ensure_has_permission(ctx: TargetType, *perms: PermissionType, bot: Giesela = None, global_only: bool = False) -> None:
    """Make sure permissions are granted"""
    bot, target = _get_bot_and_target(ctx, bot)
    await bot.ensure_permission(target, *perms, global_only=global_only)


async def ensure_entry_add_permissions(ctx: TargetType, entry: Union[PlayableEntry, List[PlayableEntry]], *, bot: Giesela = None) -> None:
    """Make sure an entry can be added to the queue."""
    bot, target = _get_bot_and_target(ctx, bot)

    if isinstance(entry, list):
        if len(entry) > 1:
            await bot.ensure_permission(target, perm_tree.queue.add.playlist)
        else:
            entry = entry[0]

    if entry.is_stream:
        await bot.ensure_permission(target, perm_tree.queue.add.stream)
    else:
        await bot.ensure_permission(target, perm_tree.queue.add.entry)


async def ensure_skip_chapter_permission(ctx: TargetType, player: GieselaPlayer, *, bot: Giesela = None) -> None:
    """Make sure entry can be skipped."""
    bot, target = _get_bot_and_target(ctx, bot)

    current_entry = player.current_entry

    if current_entry and current_entry.has_chapters:
        await bot.ensure_permission(target, perm_tree.player.seek)
    else:
        await bot.ensure_permission(target, perm_tree.player.skip)


async def ensure_revert_chapter_permission(ctx: TargetType, player: GieselaPlayer, *, bot: Giesela = None) -> None:
    """Make sure entry can be reverted."""
    bot, target = _get_bot_and_target(ctx, bot)

    current_entry = player.current_entry

    if current_entry and current_entry.has_chapters:
        await bot.ensure_permission(target, perm_tree.player.seek)
    else:
        await bot.ensure_permission(target, perm_tree.player.revert)
