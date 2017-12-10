"""The core of Giesela."""

import asyncio
import logging
import traceback
from collections import defaultdict

import aiohttp
import discord

from giesela.config import Config
from giesela.lib import module
from giesela.models import exceptions, signals
from giesela.utils import localisation
from giesela.utils.opus_loader import load_opus_lib

load_opus_lib()
log = logging.getLogger(__name__)


class Giesela(discord.Client):
    """The marvelous Giesela."""

    def __init__(self):
        """Initialise."""
        super().__init__()

        self.config = Config.load()
        self.modules = []

        self.locks = defaultdict(asyncio.Lock)
        self.aiosession = aiohttp.ClientSession(loop=self.loop)

        self.load_modules()

    def load_modules(self):
        """Load all modules."""
        from . import modules  # noqa: F401

        ext_classes = module.GieselaModule.modules

        self.modules = []

        log.debug("loading {} modules".format(len(ext_classes)))

        for ext_cls in ext_classes:
            try:
                m = ext_cls(self)
                log.debug("created module {}".format(m))

                m.on_load()
                log.debug("initialised module {}".format(m))

                self.modules.append(m)
            except Exception:
                log.error("{}\nCouldn't load extension {}!".format(traceback.format_exc(), ext_cls))

        log.info("loaded {}/{} modules".format(len(self.modules), len(ext_classes)))

    def _emitted(self, future):
        exc = future.exception()

        if exc:
            log.error("Exception in {}:\n{}".format(future, traceback.format_exception(None, exc, None)))

    async def emit(self, event, *args, **kwargs):
        """Call a function in all extensions."""
        for m in self.modules:
            task = self.loop.create_task(getattr(m, event)(*args, **kwargs))
            task.add_done_callback(self._emitted)

    async def on_ready(self):
        """Call when bot ready."""
        log.info("ready!")
        await self.emit("on_ready")

    async def on_error(self, event, *args, **kwargs):
        """Call on error."""
        log.exception("Error in {}".format(event))
        traceback.print_exc()
        await self.emit("on_error", event, *args, **kwargs)

    async def on_message(self, message):
        """Call when message received."""
        await self.emit("_on_message", message)

    async def on_message_edit(self, before, after):
        """Call when message edited."""
        await self.emit("on_message_edit", before, after)

    async def on_message_delete(self, message):
        """Call when message deleted."""
        await self.emit("on_message_delete", message)

    async def on_channel_create(self, channel):
        """Call when channel created."""
        await self.emit("on_channel_create", channel)

    async def on_channel_update(self, before, after):
        """Call when channel updated."""
        await self.emit("on_channel_update", before, after)

    async def on_channel_delete(self, channel):
        """Call when channel deleted."""
        await self.emit("on_channel_delete", channel)

    async def on_member_join(self, member):
        """Call when member joined."""
        await self.emit("on_member_join", member)

    async def on_member_remove(self, member):
        """Call when member removed (left)."""
        await self.emit("on_member_remove", member)

    async def on_member_update(self, before, after):
        """Call when member updated."""
        await self.emit("on_member_update", before, after)

    async def on_server_join(self, server):
        """Call after joining a server."""
        await self.emit("on_server_join", server)

    async def on_server_update(self, before, after):
        """Call when server updated."""
        await self.emit("on_server_update", before, after)

    async def on_server_role_create(self, server, role):
        """Call when role created."""
        await self.emit("on_server_role_create", server, role)

    async def on_server_role_delete(self, server, role):
        """Call when role deleted."""
        await self.emit("on_server_role_delete", server, role)

    async def on_server_role_update(self, server, role):
        """Call when role updated."""
        await self.emit("on_server_role_update", server, role)

    async def on_voice_state_update(self, before, after):
        """Call when voice state updated."""
        await self.emit("on_voice_state_update", before, after)

    async def on_member_ban(self, member):
        """Call when member banned."""
        await self.emit("on_member_ban", member)

    async def on_member_unban(self, member):
        """Call when member unbanned."""
        await self.emit("on_member_unban", member)

    async def on_typing(self, channel, user, when):
        """Call when user starts typing."""
        await self.emit("on_typing", channel, user, when)

    def _cleanup(self):
        try:
            self.loop.run_until_complete(self.logout())
        except Exception:  # Can be ignored
            pass

        pending = asyncio.Task.all_tasks()
        gathered = asyncio.gather(*pending)

        try:
            gathered.cancel()
            self.loop.run_until_complete(gathered)
            gathered.exception()
        except Exception:  # Can be ignored
            pass

    def run(self):
        """Start 'er up."""
        try:
            self.config.check()
        except exceptions.ConfigKeysMissing as e:
            log.error(localisation.format(None, "exceptions.config.missing_keys", " ,".join(e.missing)))
            raise signals.StopSignal

        if not self.config.token:
            log.error(localisation.get(None, "exceptions.token.none"))
            raise signals.StopSignal

        try:
            self.loop.run_until_complete(self.start(self.config.token))
        except discord.errors.LoginFailure:
            log.error(localisation.get(None, "exceptions.token.invalid"))

        finally:
            try:
                self._cleanup()
            except Exception as e:
                log.exception("Error in cleanup:")

            self.loop.close()
            raise signals.StopSignal
