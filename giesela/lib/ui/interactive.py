import abc
import asyncio
import copy
import inspect
import operator
import textwrap
from asyncio import CancelledError, Future
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from discord import Embed, Message, TextChannel, User

from . import events, utils
from .basic import EditableEmbed
from .utils import EmojiType

EmojiHandlerType = Callable[[EmojiType, User], Awaitable]
_CT = TypeVar("_CT", bound=EmojiHandlerType)


def emoji_handler(*reactions: EmojiType, pos: int = None):
    def decorator(func: _CT) -> _CT:
        func._handles = list(reactions)
        func._pos = pos
        return func

    return decorator


class InteractableEmbed(EditableEmbed):
    user: Optional[User]
    handlers: Dict[EmojiType, EmojiHandlerType]

    _emojis: List[Tuple[EmojiType, int]]
    _stop_signal: bool
    _listener: Future

    def __init__(self, channel: TextChannel, user: User = None):
        super().__init__(channel)

        self.user = user
        self.handlers = {}
        self._emojis = []
        self._stop_signal = False
        self._listener = None

        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            handles = getattr(method, "_handles", None)
            if handles:
                pos = getattr(method, "_pos", None)
                for emoji in handles:
                    self.register_handler(emoji, method, pos=pos)

    @property
    def emojis(self) -> Tuple[EmojiType]:
        self._emojis.sort(key=operator.itemgetter(1))
        return next(zip(*self._emojis), tuple())

    def register_handler(self, emoji: EmojiType, handler: EmojiHandlerType, pos: int = None):
        if emoji in self.handlers:
            raise KeyError(f"There's already a handler for {emoji}")
        self.handlers[emoji] = handler
        if pos is None:
            pos = 10
        self._emojis.append((emoji, pos))

    def stop(self, force=False):
        self._stop_signal = True
        if force and self._listener:
            self._listener.cancel()

    async def add_reactions(self, msg: Message = None):
        if not msg:
            msg = self.message
        for emoji in self.emojis:
            await msg.add_reaction(emoji)

    async def listen_once(self) -> Any:
        if not self.message:
            raise Exception("There's no message to listen to")

        reaction, user = await events.wait_for_reaction_change(emoji=self.emojis, user=self.user, message=self.message)
        emoji = reaction.emoji
        await self.on_any_emoji(emoji, user)

        handler = self.handlers.get(emoji)
        if not handler:
            return await self.on_unhandled_emoji(emoji, user)
        else:
            return await handler(emoji, user)

    async def listen(self) -> Any:
        self._stop_signal = False

        result = None
        while not self._stop_signal:
            self._listener = self.listen_once()
            try:
                result = await self._listener
            except CancelledError:
                pass
        return result

    async def on_any_emoji(self, emoji: EmojiType, user: User):
        pass

    async def on_unhandled_emoji(self, emoji: EmojiType, user: User):
        pass


class _Abortable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def stop(self):
        pass

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        self.stop()
        return None


class _HorizontalPageViewer(InteractableEmbed, metaclass=abc.ABCMeta):
    """
    Keyword Args:
        user: `User` to respond to
        embeds: list of `Embed` to use
        embed_callback: function to call which returns an `Embed` based on the current index
    """
    embeds: Optional[List[Embed]]
    embed_callback: Optional[Callable[[int], Union[Embed, Awaitable[Embed]]]]

    _current_index: int

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        self.embeds = kwargs.pop("embeds", None)
        self.embed_callback = kwargs.pop("embed_callback", None)

        if not (bool(self.embeds) ^ bool(self.embed_callback)):
            raise ValueError("You need to provide either the `embeds` or the `embed_callback` keyword argument")

        self._current_index = 0
        super().__init__(channel, user)

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    async def current_embed(self) -> Embed:
        if self.embeds:
            return self.embeds[self.current_index % len(self.embeds)]
        elif self.embed_callback:
            res = self.embed_callback(self.current_index)

            if asyncio.iscoroutine(res):
                res = await res

            return res

    async def show_page(self):
        next_embed = await self.current_embed
        await self.edit(next_embed, on_new=self.add_reactions)

    async def start(self) -> Any:
        await self.show_page()
        result = await self.listen()
        await self.delete()
        return result

    @emoji_handler("◀")
    async def previous_page(self, *_):
        self._current_index -= 1
        await self.show_page()

    @emoji_handler("▶")
    async def next_page(self, *_):
        self._current_index += 1
        await self.show_page()


class ItemPicker(_HorizontalPageViewer, _Abortable):
    async def choose(self) -> Optional[int]:
        return await self.start()

    @emoji_handler("✅", pos=999)
    async def select(self, *_) -> int:
        self.stop()
        return self.current_index


class EmbedViewer(_HorizontalPageViewer, _Abortable):
    async def display(self) -> None:
        return await self.start()


class VerticalTextViewer(InteractableEmbed, _Abortable):
    """
    Keyword Args:
        embed_frame: Template `Embed` to use
        content: String or list of lines which will be displayed
            When providing a string the following kwargs are applicable:
            window_height: number of lines to show at once
            window_size: Max number of characters to fit in window

        line_callback: Callable which takes returns the content of a line
            when given its index

        window_height: Amount of lines to display at once
        window_length: Max amount of characters to show at once
        scroll_amount: Amount of lines to scroll
    """
    embed_frame: Dict[str, Any]
    lines: List[str]
    line_callback: Callable[[int], Union[str, Awaitable[str]]]

    window_height: int
    max_window_length: int
    scroll_amount: int

    _current_line: int
    _lines_displayed: int

    def __init__(self, channel: TextChannel, user: User, **kwargs):
        self.embed_frame = kwargs.pop("embed_frame", None)
        if isinstance(self.embed_frame, Embed):
            self.embed_frame = self.embed_frame.to_dict()

        self.lines = kwargs.pop("content", None)
        if isinstance(self.lines, str):
            self.window_width = kwargs.pop("window_width", 75)
            self.lines = self.split_content(self.lines, self.window_width)
        else:
            self.window_width = max(len(line) for line in self.lines)

        self.line_callback = kwargs.pop("line_callback", None)

        self.window_height = kwargs.pop("window_height", 20)
        self.max_window_length = kwargs.pop("max_window_length", 2000)

        self.scroll_amount = kwargs.pop("scroll_amount", self.window_height // 2)

        if not (bool(self.lines) ^ bool(self.line_callback)):
            raise ValueError("You need to provide either the `content` or the `content_callback` keyword argument")

        self._current_line = 0
        self._lines_displayed = 0
        super().__init__(channel, user)

    @property
    def current_line(self) -> int:
        return self._current_line

    @property
    def lines_displayed(self) -> int:
        return self._lines_displayed

    @property
    def total_lines(self) -> Optional[int]:
        if self.lines:
            return len(self.lines)

    @property
    async def current_content(self) -> str:
        lines = []
        _current_length = 0
        _current_line = self.current_line

        while len(lines) < self.window_height:
            if self.lines and _current_line >= len(self.lines):
                break

            line = await self.get_line(_current_line)
            if _current_length + len(line) <= self.max_window_length:
                lines.append(line)
                _current_length += len(line)
                _current_line += 1
            else:
                break

        if not lines:
            if self.lines:
                raise ValueError(f"One of the provided lines is too long to be displayed within {self.max_window_length} chars")
            elif self.line_callback:
                raise ValueError(f"Callback {self.line_callback} provided line that can't be displayed within {self.max_window_length} chars")

        self._lines_displayed = len(lines)
        return "\n".join(lines)

    @property
    async def current_embed(self) -> Embed:
        content = await self.current_content

        if self.embed_frame:
            embed = copy.deepcopy(self.embed_frame)
            embed = Embed.from_data(embed)
        else:
            embed = Embed()
            embed.set_footer()

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
        _progress = (self.current_line + self.lines_displayed) / self.total_lines
        f_args = dict(viewer=self,
                      current_line=self.current_line + 1,
                      total_lines=self.total_lines,
                      progress_bar=utils.create_bar(_progress, min(self.window_width, 30)))

        def format_rich(rich: str, attr: str):
            nonlocal embed, f_args
            _rich = getattr(embed, rich, None)
            if _rich:
                if attr in _rich:
                    _rich[attr] = _rich[attr].format(**f_args)

        format_rich("_author", "name")
        format_rich("_footer", "text")

        if embed.description:
            embed.description = embed.description.format(**f_args)
        return embed

    async def get_line(self, line: int) -> str:
        if self.lines:
            return self.lines[line]
        else:
            content = self.line_callback(line)
            if asyncio.iscoroutine(content):
                content = await content
            return content

    async def display(self) -> None:
        await self.show_window()
        await self.listen()
        await self.delete()

    async def show_window(self):
        next_embed = await self.current_embed
        await self.edit(next_embed, on_new=self.add_reactions)

    @emoji_handler("🔼")
    async def scroll_up(self, *_):
        if self.lines:
            self._current_line = max(0, self._current_line - self.scroll_amount)
        else:
            self._current_line -= self.scroll_amount
        await self.show_window()

    @emoji_handler("🔽")
    async def scroll_down(self, *_):
        if self.lines:
            self._current_line = min(len(self.lines) - 1, self._current_line + self.scroll_amount)
        else:
            self._current_line += self.scroll_amount
        await self.show_window()
