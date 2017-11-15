import logging
from functools import wraps

log = logging.getLogger(__name__)


def command(match, ):
    def decorator(func):

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            pass


class ExtensionMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, "extensions"):
            # only add it to the first deriver (the Extension class)
            cls.extensions = []
            log.debug("created base Extension class")
        else:
            # otherwise add it
            cls.extensions.append(cls)
            log.debug("loaded extension {}".format(cls))


class Extension(metaclass=ExtensionMount):
    def __init__(self):
        # TODO do stuff?
        await self.init()

    async def init():
        pass

    async def on_connect(self, connection):
        pass

    async def on_disconnect(self, connection):
        pass

    async def on_raw_message(self, connection, message):
        pass

    async def on_message(self, connection, message):
        pass
