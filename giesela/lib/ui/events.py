import asyncio

from discord import Emoji

_reaction_listeners = []


async def handle_reaction(reaction, user):
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


async def wait_for_reaction_change(emoji=None, *, user=None, timeout=None, message=None, check=None):
    global _reaction_listeners

    if emoji is None:
        emoji_check = lambda r: True
    elif isinstance(emoji, (str, Emoji)):
        emoji_check = lambda r: r.emoji == emoji
    else:
        emoji_check = lambda r: r.emoji in emoji

    def predicate(reaction, reaction_user):
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
