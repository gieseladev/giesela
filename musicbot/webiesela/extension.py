import inspect
import logging
import re
from functools import wraps

from .models.exceptions import Exceptions
from .models.message import Command, Request

log = logging.getLogger(__name__)


def command(match=None, *, require_registration=True):
    def decorator(func):
        name = func.__name__

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            await func(self, *args, **kwargs)

        return wrapper

    return decorator


def request(match=None, *, require_registration=True):
    def decorator(func):
        name = func.__name__
        prog = re.compile(match or name)

        sig = inspect.signature(func)
        parameters = sig.parameters

        @wraps(func)
        async def wrapper(self, message):
            if prog.match(message.request):
                if require_registration and not message.registered:
                    return

                kwargs = {}

                params = parameters.copy()

                if params.pop("self", False):
                    kwargs["self"] = self

                if params.pop("message", False):
                    kwargs["message"] = message

                if params.pop("connection", False):
                    kwargs["connection"] = message.connection

                if params.pop("leftover", False):
                    kwargs["leftover"] = message.content

                # creating a copy of the params
                for key, param in list(params.items()):
                    if key in message:
                        kwargs[key] = message[key]
                        params.pop(key)
                    elif param.default is inspect.Parameter.empty:
                        log.warning("missing parameter \"{}\"".format(key))

                if params:
                    log.warning("not all parameters satisfied!")
                    await message.reject(Exceptions.MISSING_PARAMS)
                    return

                return await func(**kwargs)
            else:
                return

        wrapper._is_request = True

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
    singleton = None

    def __init__(self, server):
        type(self).singleton = self

        self.server = server
        self.bot = server.bot

        self.commands = {}
        self.requests = {}

        for name, value in inspect.getmembers(self):
            if hasattr(value, "_is_command"):
                self.commands[name] = value

            if hasattr(value, "_is_request"):
                self.requests[name] = value

        log.debug("{} registered {}/{} cmds/reqs".format(self, len(self.commands), len(self.requests)))

    def __str__(self):
        return "<Webiesela Extension {}>".format(type(self).__name__)

    async def _on_message(self, message):
        targets = []

        if isinstance(message, Command):
            targets.extend(self.commands.items())

        if isinstance(message, Request):
            targets.extend(self.requests.items())

        for name, func in targets:
            try:
                result = await func(message)
            except Exception as e:
                log.error("Error while running \"{}\"".format(name), exc_info=True)
                # TODO send internal server error

        await self.on_message(message)

    async def on_load(self):
        pass

    async def on_error(self, connection, error, data):
        pass

    async def on_connect(self, connection):
        pass

    async def on_disconnect(self, connection):
        pass

    async def on_raw_message(self, connection, message):
        pass

    async def on_message(self, message):
        pass
