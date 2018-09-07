import abc
import asyncio
import copy
import inspect
import logging
import operator
import textwrap
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from discord import Client, Embed, Message, Reaction, TextChannel, User
from discord.ext.commands import Command, CommandError, CommandInvokeError, Context
from discord.ext.commands.bot import BotBase

from . import events, text
from .abstract import HasListener, MessageHandler, ReactionHandler, Startable, Stoppable
from .basic import EditableEmbed
from .utils import EmbedLimits, EmojiType, MenuCommandGroup, format_embed

log = logging.getLogger(__name__)

EmojiHandlerType = Callable[[EmojiType, User], Awaitable]

_CT = TypeVar("_CT", bound=EmojiHandlerType)


def emoji_handler(*reactions: EmojiType, pos: int = None):
    def decorator(func: _CT) -> _CT:
        func._handles = list(reactions)
        func._pos = pos
        return func

    return decorator


class InteractableEmbed(HasListener, EditableEmbed, ReactionHandler, Startable, Stoppable):
    user: Optional[User]
    handlers: Dict[EmojiType, EmojiHandlerType]

    _emojis: List[Tuple[EmojiType, int]]

    def __init__(self, channel: TextChannel, *, user: User = None, **kwargs):
        super().__init__(channel, **kwargs)
        self.user = user
        self.handlers = {}
        self._emojis = []

        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            handles = getattr(method, "_handles", None)
            if handles:
                pos = getattr(method, "_pos", None)
                for emoji in handles:
                    self.register_handler(emoji, method, pos=pos)

        self.create_listener("reactions", listen_once=self.wait_for_reaction)

    @property
    def emojis(self) -> Tuple[EmojiType]:
        self._emojis.sort(key=operator.itemgetter(1))
        return next(zip(*self._emojis), tuple())

    @property
    def result(self) -> Any:
        return self.listener_result("reactions", None)

    def register_handler(self, emoji: EmojiType, handler: EmojiHandlerType, pos: int = None):
        if emoji in self.handlers:
            raise KeyError(f"There's already a handler for {emoji}")
        self.handlers[emoji] = handler
        if pos is None:
            pos = 10
        self._emojis.append((emoji, pos))

    async def remove_handler(self, handler: Union[EmojiType, List[EmojiType], EmojiHandlerType]):
        emojis = self.disable_handler(handler)
        futures = []

        for emoji in emojis:
            fut = asyncio.ensure_future(self.remove_reaction(emoji))
            futures.append(fut)

        await asyncio.gather(*futures)

    def disable_handler(self, handler: Union[EmojiType, List[EmojiType], EmojiHandlerType]) -> List[EmojiType]:
        if isinstance(handler, Callable):
            emojis = getattr(handler, "_handles", None)
            if not emojis:
                raise ValueError(f"{handler} doesn't handle any emoji")
        elif isinstance(handler, list):
            emojis = handler
        else:
            emojis = [handler]

        for emoji in emojis:
            _handler = self.handlers[emoji]
            func = getattr(_handler, "__func__", _handler)
            setattr(func, "_disabled", True)
        return emojis

    def is_disabled(self, handler: Union[EmojiType, EmojiHandlerType]) -> bool:
        if isinstance(handler, EmojiType.__args__):
            handler = self.handlers[handler]
        func = getattr(handler, "__func__", handler)
        return getattr(func, "_disabled", False)

    async def delete(self):
        await self.stop()
        await super().delete()

    async def _add_reaction(self, emoji: EmojiType, msg: Message = None):
        msg = msg or self.message
        if not self.is_disabled(emoji):
            await msg.add_reaction(emoji)

    async def add_reactions(self, msg: Message = None):
        msg = msg or self.message
        for emoji in self.emojis:
            await self._add_reaction(emoji, msg)

    def plan_add_reactions(self, msg: Message = None):
        asyncio.ensure_future(self.add_reactions(msg))

    async def edit(self, embed: Embed, on_new: Callable[[Message], Any] = None):
        await super().edit(embed, on_new or self.plan_add_reactions)

    async def remove_reaction(self, emoji: EmojiType):
        if not self.message:
            return

        await self.update_message_state()

        for reaction in self.message.reactions:
            if reaction.emoji == emoji:
                break
        else:
            return

        async for user in reaction.users():
            await self.message.remove_reaction(emoji, user)

    async def wait_for_reaction(self) -> Any:
        if not self.message:
            raise Exception("There's no message to listen to")

        reaction, user = await events.wait_for_reaction_change(emoji=self.emojis, user=self.user, message=self.message)
        try:
            return await self.on_reaction(reaction, user)
        except Exception as e:
            return await self.on_emoji_handler_error(e, reaction, user)

    @classmethod
    async def _try_run_coro(cls, coro):
        try:
            await coro
        except Exception:
            log.error(f"Error while running {coro}")

    @classmethod
    def try_run(cls, coro):
        asyncio.ensure_future(cls._try_run_coro(coro))

    async def on_reaction(self, reaction: Reaction, user: User) -> Any:
        await super().on_reaction(reaction, user)
        emoji = reaction.emoji
        self.try_run(self.on_any_emoji(emoji, user))

        handler = self.handlers.get(emoji)
        if hasattr(handler, "_disabled"):
            return

        if not handler:
            return await self.on_unhandled_emoji(emoji, user)
        else:
            return await handler(emoji, user)

    async def on_any_emoji(self, emoji: EmojiType, user: User):
        pass

    async def on_unhandled_emoji(self, emoji: EmojiType, user: User):
        pass

    async def on_emoji_handler_error(self, error: Exception, reaction: Reaction, user: User):
        log.exception(f"Something went wrong while handling {reaction} by {user}", exc_info=error)


class MessageableEmbed(HasListener, EditableEmbed, MessageHandler, Startable, Stoppable):
    """
    Keyword Args:
        bot: `discord.Client`. Bot to use for receiving messages.
        delete_msgs: Optional `bool`. Whether to delete incoming messages.
    """

    bot: Client
    user: Optional[User]

    _group: MenuCommandGroup
    error: Optional[str]

    def __init__(self, channel: TextChannel, *, user: User = None, **kwargs):
        self.bot = kwargs.pop("bot")
        self.delete_msgs = kwargs.pop("delete_msgs", True)
        self._group = MenuCommandGroup(self.bot)
        self.error = None

        for name, member in inspect.getmembers(self):
            if isinstance(member, Command):
                if member.parent is None:
                    self._group.add_command(member)
            elif name.startswith("on_") and member != self.on_message:
                self._group.add_listener(member)

        super().__init__(channel, **kwargs)

        self.user = user
        self.create_listener("messages", listen_once=self.wait_for_message)

    @property
    def menu_command(self) -> MenuCommandGroup:
        return self._group

    @property
    def commands(self) -> List[Command]:
        return self._group.commands

    async def stop(self):
        self.cancel_listener("messages")
        await super().stop()

    async def delete(self):
        await self.stop()
        await super().delete()

    def message_check(self, message: Message) -> bool:
        if self.user and message.author.id != self.user.id:
            return False

        return True

    async def wait_for_message(self) -> Any:
        while True:
            # noinspection PyUnresolvedReferences
            msg = await self.bot.wait_for("message", check=self.message_check)

            if isinstance(self.bot, BotBase):
                ctx = await self.bot.get_context(msg)
                if ctx.invoked_with:
                    continue
            break

        return await self.on_message(msg)

    @classmethod
    async def on_error(cls, event: str, *args, **kwargs):
        log.exception(f"Error in {event} ({args}, {kwargs})")

    async def on_command_error(self, ctx: Context, exception: Exception):
        report = False
        if isinstance(exception, CommandError):
            if isinstance(exception, CommandInvokeError):
                original = exception.original

                self.error = f"Internal Error: ```python\n{original!r}```"
                report = True
            else:
                self.error = str(exception)

        log.exception("CommandError:", exc_info=exception, extra=dict(report=report))

    async def on_message(self, message: Message):
        await super().on_message(message)

        if self.delete_msgs:
            asyncio.ensure_future(message.delete())

        await self._group.process_commands(message)


class Abortable(HasListener, metaclass=abc.ABCMeta):
    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Abort"""
        self.stop_listener()
        return None


class _HorizontalPageViewer(InteractableEmbed, metaclass=abc.ABCMeta):
    """
    Keyword Args:
        embeds: list of `Embed` to use
            no_controls_for_single_page: `bool`. Don't show page controls when only one embed
        embed_callback: function to call which returns an `Embed` based on the current index
    """
    embeds: Optional[List[Embed]]
    embed_callback: Optional[Callable[[int], Union[Embed, Awaitable[Embed]]]]

    _current_index: int

    def __init__(self, channel: TextChannel, **kwargs):
        self.embeds = kwargs.pop("embeds", None)
        no_controls_for_single_page = kwargs.pop("no_controls_for_single_page", True)

        self.embed_callback = kwargs.pop("embed_callback", None)

        if not (issubclass(type(self), _HorizontalPageViewer) or bool(self.embeds) ^ bool(self.embed_callback)):
            raise ValueError("You need to provide either the `embeds` or the `embed_callback` keyword argument")

        super().__init__(channel, **kwargs)

        if self.embeds and len(self.embeds) == 1 and no_controls_for_single_page:
            self.disable_handler(self.previous_page)
            self.disable_handler(self.next_page)

        self._current_index = 0

    @property
    def current_index(self) -> int:
        return self._current_index

    def set_index(self, index: int):
        self._current_index = index

    async def get_current_embed(self) -> Embed:
        if self.embeds:
            return self.embeds[self.current_index % len(self.embeds)]
        elif self.embed_callback:
            res = self.embed_callback(self.current_index)

            if asyncio.iscoroutine(res):
                res = await res

            return res
        else:
            raise Exception("Didn't override \"get_current_embed\" or provide any form of content")

    async def show_page(self):
        next_embed = await self.get_current_embed()
        await self.edit(next_embed)

    async def start(self) -> Any:
        await self.show_page()
        await super().start()

    async def display(self) -> Any:
        await self.start()
        result = await self.wait_for_listener()
        await self.delete()
        return result

    @emoji_handler("◀", pos=1)
    async def previous_page(self, *_):
        """Switch to the previous page"""
        self._current_index -= 1
        await self.show_page()

    @emoji_handler("▶", pos=2)
    async def next_page(self, *_):
        """Switch to the next page"""
        self._current_index += 1
        await self.show_page()


class ItemPicker(_HorizontalPageViewer, Abortable):
    async def choose(self) -> Optional[int]:
        return await self.display()

    @emoji_handler("✅", pos=999)
    async def select(self, *_) -> int:
        self.stop_listener()
        return self.current_index


class EmbedViewer(_HorizontalPageViewer, Abortable):
    pass


class VerticalTextViewer(InteractableEmbed, Abortable, Startable):
    """
    Keyword Args:
        embed_frame: Template `Embed` to use
        content: String or list of lines which will be displayed
            When providing a string the following kwargs are applicable:
            window_height: number of lines to show at once
            window_size: Max number of characters to fit in window
        no_controls_for_single_page: Whether to show buttons for embeds which can't be scrolled

        line_callback: Callable which takes returns the content of a line
            when given its index

        window_height: Amount of lines to display at once
        window_length: Max amount of characters to show at once
        scroll_amount: Amount of lines to scroll
    """
    _embed_frame: Dict[str, Any]
    lines: List[str]
    line_callback: Callable[[int], Union[str, Awaitable[str]]]

    window_height: int
    max_window_length: int
    scroll_amount: int

    _current_line: int
    _lines_displayed: int

    def __init__(self, channel: TextChannel, **kwargs):
        self._embed_frame = kwargs.pop("embed_frame", None)
        if isinstance(self._embed_frame, Embed):
            self._embed_frame = self._embed_frame.to_dict()

        self.lines = kwargs.pop("content", None)
        self.window_width = kwargs.pop("window_width", 75)
        if isinstance(self.lines, str):
            self.lines = self.split_content(self.lines, self.window_width)
        elif self.lines:
            self.window_width = max(len(line) for line in self.lines)

        no_controls_for_single_page = kwargs.pop("no_controls_for_single_page", True)

        self.line_callback = kwargs.pop("line_callback", None)

        self.window_height = kwargs.pop("window_height", 20)
        self.max_window_length = kwargs.pop("max_window_length", EmbedLimits.DESCRIPTION_LIMIT)

        self.scroll_amount = kwargs.pop("scroll_amount", max(self.window_height // 3, 1))

        if not (issubclass(type(self), VerticalTextViewer) or bool(self.lines) ^ bool(self.line_callback)):
            raise ValueError("You need to provide either the `content` or the `content_callback` keyword argument")

        super().__init__(channel, **kwargs)

        self._current_line = 0
        self._lines_displayed = 0
        self._ran_out_of_lines = False

        if self.lines and no_controls_for_single_page:
            if len(self.lines) <= self.window_height and sum(map(len, self.lines)) <= self.max_window_length:
                log.info("Not showing scroll controls because Embed only one page")
                self.disable_handler(self.scroll_up)
                self.disable_handler(self.scroll_down)

    @property
    def current_line(self) -> int:
        return self._current_line

    @property
    def embed_frame(self) -> Embed:
        if self._embed_frame:
            embed = copy.deepcopy(self._embed_frame)
            embed = Embed.from_data(embed)
        else:
            embed = Embed()
            embed.set_footer(text="{progress_bar}")
        return embed

    @property
    def lines_displayed(self) -> int:
        return self._lines_displayed

    @property
    def first_line_visible(self) -> bool:
        return self.current_line == 0

    @property
    def last_line_visible(self) -> bool:
        if self.total_lines:
            return self.current_line + self.lines_displayed >= self.total_lines
        return False

    @property
    def total_lines(self) -> Optional[int]:
        if self.lines:
            return len(self.lines)

    async def get_current_content(self) -> str:
        lines = []
        _current_length = 0
        _current_line = self.current_line

        while len(lines) < self.window_height:
            if self.total_lines is not None and _current_line >= self.total_lines:
                self._ran_out_of_lines = True
                break

            line = await self.get_line(_current_line)
            if _current_length + len(line) <= self.max_window_length:
                lines.append(line)
                _current_length += len(line)
                _current_line += 1
            else:
                self._ran_out_of_lines = False
                break

        if not lines:
            if self.total_lines:
                raise ValueError(f"One of the provided lines is too long to be displayed within {self.max_window_length} chars")
            elif self.line_callback:
                raise ValueError(f"Callback {self.line_callback} provided line that can't be displayed within {self.max_window_length} chars")

        self._lines_displayed = len(lines)
        return "\n".join(lines)

    async def get_current_embed(self) -> Embed:
        content = await self.get_current_content()
        embed = self.embed_frame
        embed = self.format_embed(embed)
        embed.description = content
        return embed

    @classmethod
    def split_content(cls, content: str, width: int) -> List[str]:
        lines = []
        _lines = content.splitlines()

        wrapper = textwrap.TextWrapper(width=width, subsequent_indent="\t", tabsize=4)

        for line in _lines:
            if len(line) > width:
                lines.extend(wrapper.wrap(line))
            else:
                lines.append(line)
        return lines

    def format_embed(self, embed: Embed) -> Embed:
        _progress = (self.current_line / self.total_lines) if self.total_lines else 0
        _visible = (self.lines_displayed / self.total_lines) if self.total_lines else 1
        progress_bar = text.keep_whitespace(text.create_scroll_bar(_progress, _visible, min(self.window_width, 30)))

        return format_embed(embed, _copy=False,
                            viewer=self,
                            current_line=self.current_line + 1,
                            total_lines=self.total_lines,
                            progress_bar=progress_bar)

    async def get_line(self, line: int) -> str:
        if self.lines:
            return self.lines[line]
        elif self.line_callback:
            content = self.line_callback(line)
            if asyncio.iscoroutine(content):
                content = await content
            return content
        else:
            raise Exception(f"{self} didn't override `get_line` or provide any form of content!")

    async def start(self):
        await self.show_window()
        await super().start()

    async def display(self) -> Any:
        await self.show_window()
        res = await self.wait_for_listener()
        await self.delete()
        return res

    async def show_window(self):
        next_embed = await self.get_current_embed()
        await self.edit(next_embed)

    def set_focus_line(self, line: int):
        displayed = self._lines_displayed or self.window_height
        if self._ran_out_of_lines and self.total_lines:
            displayed = self.total_lines
        self._current_line = max(line - (displayed // 2), 0)

    async def show_line(self, line: int):
        self.set_focus_line(line)
        await self.show_window()

    @emoji_handler("🔼", pos=2)
    async def scroll_up(self, *_):
        """Scroll up"""
        if self.first_line_visible:
            return

        if self.total_lines:
            self._current_line = max(0, self._current_line - self.scroll_amount)
        else:
            self._current_line -= self.scroll_amount
        await self.show_window()

    @emoji_handler("🔽", pos=1)
    async def scroll_down(self, *_):
        """Scroll down"""
        if self.last_line_visible:
            return

        if self.total_lines:
            self._current_line = min(self.total_lines - 1, self._current_line + self.scroll_amount)
        else:
            self._current_line += self.scroll_amount
        await self.show_window()
