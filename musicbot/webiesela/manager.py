import logging
import traceback

from .extension import Extension

log = logging.getLogger(__name__)


class Manager:
    def __init__(self, server):
        self.bot = server.bot
        self.server = server

    async def load_extentions(self):
        from . import extensions

        ext_classes = Extension.extensions

        self.extension_classes = ext_classes
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
                traceback.print_exc()
                log.warning("Couldn't load extension {}!")

        log.info("loaded {}/{} extensions".format(len(self.extensions), len(ext_classes)))

    async def on_connect(self, connection):
        log.info("{} connected".format(connection))

    async def on_disconnect(self, connection):
        log.info("{} disconnected".format(connection))

        await connection.send("bye!")

    async def on_raw_message(self, connection, msg):
        log.info("{} sent {}".format(connection, msg))
