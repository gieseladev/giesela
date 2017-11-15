import asyncio
import logging

import websockets

from .connection import Connection
from .manager import Manager

log = logging.getLogger(__name__)


class Server:
    bot = None
    manager = None
    socket_server = None

    connections = []

    @classmethod
    async def serve(cls, bot):
        cls.bot = bot
        cls.manager = Manager(cls)
        await cls.manager.load_extentions()

        cls.socket_server = websockets.serve(cls.handle_connection, host="", port=8000)

        log.info("starting server!")

        await cls.socket_server

    @classmethod
    async def handle_connection(cls, ws, path):
        connection = Connection(ws)

        cls.connections.append(connection)

        await cls.manager.on_connect(connection)

        while True:
            try:
                msg = await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                await cls.manager.on_disconnect(connection)
                return

            await cls.manager.on_raw_message(connection, msg)

    @classmethod
    async def shutdown(cls):
        await cls.socket_server.wait_closed()
