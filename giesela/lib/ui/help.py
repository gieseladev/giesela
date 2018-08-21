import abc
import asyncio
import inspect
import logging
from collections import OrderedDict
from typing import Dict, Optional, Type

from discord import Colour, Embed, TextChannel, User
from discord.ext.commands import Context

from giesela.cogs.info import help_formatter
from . import text
from .abstract import Stoppable
from .interactive import InteractableEmbed, MessageableEmbed, emoji_handler

log = logging.getLogger(__name__)


def get_short_doc(target) -> Optional[str]:
    doc = inspect.getdoc(target)
    if not doc:
        return None
    first_line = doc.splitlines()[0]
    return first_line


def get_doc_list(doc: Dict[str, str], width: int = 80, *, pad_width: int = None) -> str:
    pad_width = pad_width or max(len(key) for key in doc.keys())

    lines = []
    for name, docstring in doc.items():
        line = f"{name:<{pad_width}} | {docstring}"
        lines.append(text.shorten(line, width))

    value = "\n".join(lines)
    return f"```css\n{value}```"


def get_reaction_help(target: InteractableEmbed, *, include_undocumented: bool = False) -> str:
    handlers = []
    for emoji in target.emojis:
        handler = target.handlers[emoji]
        if handler not in handlers:
            handlers.append(getattr(handler, "__func__", handler))

    doc = OrderedDict()
    pad_width = 0

    for handler in handlers:
        docstring = get_short_doc(handler)
        if not docstring:
            if include_undocumented:
                docstring = "Undocumented button"
            else:
                continue

        handles = handler._handles
        if len(handles) == 1:
            name = handles[0]
        else:
            name = f"[{'|'.join(handles)}]"

        if len(name) > pad_width:
            pad_width = len(name)

        doc[name] = docstring
    return get_doc_list(doc, pad_width=pad_width)


def get_message_help(target: MessageableEmbed) -> str:
    commands = target.commands
    return get_doc_list({cmd.name: cmd.short_doc for cmd in commands})


async def get_command_help(ctx: Context, *cmds: str) -> Optional[Embed]:
    def _command_not_found(_name: str):
        return Embed(description=f"No command called **{_name}**", colour=Colour.red())

    bot = ctx.bot
    if len(cmds) == 0:
        return None
    elif len(cmds) == 1:
        # try to see if it is a cog name
        name = cmds[0]
        if name in bot.cogs:
            cmd = bot.cogs[name]
        else:
            cmd = bot.all_commands.get(name)
            if cmd is None:
                return _command_not_found(name)
    else:
        # handle groups
        name = cmds[0]
        cmd = bot.all_commands.get(name)
        if cmd is None:
            return _command_not_found(name)

        for key in cmds[1:]:
            try:
                cmd = cmd.all_commands.get(key)
                if cmd is None:
                    return _command_not_found(key)
            except AttributeError:
                em = Embed(description=f"Command **{cmd.name}** has no subcommands", colour=Colour.red())
                return em

    embeds = await help_formatter.format_help_for(ctx, cmd)
    return embeds[0]


class HelpEmbed(InteractableEmbed):
    help_embed: Embed

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        self.help_embed = kwargs.pop("help_embed")
        super().__init__(channel, user, **kwargs)

    def __await__(self):
        return self.display().__await__()

    async def display(self, embed: Embed = None):
        await self.edit(embed or self.help_embed)
        await self.wait_for_listener("reactions")
        await self.delete()

    @emoji_handler("❌")
    async def close_help(self, *_):
        self.stop_listener("reactions")


class HasHelp(Stoppable, metaclass=abc.ABCMeta):
    _showing_custom: bool
    _current_help: Optional[HelpEmbed]
    _help_embed: Optional[Embed]
    _help_embed_cls: Type[HelpEmbed]

    def __init__(self, *args, **kwargs):
        self._showing_custom = False
        self._current_help = None
        self._help_embed = None
        self._help_embed_cls = kwargs.pop("help_embed_cls", HelpEmbed)
        super().__init__(*args, **kwargs)

    @property
    def _showing_help(self) -> bool:
        return bool(self._current_help and self._current_help.message)

    async def stop(self):
        if self._current_help:
            await self._current_help.delete()
        await super().stop()

    @abc.abstractmethod
    def get_help_embed(self) -> Embed:
        pass

    async def show_help_embed(self, channel: TextChannel, user: User = None, *, embed: Embed = None):
        if self._showing_help and not (embed or self._showing_custom):
            return

        if embed:
            self._showing_custom = True
        else:
            self._showing_custom = False
            if not self._help_embed:
                self._help_embed = self.get_help_embed()
            embed = self._help_embed

        if self._current_help:
            await self._current_help.stop()
            return await self._current_help.display(embed)
        else:
            self._current_help = self._help_embed_cls(channel, user, help_embed=embed)
            return await self._current_help.display()

    def trigger_help_embed(self, *args, **kwargs):
        return asyncio.ensure_future(self.show_help_embed(*args, **kwargs))
