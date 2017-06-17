import json

import configparser


def encode_setting(value):
    json_handler = lambda v: json.dumps(v) + "\\json"

    handlers = {
        "int": lambda v: str(v) + "\\i",
        "float": lambda v: str(v) + "\\f",
        "list": json_handler,
        "tuple": json_handler,
        "dict": json_handler
    }
    return handlers.get(type(value).__name__, lambda v: v)(value)


def decode_setting(value):

    if type(value).__name__ != "str":
        return value

    if value in ["True", "False", "None"]:
        return {"True": True, "False": False, "None": None}[value]

    handlers = {
        "i": lambda v: int(v),
        "f": lambda v: float(v),
        "json": lambda v: json.loads(v)
    }
    val, sep, val_type = value.rpartition("\\")
    if not val:
        return value

    return handlers.get(val_type, lambda v: v)(val)


class Config:

    def __init__(self, config_file):
        self.config_file = config_file

        self.config = configparser.ConfigParser(interpolation=None)
        self.config.read(config_file, encoding='utf-8')
        self.auth = (self._token,)

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
    _email = None
    _password = None
    _token = None

    owner_id = None
    command_prefix = '!'
    bound_channels = set()
    owned_channels = set()
    autojoin_channels = set()

    default_volume = 0.3
    save_videos = True
    auto_summon = True
    auto_playlist = False
    auto_pause = True
    delete_messages = False
    delete_invoking = False
    debug_mode = False

    options_file = 'config/options.ini'
    papers_file = "config/papers.ini"
    cards_file = "data/cah/cards.ini"
    question_cards = "data/cah/question_cards.ini"
    radios_file = "config/radio_stations.ini"
    playlists_file = "config/playlists.ini"
    random_sets = "config/random_sets.ini"
    blacklist_file = 'config/blacklist.txt'
    log_file = "cache/logs/"
    auto_playlist_file = 'config/autoplaylist.txt'
    hangman_wordlist = "data/hangman_wordlist.txt"
    name_list = "data/names.txt"
