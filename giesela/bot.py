import logging
from textwrap import indent, wrap
from typing import Optional, Type

import aiohttp
from discord import Colour, Embed
from discord.ext.commands import AutoShardedBot, CommandError, CommandInvokeError, Context

from . import cogs, exceptions, reporting
from .config import Config, ConfigDefaults
from .constants import VERSION as BOT_VERSION
from .lib.ui import events
from .web_author import WebAuthor

log = logging.getLogger(__name__)


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
        await self.aiosession.close()
        await super().logout()

    def run(self):
        try:
            super().run(self.config.token)
        finally:
            if self.exit_signal:
                raise self.exit_signal

    async def on_error(self, event: str, *args, **kwargs):
        log.exception(f"Error in {event} ({args}, {kwargs})")

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
                embed = Embed(title=type(exception).__name__, description=str(exception), colour=Colour.red())
                report = False
            await ctx.send(embed=embed)

        if report:
            reporting.raven_client.captureException((type(exception), exception, exception.__traceback__))

        log.exception("CommandError:", exc_info=exception)

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

    async def on_reaction_remove(self, reaction, user):
        await events.handle_reaction(reaction, user)

    async def on_reaction_add(self, reaction, user):
        await events.handle_reaction(reaction, user)
