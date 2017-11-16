import asyncio
import json
import logging

import websockets

from .manager import Manager
from .models.connection import Connection

log = logging.getLogger(__name__)


class Server:
    bot = None
    manager = None
    socket_server = None

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

        await cls.manager.on_connect(connection)

        while True:
            try:
                data = await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                await cls.manager.on_disconnect(connection)
                return

            try:
                msg = json.loads(data)
            except json.JSONDecodeError as e:
                await cls.manager.on_error(connection, data, e)
                continue

            await cls.manager.on_raw_message(connection, msg)

    @classmethod
    async def shutdown(cls):
        await cls.socket_server.wait_closed()
