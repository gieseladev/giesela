"""Module which manages extensions and passes events to them."""

import logging
import traceback

from .extension import Extension
from .models import message

log = logging.getLogger(__name__)


class Manager:
    """Manager manages websocket stuff."""

    def __init__(self, server):
        """Create a new manager for a server."""
        self.bot = server.bot
        self.loop = self.bot.loop
        self.server = server

        self.extensions = []

        self.connections = []

    async def load_extensions(self):
        """Load all extensions."""
        # needed to import all extensions
        from . import extensions  # noqa: F401

        ext_classes = Extension.extensions

        self.extensions = []

        log.debug("loading {} extensions".format(len(ext_classes)))

        for ext_cls in ext_classes:
            try:
                ext = ext_cls(self.server)
                log.debug("created extension {}".format(ext))

                await ext.on_load()
                log.debug("initialised extension {}".format(ext))

                self.extensions.append(ext)
            except Exception:
                log.error("{}\nCouldn't load extension {}!".format(traceback.format_exc(), ext_cls))

        log.info("loaded {}/{} extensions".format(len(self.extensions), len(ext_classes)))

    def _emitted(self, future):
        exc = future.exception()

        if exc:
            log.error("Exception in {}:\n{}".format(future, traceback.format_exception(None, exc, None)))

    async def emit(self, event, *args, **kwargs):
        """Call a function in all extensions."""
        for extension in self.extensions:
            task = self.loop.create_task(getattr(extension, event)(*args, **kwargs))
            task.add_done_callback(self._emitted)

    async def on_connect(self, connection):
        """Handle new connection."""
        log.info("{} connected".format(connection))
        self.connections.append(connection)

        await self.emit("on_connect", connection)

    async def on_disconnect(self, connection):
        """Handle connection disconnecting."""
        log.info("{} disconnected".format(connection))
        self.connections.remove(connection)

        await self.emit("on_disconnect", connection)

    async def on_error(self, connection, error, data):
        """Handle errors while parsing message."""
        log.warn("{} sent {} which produced error {}".format(connection, data, type(error).__name__))

        await self.emit("on_error", connection, error, data)

    async def _parse_raw_message(self, connection, msg):
        raw = msg
        content = raw.copy()

        message_id = content.pop("id", None)

        args = (connection, raw, message_id)

        command = content.pop("command", False)
        request = content.pop("request", False)

        if command:
            m = message.Command(*args, command, content)
        elif request:
            m = message.Request(*args, request, content)
        else:
            m = message.Message(*args, content)

        return m

    async def on_raw_message(self, connection, msg):
        """Handle raw message."""
        log.debug("{} sent {}".format(connection, msg))

        await self.emit("on_raw_message", connection, msg)

        msg = await self._parse_raw_message(connection, msg)
        await self.on_message(msg)

    async def on_message(self, msg):
        """Handle parsed message."""
        log.debug("handling parsed message {}".format(msg))

        await self.emit("_on_message", msg)
