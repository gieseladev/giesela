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

    async def answer(self, data):
        # TODO
        # data.update({"response": True, "id": self.message_id})
        return await self.connection.send(data)


class Command(Message):
    def __init__(self, connection, raw_message, message_id, command, content):
        super().__init__(connection, raw_message, message_id, content)

        self.command = command


class Request(Message):
    def __init__(self, connection, raw_message, message_id, request, content):
        super().__init__(connection, raw_message, message_id, content)

        self.request = request
