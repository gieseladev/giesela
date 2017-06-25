import atexit
import hashlib
import json
import threading
from json.decoder import JSONDecodeError

from .simple_web_socket_server import SimpleWebSocketServer, WebSocket


class GieselaWebSocket(WebSocket):

    def handleMessage(self):
        try:
            data = json.loads(self.data)

            token = data.get("token", None)
            if token:
                info = GieselaServer.tokens.get(token, None)
                if info:
                    pass

            print("[WEBSOCKET] <***REMOVED******REMOVED***> invalid or no token provided".format(
                self.address))
            registration_token = data.get("registration_token", None)
            if registration_token:
                GieselaServer.awaiting_registration[
                    registration_token] = self.register  # setting the callback
                print("[WEBSOCKET] <***REMOVED******REMOVED***> Waiting for registration with token: ***REMOVED******REMOVED***".format(
                    self.address, registration_token))
                return
            else:
                print("[WEBSOCKET] <***REMOVED******REMOVED***> Didn't provide a registration token".format(
                    self.address))
        except JSONDecodeError:
            print("[WEBSOCKET] <***REMOVED******REMOVED***> sent non-json: ***REMOVED******REMOVED***".format(self.address, self.data))

    def handleConnected(self):
        print("[WEBSOCKET] <***REMOVED******REMOVED***> connected".format(self.address))
        GieselaServer.clients.append(self)

    def handleClose(self):
        GieselaServer.clients.remove(self)
        print("[WEBSOCKET] <***REMOVED******REMOVED***> disconnected".format(self.address))

    def register(self, server_id, author):
        token = hashlib.sha256(
            (server_id + author.id).encode("utf-8")).hexdigest()
        GieselaServer.tokens[token] = (server_id, author)
        data = ***REMOVED***
            "token": token***REMOVED***
        self.sendMessage(json.dumps(data))
        print("[WEBSOCKET] <***REMOVED******REMOVED***> successfully registered ***REMOVED******REMOVED***".format(
            self.address, author))

    def send_current_entry(self):
        entry = None  # get current entry
        self.sendMessage()


class GieselaServer:
    clients = []
    server = None
    bot = None
    tokens = ***REMOVED******REMOVED***  # token: (server_id, author_id)
    awaiting_registration = ***REMOVED******REMOVED***

    def run(bot):
        GieselaServer.bot = bot
        GieselaServer.server = SimpleWebSocketServer("",
                                                     8000,
                                                     GieselaWebSocket)
        atexit.register(GieselaServer.server.close)
        # new thread because it's blocking
        threading.Thread(target=GieselaServer.server.serveforever).start()
        print("[WEBSOCKET] up and running")

    def register_information(server_id, author_id, token):
        callback = GieselaServer.awaiting_registration.get(token, None)
        author = WebAuthor.from_id(author_id)
        if not callback:
            return False

        callback(server_id, author)
        return True


class WebAuthor:

    def __init__(self, id, name, display_name, avatar_url, colour):
        self.id = id
        self.name = name
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.colour = colour

    @classmethod
    def from_id(cls, author_id):
        user = GieselaServer.bot.get_global_user(author_id)
        return cls(author_id, user.name, user.display_name, user.avatar_url, user.colour)

    def __str__(self):
        return "[***REMOVED******REMOVED***/***REMOVED******REMOVED***]".format(self.id, self.name)

    def to_dict(self):
        return ***REMOVED***
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "colour": self.colour
        ***REMOVED***
