"""Communication module."""

import time

from .. import converter


class Message:
    """Represent an incoming message."""

    def __init__(self, connection, raw_message, message_id, content):
        """Create new message."""
        self.connection = connection
        self.raw_message = raw_message
        self.message_id = message_id
        self.content = content

    def __str__(self):
        """Return string."""
        return "<{} by {}::{}>".format(type(self).__name__, self.connection, self.message_id)

    def __contains__(self, key):
        """Check if the message provided a certain param."""
        return key in self.content

    def __getitem__(self, key):
        """Retrieve a parameter from the message's data."""
        return self.content[key]

    @property
    def registered(self):
        """Check if the message was sent by a registered user."""
        return self.connection.registered

    @property
    def webiesela_user(self):
        """Return the corresponding user."""
        return self.connection.webiesela_user

    @property
    def server(self):
        """Return the corresponding server."""
        return self.webiesela_user and self.webiesela_user.server

    async def reject(self, error):
        """Answer with an error to the message."""
        response = Response.error(self, error)
        return await self.connection.send(response)

    async def answer(self, data=None, *, success=None):
        """Answer with a reponse to the message."""
        data = data or {}

        if success is not None:
            data["success"] = success

        response = Response.respond(self, data)
        return await self.connection.send(response)


class Command(Message):
    """A Message which tells Giesela to do something."""

    def __init__(self, connection, raw_message, message_id, command, content):
        """Create new Command."""
        super().__init__(connection, raw_message, message_id, content)

        self.command = command


class Request(Message):
    """A Message which asks for something."""

    def __init__(self, connection, raw_message, message_id, request, content):
        """Create new Request."""
        super().__init__(connection, raw_message, message_id, content)

        self.request = request


class Response:
    """A Response is a message from Giesela to Webiesela."""

    def __init__(self, content):
        """Create new Response."""
        self.content = content

    def __str__(self):
        """Stringify."""
        return "<Response>"

    @classmethod
    def respond(cls, message, data):
        """Create new Response as a response to a Message."""
        data.update({
            "response": True,
            "id": message.message_id,
            "timestamp": time.time()
        })

        return cls(data)

    @classmethod
    def error(cls, message, error):
        """Create new error Response."""
        if not isinstance(error, (str, dict)):
            if isinstance(error, Exception):
                error = converter.exception2dict(error)
            else:
                raise TypeError("Can't send error of type {}".format(type(error)))

        data = {
            "response": True,
            "id": message.message_id,
            "timestamp": time.time(),
            "error": error
        }

        return cls(data)

    @classmethod
    def create(cls, data):
        """Create new Response."""
        data.update({
            "response": False,
            "timestamp": time.time()
        })

        return cls(data)

    def to_dict(self):
        """Return serialised dict."""
        return self.content
