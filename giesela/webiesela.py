import asyncio
import atexit
import hashlib
import inspect
import logging
import os
import pickle
import random
import rapidjson
import threading
from pathlib import Path
from string import ascii_lowercase
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Tuple

from discord import Guild

from giesela.lib.web_author import WebAuthor
from . import utils
from .lib.web_socket_server import SimpleSSLWebSocketServer, SimpleWebSocketServer, WebSocket

if TYPE_CHECKING:
    from giesela import GieselaPlayer, Giesela
    from .extensions.webiesela import Webiesela

log = logging.getLogger(__name__)


class ErrorCode:
    registration_required = 1000


def _call_function_main_thread(func: Callable, *args, wait_for_result: bool = False, **kwargs) -> Any:
    fut = asyncio.run_coroutine_threadsafe(asyncio.coroutine(func)(*args, **kwargs), WebieselaServer.bot.loop)

    if wait_for_result:
        return fut.result()
    else:
        return fut


def playlists_overview() -> List[Dict[str, Any]]:
    _playlists = WebieselaServer.cog.playlist_manager.playlists
    playlists = []
    for playlist in _playlists:
        author = WebAuthor.from_user(playlist.author).to_dict()
        entries = [pl_entry.entry.to_dict() for pl_entry in playlist]
        pl = dict(id=playlist.gpl_id.hex, name=playlist.name, description=playlist.description, cover=playlist.cover, author=author,
                  entries=entries, duration=playlist.total_duration, human_dur=utils.format_time(playlist.total_duration, max_specifications=1))
        playlists.append(pl)
    return playlists


def radio_stations_overview() -> List[Dict[str, Any]]:
    stations = []
    for station in WebieselaServer.cog.radio_station_manager:
        data = station.to_dict()
        data.update(id=station.name, language="DEPRECATED", cover=station.logo)
        stations.append(data)
    return stations


def patch_entry_data(data: Dict[str, Any]):
    requester = data.pop("requester")
    data["requester"] = dict(id=requester.id, name=requester.name)


def get_queue_information(player: "GieselaPlayer") -> Dict[str, Any]:
    queue = []
    for entry in player.queue.entries:
        data = entry.to_dict()
        patch_entry_data(data)
        queue.append(data)
    history = []
    for entry in player.queue.history:
        data = entry.to_dict()
        patch_entry_data(data)
        history.append(data)
    return dict(queue=queue, history=history)


class GieselaWebSocket(WebSocket):
    _discord_guild: Optional[Guild]
    token: str
    registration_token: Optional[str]

    def init(self):
        self.registration_token = None
        self._discord_guild = None

    @property
    def discord_guild(self) -> Guild:
        if not self._discord_guild:
            guild_id, *_ = WebieselaServer.get_token_information(self.token)
            self._discord_guild = WebieselaServer.bot.get_guild(guild_id)

        return self._discord_guild

    def log(self, *messages):
        message = " ".join(str(msg) for msg in messages)

        try:
            guild_id, author = WebieselaServer.get_token_information(self.token)
            identification = "[{}@{}] | {}".format(author.name, self.discord_guild.name, self.address[0])
        except AttributeError:
            identification = self.address

        log.info("<{}> {}".format(identification, message))

    def handleMessage(self):
        try:
            try:
                data = rapidjson.loads(self.data)
            except ValueError:
                log.warning("[WEBSOCKET] <{}> sent non-json: {}".format(self.address, self.data))
                return

            token = data.get("token", None)
            if token:
                info = WebieselaServer.get_token_information(token)
                if info:
                    self.token = token
                    if self not in WebieselaServer.authenticated_clients:
                        WebieselaServer.authenticated_clients.append(self)  # register for updates
                    # handle all the other shit over there
                    self.handle_authenticated_msg(data)
                    return
                else:
                    log.warning("[WEBSOCKET] <{}> invalid token provided".format(
                        self.address))
            else:
                log.warning("[WEBSOCKET] <{}> no token provided".format(self.address))

            register = data.get("request", None) == "register"
            if register:
                registration_token = generate_registration_token()
                WebieselaServer.awaiting_registration[registration_token] = self.register  # setting the callback

                self.registration_token = registration_token

                log.info("[WEBSOCKET] <{}> Waiting for registration with token: {}".format(
                    self.address, registration_token))

                answer = {
                    "response": True,
                    "registration_token": registration_token
                }

                self.sendMessage(rapidjson.dumps(answer))
                return
            else:
                log.warning("[WEBSOCKET] <{}> Didn't ask to be registered".format(
                    self.address))
                answer = {
                    "response": True,
                    "error": (ErrorCode.registration_required, "registration required")
                }
                self.sendMessage(rapidjson.dumps(answer))

        except Exception:
            log.exception("error while handling message")
            raise

    async def play_entry(self, player: "GieselaPlayer", answer: Dict[str, Any], kind: str, item: Dict[str, Any], searcher: str, mode: str):
        success = False
        entry_gen = []

        url = item["url"]

        guild_id, author = WebieselaServer.get_token_information(self.token)

        if searcher in ("YoutubeSearcher", "SoundcloudSearcher"):
            entry_gen = await player.extractor.get(url)
            success = True

        answer["success"] = bool(success)
        self.sendMessage(rapidjson.dumps(answer))

        if mode in "random":
            placement = mode
        elif mode in "now":
            if player.current_entry:
                _call_function_main_thread(player.skip)

            placement = 0
        elif mode == "next":
            placement = 0
        else:
            placement = None

        try:
            async for ind, entry in entry_gen:
                if entry:
                    player.queue.add_entry(entry, requester=author.discord_user, position=placement)
        except Exception:
            log.exception("error while adding entry")

    def handle_authenticated_msg(self, data: Dict[str, Any]):
        answer = {
            "response": True,
            "request_id": data.get("id")
        }

        request = data.get("request")
        command = data.get("command")
        command_data = data.get("command_data", {})
        guild_id, author = WebieselaServer.get_token_information(self.token)

        if request:
            player = WebieselaServer.get_player(token=self.token)

            # send all the information one can acquire
            if request == "send_information":
                self.log("asked for general information")
                info = {}
                player_info = WebieselaServer.get_player_information(self.token)
                user_info = WebieselaServer.get_token_information(self.token)[1].to_dict()

                info["player"] = player_info
                info["user"] = user_info
                answer["info"] = info

            elif request == "send_playlists":
                self.log("asked for playlists")

                answer["playlists"] = playlists_overview()

            elif request == "send_radio_stations":
                self.log("asked for the radio stations")

                answer["radio_stations"] = radio_stations_overview()

        if command:
            player = WebieselaServer.get_player(token=self.token)
            success = False

            if command == "play_pause":
                if player.is_playing:
                    self.log("paused")
                    _call_function_main_thread(player.pause, wait_for_result=True)
                    success = True
                elif player.is_paused:
                    self.log("resumed")
                    _call_function_main_thread(player.resume, wait_for_result=True)
                    success = True

            elif command == "skip":
                if player.current_entry:
                    success = False

                    if not success:
                        _call_function_main_thread(player.skip, wait_for_result=True)
                        success = True

                    self.log("skipped")

            elif command == "revert":
                success = _call_function_main_thread(player.queue.replay, wait_for_result=True, revert=True)

            elif command == "seek":
                target_seconds = command_data.get("value")
                if target_seconds and player.current_entry:
                    if 0 <= target_seconds <= player.current_entry.duration:
                        _call_function_main_thread(player.seek, target_seconds, wait_for_result=True)
                        self.log("sought to", target_seconds)
                    else:
                        success = False
                else:
                    success = False

            elif command == "volume":
                target_volume = command_data.get("value")
                if target_volume is not None:
                    if 0 <= target_volume <= 1:
                        _call_function_main_thread(player.set_volume, target_volume, wait_for_result=True)
                        self.log("set volume to", round(target_volume * 100, 1), "%")
                        success = True
                    else:
                        success = False
                else:
                    success = False

            elif command == "move":
                from_index = command_data.get("from")
                to_index = command_data.get("to")

                success = bool(_call_function_main_thread(player.queue.move, from_index, to_index, wait_for_result=True))
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
                success = bool(_call_function_main_thread(player.queue.remove, remove_index, wait_for_result=True))
                self.log("removed", remove_index)

            elif command == "promote":
                promote_index = command_data.get("index")
                success = bool(_call_function_main_thread(player.queue.move, promote_index, wait_for_result=True))
                self.log("promoted", promote_index)

            elif command == "replay":
                replay_index = command_data.get("index")
                success = bool(_call_function_main_thread(player.queue.replay, replay_index, wait_for_result=True))
                self.log("replayed", replay_index)

            elif command == "playlist_play":
                playlist_id = command_data.get("playlist_id")
                playlist_index = command_data.get("index")

                playlist = WebieselaServer.cog.playlist_manager.get_playlist(playlist_id)

                if playlist:
                    if 0 <= playlist_index < len(playlist):
                        entry = playlist.entries[playlist_index].entry
                        _call_function_main_thread(player.queue.add_entry, entry, requester=author.discord_user, wait_for_result=True)
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
                    playlist = WebieselaServer.cog.playlist_manager.get_playlist(playlist_id)

                    if playlist:
                        if load_mode == "replace":
                            player.queue.clear()

                        _call_function_main_thread(playlist.play, player.queue, requester=author.discord_user, wait_for_result=True)
                        self.log("loaded playlist", playlist_id, "with mode", load_mode)
                        success = True
                    else:
                        success = False
                else:
                    success = False

            elif command == "play_radio":
                station_id = command_data.get("id")
                play_mode = command_data.get("mode", "now")
                station = WebieselaServer.cog.radio_station_manager.find_station(station_id)

                if station:
                    self.log("enqueued radio station", station.name, "(mode " + play_mode + ")")
                    entry = _call_function_main_thread(player.extractor.get_radio_entry, station, wait_for_result=True)
                    _call_function_main_thread(player.queue.add_entry, entry, requester=author.discord_user, wait_for_result=True)
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
                _call_function_main_thread(self.play_entry, player, answer, kind, item, searcher, mode)
                # let the play_entry function handle the response
                return

            answer["success"] = bool(success)

        self.sendMessage(rapidjson.dumps(answer))

    def handleConnected(self):
        log.info("[WEBSOCKET] <{}> connected".format(self.address))
        WebieselaServer.clients.append(self)

    def handleClose(self):
        WebieselaServer.clients.remove(self)

        if self in WebieselaServer.authenticated_clients:
            WebieselaServer.authenticated_clients.remove(self)

        if self.registration_token:
            if WebieselaServer.awaiting_registration.pop(self.registration_token, None):
                log.info("[WEBSOCKET] Removed <{}>'s registration_token from awaiting list".format(self.address))

        log.info("[WEBSOCKET] <{}> disconnected".format(self.address))

    def register(self, guild_id: int, author: WebAuthor):
        salt = os.urandom(20)
        user_identifier = f"{guild_id}:{author.id}"
        token = hashlib.sha256(user_identifier.encode("utf-8") + salt).hexdigest()
        self.token = token
        WebieselaServer.set_token_information(token, guild_id, author)
        data = {"token": token}
        self.sendMessage(rapidjson.dumps(data))
        log.info("[WEBSOCKET] <{}> successfully registered {}".format(self.address, author))


def generate_registration_token() -> str:
    while True:
        token = "".join(random.choice(ascii_lowercase) for _ in range(5))
        if token not in WebieselaServer.awaiting_registration:
            return token


def find_cert_files(directory: str) -> Tuple[Optional[str], Optional[str]]:
    folder = Path(directory)
    folder.mkdir(exist_ok=True)

    files = list(folder.glob("*"))

    if not files:
        return None, None
    if len(files) == 1:
        return str(files[0].absolute()), None
    if len(files) == 2:
        certfile = keyfile = None

        for file in files:
            if file.suffix:
                target = file.suffix[1:].lower()
            else:
                target = file.name.lower()
            if target in ("cer", "cert", "crt", "certificate", "pem"):
                certfile = str(file.absolute())
            elif target in ("private", "privatekey", "key", "keyfile"):
                keyfile = str(file.absolute())
            else:
                raise EnvironmentError(f"Can't distinguish public from private in your cert folder ({folder})")
        return certfile, keyfile
    else:
        raise EnvironmentError(f"Your certificates folder has too many files in it! ({folder})")


class WebieselaServer:
    clients = []
    authenticated_clients = []
    server: SimpleWebSocketServer = None
    cog: "Webiesela" = None
    bot: "Giesela" = None
    _tokens: Dict[str, Tuple[int, WebAuthor]] = {}
    awaiting_registration: Dict[str, Callable] = {}

    @classmethod
    def run(cls, cog: "Webiesela"):
        cls.cog = cog
        cls.bot = cog.bot

        try:
            with open("data/websocket_token.bin", "rb") as fp:
                data = pickle.load(fp)
            cls._tokens = {t: (s, WebAuthor.from_id(u)) for t, (s, u) in data.items()}
            log.info("[WEBSOCKET] loaded {} tokens".format(len(cls._tokens)))
        except FileNotFoundError:
            log.warning("[WEBSOCKET] failed to load tokens, there are none saved")

        cert_file, key_file = find_cert_files(cog.config.app.files.certificates)
        if cert_file:
            log.info("found cert file, creating SSL Server!")
            server = SimpleSSLWebSocketServer("", cog.config.app.webiesela.port, GieselaWebSocket, cert_file, key_file)
        else:
            log.warning("no certificate found, using default server")
            server = SimpleWebSocketServer("", cog.config.app.webiesela.port, GieselaWebSocket)

        cls.server = server
        atexit.register(cls.server.close)
        # new thread because it's blocking
        threading.Thread(target=cls.server.serveforever).start()
        log.debug("[WEBSOCKET] up and running")

    @classmethod
    def register_information(cls, guild_id: int, author_id: int, token: str) -> bool:
        callback = cls.awaiting_registration.pop(token, None)
        author = WebAuthor.from_id(author_id)
        if not callback:
            return False

        callback(guild_id, author)
        return True

    @classmethod
    def get_token_information(cls, token: str) -> Optional[Tuple[int, WebAuthor]]:
        return cls._tokens.get(token, None)

    @classmethod
    def set_token_information(cls, token: str, guild_id: int, author: WebAuthor):
        cls._tokens[token] = (guild_id, author)
        data = {t: (s, u.id) for t, (s, u) in cls._tokens.items()}

        with open("data/websocket_token.bin", "wb+") as fp:
            pickle.dump(data, fp)

    @classmethod
    def _broadcast_message(cls, guild_id: int, json_message: str):
        for auth_client in cls.authenticated_clients:
            # does this update concern this socket
            if cls.get_token_information(auth_client.token)[0] == guild_id:
                auth_client.sendMessage(json_message)

    @classmethod
    def broadcast_message(cls, guild_id: int, message: str):
        try:
            threading.Thread(target=cls._broadcast_message, args=(guild_id, message)).start()
        except Exception:
            log.exception("error while broadcasting")

    @classmethod
    def get_player(cls, token: str = None, guild_id: int = None) -> Optional["GieselaPlayer"]:
        if not token and not guild_id:
            raise ValueError("Specify at least one of the two")
        guild_id = cls.get_token_information(token)[0] if token else guild_id
        try:
            player = asyncio.run_coroutine_threadsafe(cls.cog.get_player(guild_id), cls.bot.loop).result()
            return player
        except Exception as e:
            log.warning("encountered error while getting player:\n{}".format(e))
            return None

    @classmethod
    def get_player_information(cls, token: str = None, guild_id: int = None) -> Optional[Dict[str, Any]]:
        player = cls.get_player(token=token, guild_id=guild_id)
        if not player:
            return None

        if player.current_entry:
            entry = player.current_entry.to_dict()
            patch_entry_data(entry)
        else:
            entry = None

        data = {
            "entry": entry,
            "queue": get_queue_information(player),
            "volume": player.volume,
            "state": player.state.value
        }

        return data

    @classmethod
    def _send_player_information(cls, guild_id: int):
        message = {
            "info":
                {
                    "player": cls.get_player_information(guild_id=guild_id)
                }
        }

        cls._broadcast_message(guild_id, rapidjson.dumps(message))

    @classmethod
    def send_player_information(cls, guild_id: int):
        if not cls.bot:
            return

        if not cls.authenticated_clients:
            return

        frame = inspect.currentframe()
        outer_frames = inspect.getouterframes(frame)
        caller = outer_frames[1]
        log.debug("Broadcasting player update to {} socket(s). Caused by \"{}\"".format(len(cls.authenticated_clients), caller.function))

        threading.Thread(target=cls._send_player_information, args=(guild_id,)).start()

    @classmethod
    def small_update(cls, guild_id: int, **kwargs):
        if not cls.bot:
            return

        if not cls.authenticated_clients:
            return

        frame = inspect.currentframe()
        outer_frames = inspect.getouterframes(frame)
        caller = outer_frames[1]
        log.debug("Broadcasting update to {} socket(s). Caused by \"{}\"".format(len(cls.authenticated_clients), caller.function))

        message = {
            "update": kwargs
        }

        cls.broadcast_message(guild_id, rapidjson.dumps(message))
