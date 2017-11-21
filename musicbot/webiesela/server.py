"""Module for the Websocket server which receives incoming connections, manages them and passes events to the manager."""

import json
import logging

import websockets

from .manager import Manager
from .models.connection import Connection
from .models.webiesela_user import WebieselaUser

log = logging.getLogger(__name__)


class Server:
    """A websocket server."""

    bot = None
    manager = None
    socket_server = None

    @classmethod
    async def serve(cls, bot):
        """Start listening to incoming connections."""
        cls.bot = bot
        WebieselaUser.bot = bot
        cls.manager = Manager(cls)
        await cls.manager.load_extensions()

        cls.socket_server = websockets.serve(cls.handle_connection, host="", port=8000)

        log.info("starting server!")

        await cls.socket_server

    @classmethod
    async def handle_connection(cls, ws, path):
        """Manage an incoming connection asynchronously and pass its events to the manager."""
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
        """Kill the server."""
        await cls.socket_server.wait_closed()
