import atexit
import hashlib
import json
import threading
import traceback
from json.decoder import JSONDecodeError
from random import choice
from string import ascii_lowercase

import asyncio

from .entry import TimestampEntry
from .simple_web_socket_server import SimpleWebSocketServer, WebSocket
from .web_author import WebAuthor


class ErrorCode:
    registration_required = 1000


class GieselaWebSocket(WebSocket):

    def init(self):
        self.registration_token = None

    def log(self, *messages):
        message = " ".join(str(msg) for msg in messages)

        try:
            server_id, author = GieselaServer.get_token_information(self.token)
            identification = "***REMOVED******REMOVED***@***REMOVED******REMOVED***/***REMOVED******REMOVED***".format(author, server_id, self.address[0])
        except AttributeError:
            identification = self.address

        print("[WEBSOCKET] <***REMOVED******REMOVED***>".format(identification, message))

    def handleMessage(self):
        try:
            try:
                data = json.loads(self.data)
            except JSONDecodeError:
                print("[WEBSOCKET] <***REMOVED******REMOVED***> sent non-json: ***REMOVED******REMOVED***".format(self.address, self.data))
                return

            token = data.get("token", None)
            if token:
                info = GieselaServer.get_token_information(token)
                if info:
                    self.token = token
                    if self not in GieselaServer.authenticated_clients:
                        GieselaServer.authenticated_clients.append(self)  # register for updates
                    # handle all the other shit over there
                    self.handleAuthenticatedMessage(data)
                    return
                else:
                    print("[WEBSOCKET] <***REMOVED******REMOVED***> invalid token provided".format(
                        self.address))
            else:
                print("[WEBSOCKET] <***REMOVED******REMOVED***> no token provided".format(self.address))

            register = data.get("request", None) == "register"
            if register:
                registration_token = GieselaServer.generate_registration_token()
                GieselaServer.awaiting_registration[
                    registration_token] = self.register  # setting the callback

                self.registration_token = registration_token

                print("[WEBSOCKET] <***REMOVED******REMOVED***> Waiting for registration with token: ***REMOVED******REMOVED***".format(
                    self.address, registration_token))

                answer = ***REMOVED***
                    "response": True,
                    "registration_token": registration_token
                ***REMOVED***

                self.sendMessage(json.dumps(answer))
                return
            else:
                print("[WEBSOCKET] <***REMOVED******REMOVED***> Didn't ask to be registered".format(
                    self.address))
                answer = ***REMOVED***
                    "response": True,
                    "error": (ErrorCode.registration_required, "registration required")
                ***REMOVED***
                self.sendMessage(json.dumps(answer))

        except Exception as e:
            traceback.print_exc()
            raise

    def handleAuthenticatedMessage(self, data):
        answer = ***REMOVED***
            "response": True
        ***REMOVED***

        request = data.get("request")
        command = data.get("command")
        command_data = data.get("command_data", ***REMOVED******REMOVED***)

        if request:
            # send all the information one can acquire
            if request == "send_information":
                self.log("asked for information")
                info = ***REMOVED******REMOVED***
                player_info = GieselaServer.get_player_information(self.token)
                user_info = GieselaServer.get_token_information(self.token)[
                    1].to_dict()

                info["player"] = player_info
                info["user"] = user_info
                answer["info"] = info

        if command:
            player = GieselaServer.get_player(token=self.token)
            success = False

            if command == "play_pause":
                if player.is_playing:
                    self.log("paused")
                    player.pause()
                    success = True
                elif player.is_paused:
                    self.log("resumed")
                    player.resume()
                    success = True

            elif command == "skip":
                if player.current_entry:
                    if isinstance(player.current_entry, TimestampEntry):
                        player.goto_seconds(player.current_entry.current_sub_entry["end"])
                    else:
                        player.skip()

                    self.log("skipped")
                    success = True

            elif command == "revert":
                success = player.playlist.replay()

            elif command == "seek":
                target_seconds = command_data.get("value")
                if target_seconds and player.current_entry:
                    if 0 <= target_seconds <= player.current_entry.duration:
                        success = player.goto_seconds(target_seconds)
                        self.log("sought to", target_seconds)
                    else:
                        success = False
                else:
                    success = False

            elif command == "volume":
                target_volume = command_data.get("value")
                if target_volume:
                    if 0 <= target_volume <= 1:
                        player.volume = target_volume
                        self.log("set volume to", round(target_volume * 100, 1), "%")
                        success = True
                    else:
                        success = False
                else:
                    success = False

            answer["success"] = success

        self.sendMessage(json.dumps(answer))

    def handleConnected(self):
        print("[WEBSOCKET] <***REMOVED******REMOVED***> connected".format(self.address))
        GieselaServer.clients.append(self)

    def handleClose(self):
        GieselaServer.clients.remove(self)

        if self in GieselaServer.authenticated_clients:
            GieselaServer.authenticated_clients.remove(self)

        if self.registration_token:
            if GieselaServer.awaiting_registration.pop(self.registration_token, None):
                print("[WEBSOCKET] Removed <***REMOVED******REMOVED***>'s registration_token from awaiting list".format(
                    self.address))

        print("[WEBSOCKET] <***REMOVED******REMOVED***> disconnected".format(self.address))

    def register(self, server_id, author):
        token = hashlib.sha256(
            (server_id + author.id).encode("utf-8")).hexdigest()
        self.token = token
        GieselaServer.set_token_information(token, server_id, author)
        data = ***REMOVED***"token": token***REMOVED***
        self.sendMessage(json.dumps(data))
        print("[WEBSOCKET] <***REMOVED******REMOVED***> successfully registered ***REMOVED******REMOVED***".format(
            self.address, author))


class GieselaServer:
    clients = []
    authenticated_clients = []
    server = None
    bot = None
    _tokens = ***REMOVED******REMOVED***  # token: (server_id, author)
    awaiting_registration = ***REMOVED******REMOVED***

    def run(bot):
        GieselaServer.bot = bot

        try:
            GieselaServer._tokens = ***REMOVED***t: (s, WebAuthor.from_id(u)) for t, (s, u) in json.load(
                open("data/websocket_token.json", "r")).items()***REMOVED***
            print("[WEBSOCKET] loaded ***REMOVED******REMOVED*** tokens".format(
                len(GieselaServer._tokens)))
        except FileNotFoundError:
            print("[WEBSOCKET] failed to load tokens, there are none saved")

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
                  open("data/websocket_token.json", "w+"), indent=4)

    def generate_registration_token():
        while True:
            token = "".join(choice(ascii_lowercase) for _ in range(5))
            if token not in GieselaServer.awaiting_registration:
                return token

    def _broadcast_message(server_id, json_message):
        for auth_client in GieselaServer.authenticated_clients:
            # does this update concern this socket
            if GieselaServer.get_token_information(auth_client.token)[0] == server_id:
                auth_client.sendMessage(json_message)

    def get_player(token=None, server_id=None):
        if not token and not server_id:
            raise ValueError("Specify at least one of the two")
        server_id = GieselaServer.get_token_information(
            token)[0] if token else server_id
        try:
            player = asyncio.run_coroutine_threadsafe(GieselaServer.bot.get_player(server_id), GieselaServer.bot.loop).result()
            return player
        except Exception as e:
            print("[WEBSOCKET] encountered error while getting player:\n***REMOVED******REMOVED***".format(e))
            traceback.print_exc()
            return None

    def get_player_information(token=None, server_id=None):
        player = GieselaServer.get_player(token=token, server_id=server_id)
        if not player:
            return None

        if player.current_entry:
            entry = player.current_entry.to_web_dict()
            entry["progress"] = player.progress
        else:
            entry = None

        data = ***REMOVED***
            "entry":        entry,
            "queue":        player.playlist.get_web_dict(),
            "volume":       player.volume,
            "state_name":   str(player.state),
            "state":        player.state.value
        ***REMOVED***

        return data

    def send_player_information_update(server_id):
        if not GieselaServer.bot:
            return

        threading.Thread(
            target=GieselaServer._send_player_information_update, args=(server_id,)).start()

    def _send_player_information_update(server_id):
        try:
            message = ***REMOVED***
                "info":
                ***REMOVED***
                    "player": GieselaServer.get_player_information(server_id=server_id)
                ***REMOVED***
            ***REMOVED***

            json_message = json.dumps(message)
            print("[WEBSOCKET] Broadcasting player update to sockets")

            GieselaServer._broadcast_message(server_id, json_message)
        except Exception as e:
            traceback.print_exc()
