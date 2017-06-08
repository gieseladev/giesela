import json

import configparser


def encode_setting(value):
    handlers = ***REMOVED***
        "int": lambda v: str(v) + "\\i",
        "float": lambda v: str(v) + "\\f",
        "json": lambda v: json.dumps(v) + "\\json",
        "list": handlers["json"],
        "tuple": handlers["json"],
        "dict": handlers["json"]
    ***REMOVED***
    return handlers.get(type(value).__name__, lambda v: v)(value)


def decode_setting(value):

    if type(value).__name__ != "str":
        return value

    if value in ["True", "False", "None"]:
        return ***REMOVED***"True": True, "False": False, "None": None***REMOVED***[value]

    handlers = ***REMOVED***
        "i": lambda v: int(v),
        "f": lambda v: float(v),
        "json": lambda v: json.loads(v)
    ***REMOVED***
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
    skips_required = 4
    skip_ratio_required = 0.5
    save_videos = True
    now_playing_mentions = False
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
