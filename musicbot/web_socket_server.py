import asyncio
import atexit
import hashlib
import inspect
import json
import threading
import traceback
import uuid
from json.decoder import JSONDecodeError
from random import choice
from string import ascii_lowercase

from musicbot import spotify
from musicbot.config import static_config
from musicbot.entry import TimestampEntry
from musicbot.radio import RadioStations
from musicbot.simple_web_socket_server import SimpleWebSocketServer, WebSocket
from musicbot.web_author import WebAuthor


class ErrorCode:
    registration_required = 1000


class GieselaWebSocket(WebSocket):

    def init(self):
        self.registration_token = None
        self._discord_server = None

    @property
    def discord_server(self):
        if not self._discord_server:
            server_id, *_ = GieselaServer.get_token_information(self.token)
            self._discord_server = GieselaServer.bot.get_server(server_id)

        return self._discord_server

    def log(self, *messages):
        message = " ".join(str(msg) for msg in messages)

        try:
            server_id, author = GieselaServer.get_token_information(self.token)
            identification = "[{}@{}] | {}".format(author.name, self.discord_server.name, self.address[0])
        except AttributeError:
            identification = self.address

        print("[WEBSOCKET] <{}> {}".format(identification, message))

    def handleMessage(self):
        try:
            try:
                data = json.loads(self.data)
            except JSONDecodeError:
                print("[WEBSOCKET] <{}> sent non-json: {}".format(self.address, self.data))
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
                    "registration_token": registration_token,
                    "command_prefix": static_config.command_prefix
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

    def _call_function_main_thread(self, func, *args, wait_for_result=False, **kwargs):
        fut = asyncio.run_coroutine_threadsafe(asyncio.coroutine(func)(*args, **kwargs), GieselaServer.bot.loop)

        if wait_for_result:
            return fut.result()
        else:
            return fut

    async def _tuple_generator(self, collection):
        for i, el in enumerate(collection):
            yield i, el

    async def play_entry(self, player, answer, kind, item, searcher, mode):
        success = False
        entry_gen = []

        url = item["url"]

        if searcher == "SpotifySearcher":
            if kind == "playlist":
                playlist = spotify.SpotifyPlaylist.from_url(url)
                self.log("adding Spotify playlist {}".format(playlist))
                entry_gen = playlist.get_spotify_entries_generator(player.queue)
                success = True
            elif kind == "entry":
                entry = spotify.SpotifyTrack.from_url(url)
                entry_gen = self._tuple_generator([await entry.get_spotify_entry(player.queue)])
                success = True

        elif searcher in ("YoutubeSearcher", "SoundcloudSearcher"):
            entry_gen = await player.queue.get_entry_gen(url)
            success = True

        answer["success"] = bool(success)
        self.sendMessage(json.dumps(answer))

        if mode in "random":
            placement = mode
        elif mode in "now":
            if player.current_entry:
                player.skip()

            placement = 0
        elif mode == "next":
            placement = 0
        else:
            placement = None

        try:
            async for ind, entry in entry_gen:
                if entry:
                    player.queue._add_entry(entry, placement=placement)
        except Exception:
            traceback.print_exc()

    def handleAuthenticatedMessage(self, data):
        answer = {
            "response": True,
            "request_id": data.get("id")
        }

        request = data.get("request")
        command = data.get("command")
        command_data = data.get("command_data", {})

        if request:
            # send all the information one can acquire
            if request == "send_information":
                self.log("asked for general information")
                info = {}
                player_info = GieselaServer.get_player_information(self.token)
                user_info = GieselaServer.get_token_information(self.token)[1].to_dict()

                info["player"] = player_info
                info["user"] = user_info
                answer["info"] = info

            elif request == "send_playlists":
                self.log("asked for playlists")

                player = GieselaServer.get_player(token=self.token)
                answer["playlists"] = player.bot.playlists.get_all_web_playlists(player.queue)

            elif request == "send_radio_stations":
                self.log("asked for the radio stations")

                answer["radio_stations"] = [station.to_dict() for station in RadioStations.get_all_stations()]

            elif request == "send_lyrics":
                self.log("asked for lyrics")
                player = GieselaServer.get_player(token=self.token)

                if player.current_entry:
                    lyrics = player.current_entry.lyrics
                else:
                    lyrics = None

                answer["lyrics"] = lyrics

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
                    success = False

                    if isinstance(player.current_entry, TimestampEntry):
                        success = player.seek(player.current_entry.current_sub_entry["end"])

                    if not success:
                        player.skip()
                        success = True

                    self.log("skipped")

            elif command == "revert":
                success = self._call_function_main_thread(player.queue.replay, wait_for_result=True, revert=True)

            elif command == "seek":
                target_seconds = command_data.get("value")
                if target_seconds and player.current_entry:
                    if 0 <= target_seconds <= player.current_entry.duration:
                        success = player.seek(target_seconds)
                        self.log("sought to", target_seconds)
                    else:
                        success = False
                else:
                    success = False

            elif command == "volume":
                target_volume = command_data.get("value")
                if target_volume is not None:
                    if 0 <= target_volume <= 1:
                        player.volume = target_volume
                        self.log("set volume to", round(target_volume * 100, 1), "%")
                        success = True
                    else:
                        success = False
                else:
                    success = False

            elif command == "move":
                from_index = command_data.get("from")
                to_index = command_data.get("to")

                success = bool(self._call_function_main_thread(player.queue.move, from_index, to_index, wait_for_result=True))
                self.log("moved an entry from", from_index, "to", to_index)

            elif command == "clear":
                player.queue.clear()
                self.log("cleared the queue")
                success = True

            elif command == "shuffle":
                player.queue.shuffle()
                self.log("shuffled")
                success = True

            elif command == "remove":
                remove_index = command_data.get("index")
                success = bool(self._call_function_main_thread(player.queue.remove_position, remove_index, wait_for_result=True) is not None)
                self.log("removed", remove_index)

            elif command == "promote":
                promote_index = command_data.get("index")
                success = bool(self._call_function_main_thread(player.queue.promote_position, promote_index, wait_for_result=True))
                self.log("promoted", promote_index)

            elif command == "replay":
                replay_index = command_data.get("index")
                success = self._call_function_main_thread(player.queue.replay, replay_index, wait_for_result=True)
                self.log("replayed", replay_index)

            elif command == "cycle_repeat":
                success = self._call_function_main_thread(player.repeat, wait_for_result=True)
                self.log("set repeat state to", player.repeatState)

            elif command == "playlist_play":
                playlist_id = command_data.get("playlist_id")
                playlist_index = command_data.get("index")

                playlist = GieselaServer.bot.playlists.get_playlist(playlist_id, player.queue)

                if playlist:
                    if 0 <= playlist_index < len(playlist["entries"]):
                        self._call_function_main_thread(player.queue._add_entry, playlist["entries"][playlist_index])
                        self.log("loaded index", playlist_index, "from playlist", playlist_id)
                        success = True
                    else:
                        success = False
                else:
                    success = False

            elif command == "load_playlist":
                playlist_id = command_data.get("id")
                load_mode = command_data.get("mode")

                if playlist_id:
                    playlist = GieselaServer.bot.playlists.get_playlist(playlist_id, player.queue)

                    if playlist:
                        if load_mode == "replace":
                            player.queue.clear()

                        self._call_function_main_thread(player.queue.add_entries, playlist["entries"])
                        self.log("loaded playlist", playlist_id, "with mode", load_mode)
                        success = True
                    else:
                        success = False
                else:
                    success = False

            elif command == "play_radio":
                station_id = command_data.get("id")
                play_mode = command_data.get("mode", "now")
                station = RadioStations.get_station(station_id)

                self.log("enqueued radio station", station.name, "(mode " + play_mode + ")")

                if station:
                    self._call_function_main_thread(player.queue.add_radio_entry, station, now=(play_mode == "now"), wait_for_result=True, revert=True)
                    success = True
                else:
                    success = False

            elif command == "play":
                item = command_data.get("item")
                kind = command_data.get("kind")  # entry, playlist
                mode = command_data.get("mode", "queue")  # now, next, queue, random
                searcher = command_data.get("searcher")  # YoutubeSearcher, SpotifySearcher, SoundcloudSearcher

                # enter async env with run_coroutine_threadsafe. Handle Spotify and then just feed the queue add_entry with the url.

                self.log("playing {} from {} with mode {}".format(kind, searcher, mode))
                self._call_function_main_thread(self.play_entry, player, answer, kind, item, searcher, mode)
                # let the play_entry function handle the response
                return

            answer["success"] = bool(success)

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
        salt = uuid.uuid4().hex
        token = hashlib.sha256((server_id + author.id + salt).encode("utf-8")).hexdigest()
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

    def _broadcast_message(server_id, json_message):
        for auth_client in GieselaServer.authenticated_clients:
            # does this update concern this socket
            if GieselaServer.get_token_information(auth_client.token)[0] == server_id:
                auth_client.sendMessage(json_message)

    def broadcast_message(server_id, message):
        try:
            threading.Thread(target=GieselaServer._broadcast_message, args=(server_id, message)).start()
        except Exception as e:
            traceback.print_exc()

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
            "entry":                entry,
            "queue":                player.queue.get_web_dict(),
            "volume":               player.volume,
            "state_name":           str(player.state),
            "state":                player.state.value,
            "repeat_state_name":    str(player.repeatState),
            "repeat_state":         player.repeatState.value,
        }

        return data

    def _send_player_information(server_id):
        message = {
            "info":
            {
                "player": GieselaServer.get_player_information(server_id=server_id)
            }
        }

        GieselaServer._broadcast_message(server_id, json.dumps(message))

    def send_player_information(server_id):
        if not GieselaServer.bot:
            return

        if not GieselaServer.authenticated_clients:
            return

        frame = inspect.currentframe()
        outer_frames = inspect.getouterframes(frame)
        caller = outer_frames[1]
        print("[WEBSOCKET] Broadcasting player update to {} socket(s). Caused by \"{}\"".format(len(GieselaServer.authenticated_clients), caller.function))

        threading.Thread(target=GieselaServer._send_player_information, args=(server_id, )).start()

    def send_small_update(server_id, **kwargs):
        if not GieselaServer.bot:
            return

        if not GieselaServer.authenticated_clients:
            return

        frame = inspect.currentframe()
        outer_frames = inspect.getouterframes(frame)
        caller = outer_frames[1]
        print("[WEBSOCKET] Broadcasting update to {} socket(s). Caused by \"{}\"".format(len(GieselaServer.authenticated_clients), caller.function))

        message = {
            "update": kwargs
        }

        GieselaServer.broadcast_message(server_id, json.dumps(message))
