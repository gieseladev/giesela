import atexit
import hashlib
import json
import threading
import traceback
from json.decoder import JSONDecodeError

import asyncio

from .simple_web_socket_server import SimpleWebSocketServer, WebSocket


class GieselaWebSocket(WebSocket):

    def handleMessage(self):
        try:
            try:
                # always starts with GIESELA to avoid getting blocked by
                # browsers
                data = json.loads(self.data)

                token = data.get("auth_token", None)
                if token:
                    info = GieselaServer.get_token_information(token)
                    if info:
                        self.token = token
                        if self not in GieselaServer.authenticated_clients:
                            GieselaServer.authenticated_clients.append(
                                self)  # register for updates
                        # handle all the other shit over there
                        self.handleAuthenticatedMessage(data)
                        return
                    else:
                        print("[WEBSOCKET] <***REMOVED******REMOVED***> invalid token provided".format(
                            self.address))
                else:
                    print("[WEBSOCKET] <***REMOVED******REMOVED***> no token provided".format(
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
                    self.sendMessage(
                        "***REMOVED***\"error\":\"registration_token required\"***REMOVED***")
            except JSONDecodeError:
                print(
                    "[WEBSOCKET] <***REMOVED******REMOVED***> sent non-json: ***REMOVED******REMOVED***".format(self.address, self.data))
        except Exception as e:
            traceback.print_exc()

    def handleAuthenticatedMessage(self, data):
        answer = ***REMOVED******REMOVED***
        request = data.get("request", None)
        command = data.get("command", None)

        if request:
            # send all the information one can acquire
            if request == "send_information":
                player_info = GieselaServer.get_player_information(self.token)
                user_info = GieselaServer.get_token_information(self.token)[
                    1].to_dict()
                answer["player"] = player_info
                answer["user"] = user_info

        self.sendMessage(json.dumps(answer))

    def handleConnected(self):
        print("[WEBSOCKET] <***REMOVED******REMOVED***> connected".format(self.address))
        GieselaServer.clients.append(self)

    def handleClose(self):
        GieselaServer.clients.remove(self)
        GieselaServer.authenticated_clients.pop(self, None)
        print("[WEBSOCKET] <***REMOVED******REMOVED***> disconnected".format(self.address))

    def register(self, server_id, author):
        token = hashlib.sha256(
            (server_id + author.id).encode("utf-8")).hexdigest()
        self.token = token
        GieselaServer.set_token_information(token, server_id, author)
        data = ***REMOVED***
            "token": token***REMOVED***
        self.sendMessage(json.dumps(data))
        print("[WEBSOCKET] <***REMOVED******REMOVED***> successfully registered ***REMOVED******REMOVED***".format(
            self.address, author))

    def send_current_entry(self):
        entry = None  # get current entry
        self.sendMessage()


class GieselaServer():
    clients = []
    authenticated_clients = []
    server = None
    bot = None
    _tokens = ***REMOVED******REMOVED***  # token: (server_id, author)
    awaiting_registration = ***REMOVED******REMOVED***
    loaded_tokens = False

    def run(bot):
        GieselaServer.bot = bot

        if not GieselaServer.loaded_tokens:  # load when it hasn't been loaded before
            print("[WEBSOCKET] haven't loaded tokens, doing so now")
            try:
                GieselaServer._tokens = ***REMOVED***t: (s, WebAuthor.from_id(u)) for t, (s, u) in json.load(
                    open("data/websocket_token.json", "r")).items()***REMOVED***
                print("[WEBSOCKET] loaded tokens")
            except FileNotFoundError:
                print("[WEBSOCKET] failed to load tokens, there are none saved")
                pass
            GieselaServer.loaded_tokens = True

        GieselaServer.server = SimpleWebSocketServer("",
                                                     8000,
                                                     GieselaWebSocket)
        atexit.register(GieselaServer.server.close)
        # new thread because it's blocking
        threading.Thread(target=GieselaServer.server.serveforever).start()
        print("[WEBSOCKET] up and running")

    def register_information(server_id, author_id, token):
        callback = GieselaServer.awaiting_registration.pop(token, None)
        author = WebAuthor.from_id(author_id)
        if not callback:
            return False

        callback(server_id, author)
        return True

    def get_token_information(token):
        return GieselaServer._tokens.get(token, None)

    def set_token_information(token, server_id, author):
        GieselaServer._tokens[token] = (server_id, author)
        json.dump(***REMOVED***t: (s, u.id) for t, (s, u) in GieselaServer._tokens.items()***REMOVED***,
                  open("data/websocket_token.json", "w+"))

    def get_player_information(token):
        server_id = GieselaServer.get_token_information(token)[0]
        try:
            player = asyncio.run_coroutine_threadsafe(GieselaServer.bot.get_player(
                server_id=server_id), GieselaServer.bot.loop).result()
        except Exception as e:
            print("[WEBSOCKET] encountered error while getting player:\n***REMOVED******REMOVED***".format(e))
            return None

        return player.get_dict()


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
        return cls(author_id, user.name, user.display_name, user.avatar_url, user.colour.value)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

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
