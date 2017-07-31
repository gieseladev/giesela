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

    def handleMessage(self):
        try:
            try:
                data = json.loads(self.data)
            except JSONDecodeError:
                print(
                    "[WEBSOCKET] <{}> sent non-json: {}".format(self.address, self.data))
                return

            token = data.get("token", None)
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
                    print("[WEBSOCKET] <{}> invalid token provided".format(
                        self.address))
            else:
                print("[WEBSOCKET] <{}> no token provided".format(self.address))

            register = data.get("request", None) == "register"
            if register:
                registration_token = GieselaServer.generate_registration_token()
                GieselaServer.awaiting_registration[
                    registration_token] = self.register  # setting the callback

                self.registration_token = registration_token

                print("[WEBSOCKET] <{}> Waiting for registration with token: {}".format(
                    self.address, registration_token))

                answer = {
                    "response": True,
                    "registration_token": registration_token
                }

                self.sendMessage(json.dumps(answer))
                return
            else:
                print("[WEBSOCKET] <{}> Didn't ask to be registered".format(
                    self.address))
                answer = {
                    "response": True,
                    "error": (ErrorCode.registration_required, "registration required")
                }
                self.sendMessage(json.dumps(answer))

        except Exception as e:
            traceback.print_exc()
            raise

    def handleAuthenticatedMessage(self, data):
        answer = {
            "response": True
        }

        request = data.get("request")
        command = data.get("command")
        command_data = data.get("command_data", {})

        if request:
            # send all the information one can acquire
            if request == "send_information":
                info = {}
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
                    player.pause()
                    success = True
                elif player.is_paused:
                    player.resume()
                    success = True

            elif command == "skip":
                if player.current_entry:
                    if isinstance(player.current_entry, TimestampEntry):
                        player.goto_seconds(player.current_entry.current_sub_entry["end"])
                    else:
                        player.skip()

                    success = True

            elif command == "revert":
                success = player.playlist.replay()

            elif command == "seek":
                target_seconds = command_data.get("value")
                if target_seconds and player.current_entry:
                    if 0 <= target_seconds <= player.current_entry.duration:
                        success = player.goto_seconds(target_seconds)
                    else:
                        success = False
                else:
                    success = False

            elif command == "volume":
                target_volume = command_data.get("value")
                if target_volume:
                    if 0 <= target_volume <= 1:
                        player.volume = target_volume
                        success = True
                    else:
                        success = False
                else:
                    success = False

            answer["success"] = success

        self.sendMessage(json.dumps(answer))

    def handleConnected(self):
        print("[WEBSOCKET] <{}> connected".format(self.address))
        GieselaServer.clients.append(self)

    def handleClose(self):
        GieselaServer.clients.remove(self)

        if self in GieselaServer.authenticated_clients:
            GieselaServer.authenticated_clients.remove(self)

        if self.registration_token:
            if GieselaServer.awaiting_registration.pop(self.registration_token, None):
                print("[WEBSOCKET] Removed <{}>'s registration_token from awaiting list".format(
                    self.address))

        print("[WEBSOCKET] <{}> disconnected".format(self.address))

    def register(self, server_id, author):
        token = hashlib.sha256(
            (server_id + author.id).encode("utf-8")).hexdigest()
        self.token = token
        GieselaServer.set_token_information(token, server_id, author)
        data = {"token": token}
        self.sendMessage(json.dumps(data))
        print("[WEBSOCKET] <{}> successfully registered {}".format(
            self.address, author))


class GieselaServer:
    clients = []
    authenticated_clients = []
    server = None
    bot = None
    _tokens = {}  # token: (server_id, author)
    awaiting_registration = {}

    def run(bot):
        GieselaServer.bot = bot

        try:
            GieselaServer._tokens = {t: (s, WebAuthor.from_id(u)) for t, (s, u) in json.load(
                open("data/websocket_token.json", "r")).items()}
            print("[WEBSOCKET] loaded {} tokens".format(
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
        json.dump({t: (s, u.id) for t, (s, u) in GieselaServer._tokens.items()},
                  open("data/websocket_token.json", "w+"), indent=4)

    def generate_registration_token():
        while True:
            token = "".join(choice(ascii_lowercase) for _ in range(5))
            if token not in GieselaServer.awaiting_registration:
                return token

    def get_player(token=None, server_id=None):
        if not token and not server_id:
            raise ValueError("Specify at least one of the two")
        server_id = GieselaServer.get_token_information(
            token)[0] if token else server_id
        try:
            player = asyncio.run_coroutine_threadsafe(GieselaServer.bot.get_player(server_id), GieselaServer.bot.loop).result()
            return player
        except Exception as e:
            print("[WEBSOCKET] encountered error while getting player:\n{}".format(e))
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

        data = {
            "entry":        entry,
            "queue":        player.playlist.get_web_dict(),
            "volume":       player.volume,
            "state_name":   str(player.state),
            "state":        player.state.value
        }

        return data

    def send_player_information_update(server_id):
        if not GieselaServer.bot:
            return

        threading.Thread(
            target=GieselaServer._send_player_information_update, args=(server_id,)).start()

    def _send_player_information_update(server_id):
        try:
            message = {
                "info":
                {
                    "player": GieselaServer.get_player_information(server_id=server_id)
                }
            }

            json_message = json.dumps(message)
            print("[WEBSOCKET] Broadcasting player update to sockets")

            for auth_client in GieselaServer.authenticated_clients:
                # does this update concern this socket
                if GieselaServer.get_token_information(auth_client.token)[0] == server_id:
                    auth_client.sendMessage(json_message)
        except Exception as e:
            traceback.print_exc()
