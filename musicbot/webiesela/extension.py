import logging
from functools import wraps

log = logging.getLogger(__name__)


def command(match):
    def decorator(func):

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            pass

        return wrapper

    return decorator


class ExtensionMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, "extensions"):
            # only add it to the first deriver (the Extension class)
            cls.extensions = []
            log.debug("created base Extension class")
        else:
            # otherwise add it
            cls.extensions.append(cls)
            log.debug("registered extension \"{}\"".format(name))


class Extension(metaclass=ExtensionMount):
    def __init__(self, server):
        # TODO do stuff?
        pass

    async def on_load(self):
        pass

    async def on_connect(self, connection):
        pass

    async def on_disconnect(self, connection):
        pass

    async def on_raw_message(self, connection, message):
        pass

    async def on_message(self, connection, message):
        pass
