import asyncio
import inspect
import logging
import traceback

from .extension import Extension
from .models import message

log = logging.getLogger(__name__)


class Manager:
    def __init__(self, server):
        self.bot = server.bot
        self.loop = self.bot.loop
        self.server = server

        self.extensions = []

        self.connections = []

    async def load_extentions(self):
        from . import extensions

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
            except:
                log.error("{}\nCouldn't load extension {}!".format(traceback.format_exc(), ext_cls))

        log.info("loaded {}/{} extensions".format(len(self.extensions), len(ext_classes)))

    def emitted(self, future):
        exc = future.exception()

        if exc:
            log.error("Exception in {}:\n{}".format(future, traceback.format_exception(None, exc, None)))

    async def emit(self, event, *args, **kwargs):
        for extension in self.extensions:
            task = self.loop.create_task(getattr(extension, event)(*args, **kwargs))
            task.add_done_callback(self.emitted)

    async def on_connect(self, connection):
        log.info("{} connected".format(connection))
        self.connections.append(connection)

        await self.emit("on_connect", connection)

    async def on_disconnect(self, connection):
        log.info("{} disconnected".format(connection))
        self.connections.remove(connection)

        await self.emit("on_disconnect", connection)

    async def on_error(self, connection, error, data):
        log.warn("{} sent {} which produced error {}".format(connection, data, type(error).__name__))

        await self.emit("on_error", connection, error, data)

    async def parse_raw_message(self, connection, msg):
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
        log.debug("{} sent {}".format(connection, msg))

        await self.emit("on_raw_message", connection, msg)

        msg = await self.parse_raw_message(connection, msg)
        await self.on_message(msg)

    async def on_message(self, msg):
        log.debug("handling parsed message {}".format(msg))

        await self.emit("_on_message", msg)
