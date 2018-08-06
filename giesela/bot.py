import asyncio
import logging
import os
import shutil
import sys
from textwrap import indent, wrap

import aiohttp
from discord import Colour, Embed
from discord.ext.commands import AutoShardedBot, CommandError, Context

from . import cogs, exceptions, reporting
from .config import Config, ConfigDefaults
from .constants import ABS_AUDIO_CACHE_PATH, VERSION as BOT_VERSION
from .lib.ui import events
from .saved_playlists import Playlists
from .web_author import WebAuthor

log = logging.getLogger(__name__)


def _delete_old_audio_cache(path=ABS_AUDIO_CACHE_PATH):
    try:
        shutil.rmtree(path)
        return True
    except Exception:
        try:
            os.rename(path, path + "__")
        except Exception:
            return False
        try:
            shutil.rmtree(path)
        except Exception:
            os.rename(path + "__", path)
            return False

    return True


class Giesela(AutoShardedBot):
    config: Config
    aiosession: aiohttp.ClientSession

    def __init__(self, *args, **kwargs):
        self.config = Config(ConfigDefaults.options_file)

        super().__init__(self.config.command_prefix, *args, **kwargs)
        WebAuthor.bot = self

        self.exit_signal = None
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += f" Giesela/{BOT_VERSION}"

        self.playlists = Playlists(ConfigDefaults.playlists_file)

        for ext in cogs.get_extensions():
            log.info(f"loading extension {ext}")
            self.load_extension(ext)

    async def logout(self):
        await self.aiosession.close()
        await super().logout()

    def _cleanup(self):
        try:
            self.loop.run_until_complete(self.logout())
        except BaseException:  # Can be ignored
            pass

        pending = asyncio.Task.all_tasks()
        gathered = asyncio.gather(*pending)

        try:
            gathered.cancel()
            self.loop.run_until_complete(gathered)
            gathered.exception()
        except BaseException:  # Can be ignored
            pass

    def run(self):
        try:
            super().run(self.config._token)
        finally:
            try:
                self._cleanup()
            except Exception as e:
                log.info("Error in cleanup:", e)

            self.loop.close()
            if self.exit_signal:
                raise self.exit_signal

    async def on_error(self, event: str, *args, **kwargs):
        ex_type, ex, stack = sys.exc_info()

        if issubclass(ex_type, exceptions.Signal):
            self.exit_signal = ex_type
            await self.logout()

        else:
            log.exception(f"Error in {event} ({args}, {kwargs})")

    async def on_command_error(self, ctx: Context, exception: Exception):
        if isinstance(exception, CommandError):
            embed = Embed(title=type(exception).__name__, description=str(exception), colour=Colour.red())
            await ctx.send(embed=embed)
        else:
            reporting.raven_client.captureException((type(exception), exception, exception.__traceback__))

        log.exception("CommandError:", exc_info=(type(exception), exception, exception.__traceback__))

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
                val_string = "{}\n{}\n".format(lines[0],
                                               indent("\n".join(lines[1:]), len(opt_string) * " ")
                                               )
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
