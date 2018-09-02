import configparser
import json
import os
import pickle
from typing import Any


class ConfigDefaults:
    token = os.getenv("token")

    google_api_key = os.getenv("google_api_key")

    html_parser = "html.parser"

    webiesela_port = 30000
    start_webiesela = True

    command_prefix = os.getenv("command_prefix", "!")
    message_decay_delay = 30
    vc_disconnect_delay = 20

    voice_channel_home = None
    idle_game = ""

    client_language = "en-gb"
    server_languages = {}
    user_languages = {}

    history_limit = 200

    lavalink_ws_url = os.getenv("lavalink_ws_url")
    lavalink_rest_url = os.getenv("lavalink_rest_url")
    lavalink_password = os.getenv("lavalink_password")

    auto_pause = True
    default_volume = 100

    webiesela_cert = "data/cert"
    options_file = "data/options.ini"
    radio_stations_config = "data/radio_stations.yml"
    playlists_file = "data/playlists/playlists"
    lyrics_cache = "data/lyrics"


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


class Config(ConfigDefaults):

    def __init__(self, config_file):
        self.config_file = config_file

        self.config = configparser.ConfigParser(interpolation=None)
        self.config.read(config_file, encoding="utf-8")

    def get_all_options(self):
        options = []
        if not self.config.has_section("Settings"):
            return []

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

    def __getattribute__(self, item: str) -> Any:
        if item in dir(ConfigDefaults):
            return decode_setting(self.config.get("Settings", item, fallback=getattr(ConfigDefaults, item)))
        else:
            return super().__getattribute__(item)

    def __setattr__(self, key: str, value: Any):
        if key in dir(ConfigDefaults):
            self.config.set("Settings", key, encode_setting(value))
            self.config.write(open(self.config_file, "w+"))
        else:
            super().__setattr__(key, value)


static_config: Config = Config(ConfigDefaults.options_file)
