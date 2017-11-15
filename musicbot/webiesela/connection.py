import logging

import websockets

log = logging.getLogger(__name__)


class Connection:
    def __init__(self, websocket):
        self.websocket = websocket

    def __str__(self):
        return "<{}>".format(self.websocket.remote_address)

    async def send(self, msg):
        try:
            await self.websocket.send(msg)
            log.debug("sent {} to {}".format(msg, self))
        except websockets.exceptions.ConnectionClosed:
            return False
