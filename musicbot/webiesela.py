import asyncio
import logging

import websockets

from musicbot.webiesela.connection import Connection
from musicbot.webiesela.manager import Manager

log = logging.getLogger(__name__)


class Server:
    bot = None
    manager = None
    socket_server = None

    connections = []

    @classmethod
    async def serve(cls, bot):
        cls.bot = bot
        cls.manager = Manager(self)
        cls.socket_server = websockets.serve(cls.handle_connection)

        await cls.socket_server

    @classmethod
    async def handle_connection(cls, ws, path):
        connection = Connection(ws)
        log.info("{} connected".format(connection))

        cls.connections.append(connection)

        await cls.manager.on_connect(connection)

        await ws.recv()

    @classmethod
    async def shutdown(cls):
        await cls.socket_server.wait_closed()
