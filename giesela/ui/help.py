import abc
import asyncio
import inspect
import logging
from collections import OrderedDict
from typing import Dict, Optional, Type

from discord import Colour, Embed, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela.lib import help_formatter
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

        handles = getattr(handler, "_handles")
        if len(handles) == 1:
            name = handles[0]
        else:
            name = f"[{'|'.join(handles)}]"

        if len(name) > pad_width:
            pad_width = len(name)

        doc[name] = docstring
    return get_doc_list(doc, pad_width=pad_width)


def get_message_help(target: MessageableEmbed) -> str:
    command_list = target.commands
    return get_doc_list({cmd.name: cmd.short_doc for cmd in command_list})


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

    def __init__(self, channel: TextChannel, *, help_embed: Embed, **kwargs) -> None:
        self.help_embed = help_embed
        super().__init__(channel, **kwargs)

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

    def __init__(self, *args, **kwargs) -> None:
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

    async def show_help_embed(self, channel: TextChannel, *, embed: Embed = None, **kwargs):
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
            self._current_help = self._help_embed_cls(channel, help_embed=embed, **kwargs)
            return await self._current_help.display()

    def toggle_help_embed(self, channel: TextChannel, **kwargs):
        if self._showing_help:
            task = asyncio.ensure_future(self._current_help.delete())
        else:
            task = self.trigger_help_embed(channel, **kwargs)
        return task

    def trigger_help_embed(self, channel: TextChannel, **kwargs):
        return asyncio.ensure_future(self.show_help_embed(channel, **kwargs))


class AutoHelpEmbed(HasHelp, metaclass=abc.ABCMeta):
    channel: TextChannel

    @property
    def help_title(self) -> str:
        return f"{type(self).__name__} Help"

    @property
    def help_description(self) -> Optional[str]:
        return None

    def get_help_embed(self) -> Embed:
        embed = Embed(title=self.help_title, description=self.help_description, colour=Colour.blue())

        if isinstance(self, InteractableEmbed):
            reaction_help = get_reaction_help(self)
            embed.add_field(name="Buttons", value=reaction_help)

        if isinstance(self, MessageableEmbed):
            message_help = get_message_help(self)
            embed.add_field(name="Commands", value=message_help, inline=False)

        return embed

    @emoji_handler("❓", pos=10000)
    async def show_help(self, _, user: User):
        """Open this very box"""
        self.toggle_help_embed(self.channel, user=user)

    @commands.command()
    async def help(self, ctx: Context, *cmds: str):
        """Even more help"""
        if not cmds:
            self.toggle_help_embed(self.channel, user=ctx.author)
            return

        embed = await get_command_help(ctx, *cmds)
        self.trigger_help_embed(self.channel, user=ctx.author, embed=embed)
