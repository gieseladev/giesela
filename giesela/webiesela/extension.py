"""Module which provides the modular functions to make extending the system possible."""

import inspect
import logging
import re
from functools import wraps

from .models.exceptions import (AuthorisationRequired, MissingParamsError,
                                ParamError, WebieselaException)
from .models.message import Command, Message, Request

log = logging.getLogger(__name__)


def message_endpoint(match_key=None, match=None, *, require_auth=True):
    """Message endpoint."""
    def decorator(func):
        name = func.__name__
        name_key = match_key or name
        prog = re.compile(match or name)

        sig = inspect.signature(func)
        parameters = sig.parameters

        @wraps(func)
        async def wrapper(self, message):
            if not hasattr(message, name_key):
                log.debug("{} didn't have key {}".format(message, name_key))
                return

            if prog.match(getattr(message, name_key)):
                if require_auth and not message.registered:
                    raise AuthorisationRequired("/{} needs authorisation. please authorise or register".format(name))

                kwargs = {}

                params = parameters.copy()

                if params.pop("self", False):
                    kwargs["self"] = self

                if params.pop("message", False):
                    kwargs["message"] = message

                if params.pop("connection", False):
                    kwargs["connection"] = message.connection

                if params.pop("webiesela_user", False):
                    kwargs["webiesela_user"] = message.webiesela_user

                if params.pop("server", False):
                    kwargs["server"] = message.server

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
                    raise MissingParamsError(params.keys())

                try:
                    return await func(**kwargs)
                except AssertionError as e:
                    if e.args and isinstance(e.args[0], ParamError):
                        raise e.args[0]

                    raise e
            else:
                return

        setattr(wrapper, "_is_{}".format(name_key), True)
        wrapper._endpoint = True

        return wrapper

    return decorator


def command(match=None, *, require_auth=True):
    """Command endpoint."""
    return message_endpoint("command", match, require_auth=require_auth)


def request(match=None, *, require_auth=True):
    """Request endpoint."""
    return message_endpoint("request", match, require_auth=require_auth)


class ExtensionMount(type):
    """The metaclass for an extension which, when deriving from the inherited class, adds said class to a list."""

    def __init__(cls, name, bases, attrs):
        """Add class to list."""
        if not hasattr(cls, "extensions"):
            # only add it to the first deriver (the Extension class)
            cls.extensions = []
            log.debug("created base Extension class")
        else:
            # otherwise add it
            cls.extensions.append(cls)
            log.debug("registered extension \"{}\"".format(name))


class Extension(metaclass=ExtensionMount):
    """The basis which all other extensions derive from."""

    singleton = None

    def __init__(self, server):
        """Set-up references and parse commands and requests.

        Called internally!
        """
        type(self).singleton = self

        self.server = server
        self.bot = server.bot

        self.custom_endpoints = {}
        self.commands = {}
        self.requests = {}

        for name, value in inspect.getmembers(self):
            if hasattr(value, "_endpoint"):
                if hasattr(value, "_is_command"):
                    self.commands[name] = value
                elif hasattr(value, "_is_request"):
                    self.requests[name] = value
                else:
                    self.custom_endpoints[name] = value

        log.debug("{} registered {}/{}/{} customs/cmds/reqs".format(self, len(self.custom_endpoints), len(self.commands), len(self.requests)))

    def __str__(self):
        """Return string rep. of an Extension."""
        return "<Webiesela Extension {}>".format(type(self).__name__)

    async def _on_message(self, message):
        targets = []

        if isinstance(message, Command):
            targets.extend(self.commands.items())
        elif isinstance(message, Request):
            targets.extend(self.requests.items())
        elif isinstance(message, Message):
            targets.extend(self.custom_endpoints.items())

        for name, func in targets:
            try:
                await func(message)
            except WebieselaException as e:
                await message.reject(e)
            except Exception as e:
                log.error("Error while running \"{}\"".format(name), exc_info=True)
                # TODO send internal server error

        await self.on_message(message)

    async def on_load(self):
        """Call when Extension has been loaded."""
        pass

    async def on_error(self, connection, error, data):
        """Call when an error occurs while parsing an incoming message."""
        pass

    async def on_connect(self, connection):
        """Call when new Connection was made."""
        pass

    async def on_disconnect(self, connection):
        """Call when a Connection disconnected."""
        pass

    async def on_raw_message(self, connection, message):
        """Call after receiving a message with the raw content."""
        pass

    async def on_message(self, message):
        """Call when raw message has been parsed into a Message."""
        pass
