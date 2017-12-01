"""Contains the model for a connection made to Giesela."""

import json
import logging

import websockets

from .message import Response

log = logging.getLogger(__name__)


class Connection:
    """Represents a single connection from Webiesela to Giesela."""

    def __init__(self, websocket):
        """Initialise a new Connection based on a websocket connection."""
        self.websocket = websocket
        self.token = None
        self.webiesela_user = None

    def __str__(self):
        """Return a string version?."""
        if self.registered:
            return "<{} : {}>".format(self.webiesela_user, self.websocket.remote_address)

        return "<{}>".format(self.websocket.remote_address)

    @property
    def registered(self):
        """Check if this connection is registered."""
        return bool(self.webiesela_user)

    @property
    def open(self):
        """Check if connection still open."""
        return self.websocket.open

    def register(self, token):
        """Bind a token to this connection."""
        self.token = token
        self.webiesela_user = token.webiesela_user

    async def send(self, msg, *, quiet=True):
        """Send a message to Webiesela."""
        if msg:
            if not isinstance(msg, dict):
                if isinstance(msg, Response):
                    msg = msg.to_dict()
                else:
                    raise TypeError("Cannot send message of type {}".format(type(msg)))
        else:
            raise TypeError("Cannot send empty message...")

        encoded_message = json.dumps(msg, separators=(",", ":"))

        try:
            await self.websocket.send(encoded_message)
            log.debug("sent {} to {}".format(msg, self))
            return True
        except websockets.exceptions.ConnectionClosed:
            log.warning("couldn't send {} to {}, already closed!".format(msg, self))

            if quiet:
                return False
            else:
                raise
