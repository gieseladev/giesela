import asyncio
import copy
import logging
import operator
from textwrap import indent, wrap
from typing import Iterable, List, Optional, Tuple, Type

import aiohttp
from discord import Colour, Embed, Message
from discord.ext.commands import AutoShardedBot, Command, CommandError, CommandInvokeError, CommandNotFound, Context

from giesela.lib.web_author import WebAuthor
from giesela.ui import events
from . import cogs, exceptions, utils
from .config import Config, ConfigDefaults
from .constants import VERSION as BOT_VERSION

log = logging.getLogger(__name__)


class GieselaContext(Context):
    _sent_messages: List[Message]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sent_messages = []

    async def send(self, *args, **kwargs) -> Message:
        msg = await super().send(*args, **kwargs)
        self._sent_messages.append(msg)
        return msg

    async def decay(self):
        coros = (self.message.delete(), *map(operator.methodcaller("delete"), self._sent_messages))
        await asyncio.gather(*coros, return_exceptions=True)


class Giesela(AutoShardedBot):
    config: Config
    aiosession: aiohttp.ClientSession

    exit_signal: Optional[Type[exceptions.Signal]]

    def __init__(self, *args, **kwargs):
        self.config = Config(ConfigDefaults.options_file)

        super().__init__(self.config.command_prefix, *args, **kwargs)
        WebAuthor.bot = self

        self.exit_signal = None
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += f" Giesela/{BOT_VERSION}"

        for ext in cogs.get_extensions():
            log.info(f"loading extension {ext}")
            self.load_extension(ext)

    async def logout(self):
        self.dispatch("logout")
        await self.aiosession.close()
        await super().logout()

    def run(self):
        try:
            super().run(self.config.token)
        finally:
            if self.exit_signal:
                raise self.exit_signal

    async def on_message(self, message: Message):
        content = message.content
        if "&&" in content:
            await self.chain_commands(message)
        else:
            await super().on_message(message)

    async def chain_commands(self, message: Message, commands: Iterable[str] = None):
        if not commands:
            commands = map(str.lstrip, message.content.split("&&"))

        for command in commands:
            msg = copy.copy(message)
            msg.content = command
            await self.on_message(msg)

    def find_commands(self, query: str, *, threshold: float = .5) -> List[Tuple[Command, float]]:
        commands = []

        for command in self.walk_commands():
            similarity = utils.similarity(query, (command.name, command.help), lower=True)
            if similarity > threshold:
                commands.append((command, similarity))
        commands.sort(key=operator.itemgetter(1), reverse=True)
        return commands

    async def get_context(self, message: Message, *, cls: Context = GieselaContext) -> Context:
        return await super().get_context(message, cls=cls)

    @classmethod
    async def on_command(cls, ctx: Context):
        if ctx.command:
            log.debug(f"{ctx.author} invoked {ctx.command.qualified_name}")

    async def on_command_finished(self, ctx: Context, **_):
        if isinstance(ctx, GieselaContext):
            await asyncio.sleep(self.config.message_decay_delay)
            await ctx.decay()

    async def on_command_completion(self, ctx: Context):
        self.dispatch("command_finished", ctx)

    async def on_command_error(self, ctx: Context, exception: Exception):
        report = True

        if isinstance(exception, CommandError):
            if isinstance(exception, CommandInvokeError):
                original = exception.original

                if isinstance(original, exceptions.Signal):
                    self.exit_signal = type(original)
                    await self.logout()
                    return

                description = "There was an internal error while processing your command." \
                              "This shouldn't happen (obviously) and it isn't your fault *(maybe)*.\n"

                embed = Embed(title="Internal Error", description=description, colour=Colour.red())
                embed.add_field(name="Please ask someone (who knows their shit) to take a look at this:",
                                value=f"```python\n{original!r}```",
                                inline=False)
            else:
                embed = None
                if isinstance(exception, CommandNotFound):
                    query = ctx.invoked_with + ctx.view.read_rest()
                    commands = self.find_commands(query)
                    if commands:
                        commands = set(next(zip(*commands)))
                        embed = Embed(title="Did you mean:", colour=Colour.orange())
                        for cmd in commands:
                            if len(embed.fields) >= 25:
                                break
                            embed.add_field(name=cmd.qualified_name, value=f"`{cmd.short_doc}`")
                if not embed:
                    embed = Embed(title=type(exception).__name__, description=str(exception), colour=Colour.red())
                report = False

            await ctx.send(embed=embed)

        log.exception("CommandError:", exc_info=exception, extra=dict(report=report))

        self.dispatch("command_finished", ctx, exception=exception)

    async def on_ready(self):
        log.info(f"\rConnected!  Giesela v{BOT_VERSION}")
        log.info(f"Bot: {self.user}")

        config_string = ""
        all_options = self.config.get_all_options()
        for option in all_options:
            opt, val = option

            opt_string = "  {}: ".format(opt)

            lines = wrap(str(val), 100 - len(opt_string))
            if len(lines) > 1:
                val_string = "{}\n{}\n".format(lines[0], indent("\n".join(lines[1:]), len(opt_string) * " "))
            else:
                val_string = lines[0]

            config_string += opt_string + val_string + "\n"

        if config_string:
            log.info("Config:\n" + config_string)

        log.info("Ready to go!")

    async def on_error(self, event: str, *args, **kwargs):
        log.exception(f"Error in {event} ({args}, {kwargs})")

    @classmethod
    async def on_reaction_remove(cls, reaction, user):
        await events.handle_reaction(reaction, user)

    @classmethod
    async def on_reaction_add(cls, reaction, user):
        await events.handle_reaction(reaction, user)
