import time

from .. import converter
from .exceptions import Exceptions


class Message:
    def __init__(self, connection, raw_message, message_id, content):
        self.connection = connection
        self.raw_message = raw_message
        self.message_id = message_id
        self.content = content

    def __str__(self):
        return "<{} by {}::{}>".format(type(self).__name__, self.connection, self.message_id)

    def __contains__(self, key):
        return key in self.content

    def __getitem__(self, key):
        return self.content[key]

    @property
    def registered(self):
        return self.connection.registered

    @property
    def webiesela_user(self):
        return self.connection.webiesela_user

    async def reject(self, error):
        response = Response.error(self, error)
        return await self.connection.send(response)

    async def answer(self, data):
        response = Response.respond(self, data)
        return await self.connection.send(response)


class Command(Message):
    def __init__(self, connection, raw_message, message_id, command, content):
        super().__init__(connection, raw_message, message_id, content)

        self.command = command


class Request(Message):
    def __init__(self, connection, raw_message, message_id, request, content):
        super().__init__(connection, raw_message, message_id, content)

        self.request = request


class Response:
    def __init__(self, content):
        self.content = content

    def __str__(self):
        return "<Response>"

    @classmethod
    def respond(cls, message, data):
        data.update({
            "response": True,
            "id": message.message_id,
            "timestamp": time.time()
        })

        return cls(data)

    @classmethod
    def error(cls, message, error):
        if not isinstance(error, (str, dict)):
            if isinstance(error, (Exception, Exceptions)):
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
        data.update({
            "response": False,
            "timestamp": time.time()
        })

        return cls(data)

    def to_dict(self):
        return self.content
