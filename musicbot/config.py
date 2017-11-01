import configparser
import json
import pickle


def encode_setting(value):
    def json_handler(v): return json.dumps(v) + "\\json"

    handlers = {
        "int": lambda v: str(v) + "\\i",
        "float": lambda v: str(v) + "\\f",
        "list": json_handler,
        "tuple": json_handler,
        "dict": json_handler
    }
    return handlers.get(type(value).__name__, lambda v: str(v))(value)


def decode_setting(value):

    if type(value).__name__ != "str":
        return value

    if value in ["True", "False", "None"]:
        return {"True": True, "False": False, "None": None}[value]

    handlers = {
        "i": lambda v: int(v),
        "f": lambda v: float(v),
        "json": lambda v: json.loads(v),
        "pickle": lambda v: pickle.loads(bytes.fromhex(v))
    }
    val, sep, val_type = value.rpartition("\\")
    if not val:
        return value

    return handlers.get(val_type, lambda v: v)(val)


def beautify_value(value):
    if isinstance(value, bool):
        return ("no", "yes")[int(value)]
    elif isinstance(value, float):
        return round(value, 2)
    elif isinstance(value, (list, set, tuple)):
        return ", ".join(value)

    return value


class Config:

    def __init__(self, config_file):
        self.config_file = config_file

        self.config = configparser.ConfigParser(interpolation=None)
        self.config.read(config_file, encoding="utf-8")

        self.auth = (self._token,)

    def get_all_options(self):
        options = []
        for option in self.config.options("Settings"):
            custom_value = getattr(self, option)
            default_value = getattr(ConfigDefaults, option)

            if custom_value != default_value:
                options.append((option, beautify_value(custom_value)))

        return options

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __contains__(self, item):
        return item in self.config.options("Settings")

    def __getattr__(self, name):
        if name in dir(ConfigDefaults):
            return decode_setting(self.config.get("Settings", name, fallback=getattr(ConfigDefaults, name)))
        else:
            return self.__dict__[name]

    def __setattr__(self, name, value):
        if name in dir(ConfigDefaults):
            self.config.set("Settings", name, encode_setting(value))
            self.config.write(open(self.config_file, "w+"))
        else:
            self.__dict__[name] = value


class ConfigDefaults:
    _token = None

    google_api_key = "AIzaSyDb9eZgqs86NlNtekfFHKWN5jaaR-eZFQY"

    html_parser = "html.parser"

    entry_type_emojis = {
        "YoutubeEntry":     ":black_circle:",
        "TimestampEntry":   ":large_blue_circle:",
        "GieselaEntry":     ":white_circle:",
        "SpotifyEntry":     ":red_circle:",
        "DiscogsEntry":     ":large_orange_diamond:",
        "VGMEntry":         ":large_blue_diamond:"
    }

    owner_id = None
    command_prefix = "!"
    bound_channels = set()
    owned_channels = set()
    private_chat_commands = set()
    idle_game = ""

    client_language = "en-gb"
    server_languages = {}
    user_languages = {}

    history_limit = 200

    default_volume = 0.3
    volume_power = 3
    save_videos = True
    auto_playlist = False
    auto_pause = True
    delete_messages = False
    delete_invoking = False
    debug_mode = False
    open_websocket = True
    delete_unrelated_in_owned = False

    options_file = "config/options.ini"
    cards_file = "data/cah/cards.ini"
    question_cards = "data/cah/question_cards.ini"
    radios_file = "data/radio_stations.json"
    playlists_file = "data/playlists.json"  # deprecated
    playlists_location = "data/playlists"
    random_sets = "data/random_sets.ini"
    settings_file = "data/settings.bin"
    blacklist_file = "config/blacklist.txt"
    auto_playlist_file = "config/autoplaylist.txt"
    hangman_wordlist = "data/hangman_wordlist.txt"
    name_list = "data/names.txt"
    lyrics_cache = "cache/lyrics"


static_config = Config(ConfigDefaults.options_file)
