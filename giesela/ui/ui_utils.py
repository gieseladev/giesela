import asyncio
import inspect
import logging
from typing import Callable, Dict, List, TYPE_CHECKING, Union

from discord import Client, Embed, Emoji
from discord.ext.commands import Command, Context
from discord.ext.commands.bot import BotBase

if TYPE_CHECKING:
    from giesela import Giesela

__all__ = ["EmojiType", "EmbedLimits", "copy_embed", "format_embed", "count_embed_chars", "CustomParamsCommand", "MenuCommandGroup"]

log = logging.getLogger(__name__)

EmojiType = Union[Emoji, str]


class EmbedLimits:
    TITLE_LIMIT = 256
    DESCRIPTION_LIMIT = 2048
    FIELDS_LIMIT = 25
    FIELD_NAME_LIMIT = 256
    FIELD_VALUE_LIMIT = 1024
    FOOTER_TEXT_LIMIT = 2048
    AUTHOR_NAME_LIMIT = 256

    CHAR_LIMIT = 6000


def copy_embed(embed: Embed) -> Embed:
    return Embed.from_data(embed.to_dict())


def format_embed(embed: Embed, _copy=True, **fmt) -> Embed:
    if _copy:
        embed = copy_embed(embed)

    if embed.title:
        embed.title = embed.title.format(**fmt)

    if embed.description:
        embed.description = embed.description.format(**fmt)

    if embed.author.name:
        embed.set_author(name=embed.author.name.format(**fmt), url=embed.author.url, icon_url=embed.author.icon_url)

    if embed.footer.text:
        embed.set_footer(text=embed.footer.text.format(**fmt), icon_url=embed.footer.icon_url)

    for i, field in enumerate(embed.fields):
        embed.set_field_at(i, name=field.name.format(**fmt), value=field.value.format(**fmt), inline=field.inline)

    return embed


def count_embed_chars(embed: Embed) -> int:
    count = 0

    if embed.title:
        count += len(embed.title)

    if embed.description:
        count += len(embed.description)

    if embed.author.name:
        count += len(embed.author.name)

    if embed.footer.text:
        count += len(embed.footer.text)

    count += sum(len(field.name) + len(field.value) for field in embed.fields)

    return count


class _FakeClient:
    _listeners: Dict[str, Callable]

    def __init__(self, *args, loop=None, **kwargs) -> None:
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self._listeners = {}

    dispatch = Client.dispatch
    _run_event = getattr(Client, "_run_event")


class CustomParamsCommand(Command):
    def __init__(self, name: str, callback: Callable, params: Dict[str, inspect.Parameter], **kwargs) -> None:
        super().__init__(name, callback, **kwargs)
        self.params = params

    @property
    def callback(self) -> Callable:
        return self._callback

    @callback.setter
    def callback(self, value: Callable):
        self._callback = value


class MenuCommandGroup(BotBase, _FakeClient):
    """
    Keyword Args:
        keep_default_help: `bool`. Defaults to `False`.
    """
    _dynamic_commands: List[str]

    def __init__(self, bot: Client, **kwargs) -> None:
        self.bot = bot
        keep_default_help = kwargs.pop("keep_default_help", False)
        super().__init__("", **kwargs)
        self.user = bot.user
        if not keep_default_help:
            self.remove_command("help")

        self._dynamic_commands = []
        self.check_once(self._permission_check)

    def __getattr__(self, item):
        return getattr(self.bot, item)

    async def invoke(self, ctx: Context):
        ctx.client = self.bot
        await super().invoke(ctx)

    async def _permission_check(self, ctx: Context) -> bool:
        from giesela.permission import get_decorated_permissions

        bot: "Giesela" = self.bot

        return all((
            await bot.ensure_permission(ctx, *get_decorated_permissions(ctx.command, global_only=True), global_only=True),
            await bot.ensure_permission(ctx, *get_decorated_permissions(ctx.command, global_only=False), global_only=False),
        ))

    def add_dynamic_command(self, cmd: Command):
        self.add_command(cmd)
        self._dynamic_commands.append(cmd.name)

    def clear_dynamic_commands(self):
        for cmd_name in self._dynamic_commands:
            self.remove_command(cmd_name)
        self._dynamic_commands.clear()
