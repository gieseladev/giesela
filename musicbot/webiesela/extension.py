from functools import wraps


def command(match, ):
    def decorator(func):

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            pass


class ExtensionMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, "extensions"):
            cls.extensions = []
        else:
            cls.extensions.append(cls)


class Extension(metaclass=ExtensionMount):
    def __init__(self):
        pass

    async def on_connect(self, connection):
        pass

    async def on_disconnect(self, connection):
        pass

    async def on_raw_message(self, connection, message):
        pass

    async def on_message(self, connection, message):
        pass
