import asyncio
from typing import Callable, Iterable, Union

from discord import Emoji, Message, Reaction, User

from .utils import EmojiType

_reaction_listeners = []


async def handle_reaction(reaction: Reaction, user: User):
    global _reaction_listeners

    removed = []

    for i, (condition, future) in enumerate(_reaction_listeners):
        if future.cancelled():
            removed.append(i)
            continue

        try:
            result = condition(reaction, user)
        except Exception as e:
            future.set_exception(e)
            removed.append(i)
        else:
            if result:
                future.set_result((reaction, user))
                removed.append(i)

    for idx in reversed(removed):
        del _reaction_listeners[idx]


async def wait_for_reaction_change(emoji: Union[EmojiType, Iterable[EmojiType]] = None, *, user: User = None, timeout: float = None,
                                   message: Message = None, check: Callable[[Reaction, User], bool] = None):
    global _reaction_listeners

    if emoji is None:
        def emoji_check(*_) -> True:
            return True
    elif isinstance(emoji, (str, Emoji)):
        def emoji_check(r: Reaction) -> bool:
            return r.emoji == emoji
    else:
        def emoji_check(r: Reaction) -> bool:
            return r.emoji in emoji

    def predicate(reaction: Reaction, reaction_user: User) -> bool:
        result = emoji_check(reaction)

        if message is not None:
            result = result and message.id == reaction.message.id

        if user is not None:
            result = result and user.id == reaction_user.id

        if callable(check):
            # the exception thrown by check is propagated through the future.
            result = result and check(reaction, reaction_user)

        return result

    future = asyncio.Future()
    _reaction_listeners.append((predicate, future))

    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        return None
