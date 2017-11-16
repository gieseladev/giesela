import logging

import websockets

log = logging.getLogger(__name__)


class Connection:
    def __init__(self, websocket):
        self.websocket = websocket
        self.token = None
        self.webiesela_user = None

    def __str__(self):
        return "<{}>".format(self.websocket.remote_address)

    @property
    def registered(self):
        return bool(self.webiesela_user)

    def register(self, token):
        self.token = token
        self.webiesela_user = token.webiesela_user

    async def send(self, msg):
        try:
            await self.websocket.send(msg)
            log.debug("sent {} to {}".format(msg, self))
            return True
        except websockets.exceptions.ConnectionClosed:
            log.warning("couldn't send {} to {}, already closed!".format(msg, self))
            return False
