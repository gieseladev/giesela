"""
use some kind of dot notation
> "player.now_playing.generic"
should map to the generic string in the now_playing dict within the player.json file

Client - Server - User
"""

import json
import os
from os import path

import discord

from giesela.config import static_config

LOCALE_FOLDER = "locale"
FALLBACK_LANGUAGE = "_default"

locales = {}


class Settings:
    @staticmethod
    def search_id(_id):
        return static_config.user_languages.get(_id) or static_config.guild_languages.get(_id)

    @staticmethod
    def set_language(obj, lang):
        assert has_language(lang), "Can't set the language to {}, this language doesn't exist".format(lang)

        if isinstance(obj, discord.Guild):
            static_config.guild_languages[obj.id] = lang
        elif isinstance(obj, discord.User):
            static_config.user_languages[obj.id] = lang

    @staticmethod
    def get_language(lans):

        if not isinstance(lans, (tuple, list)):
            lans = [lans]

        for lan in lans:
            if isinstance(lan, str) and has_language(lan):
                return lan.lower()

            _id = lan

            if isinstance(lan, (discord.User, discord.Guild)):
                _id = lan.id

            res = Settings.search_id(_id)

            if res:
                return res

        return static_config.client_language


def unravel_id(string_id):
    return [s.lower() for s in string_id.split(".")]


def traverse(dictionary, directions):
    current_frame = dictionary
    for ind, loc in enumerate(directions):
        try:
            current_frame = current_frame[loc]
        except KeyError:
            ref = ".".join(directions[:ind])
            raise KeyError("{} doesn't exist in {}".format(loc, ref))

    return current_frame


def has_language(lang):
    loc = path.join(LOCALE_FOLDER, lang)

    return path.isdir(loc)


def load_language(lang):
    loc = path.join(LOCALE_FOLDER, lang)

    lan_data = {}

    if path.isdir(loc):
        files = os.listdir(loc)

        for f in files:
            file_loc = path.join(loc, f)

            if not path.isfile(file_loc):
                continue

            file_key = path.splitext(f)[0]

            with open(file_loc, "r") as lan_file:
                data = json.load(lan_file)

            lan_data[file_key] = data
    else:
        raise ValueError("Language {} doesn't exist".format(lang))

    return lan_data


class Locale:
    def __init__(self, lang):
        self.language = lang
        self.data = load_language(lang)

    def __getitem__(self, key):
        return self.get(key)

    def __str__(self):
        return "Locale {}".format(self.language)

    def get(self, string_id):
        location = unravel_id(string_id)

        return traverse(self.data, location)

    def format(self, string_id, *args, **kwargs):
        string = self.get(string_id)

        assert isinstance(string, str), "\"{}\" isn't explicit!".format(string_id)

        return string.format(*args, **kwargs)


_fallback = Locale(FALLBACK_LANGUAGE)


def get_locale(lang, use_fallback=True):
    global locales

    lang = Settings.get_language(lang)

    if lang not in locales:
        if has_language(lang):
            locales[lang] = Locale(lang)
        else:
            if use_fallback:
                return _fallback

            raise KeyError("Language {} doesn't exist".format(lang))

    return locales[lang]


def get(lang, string_id):
    return get_locale(lang).get(string_id)


def format(lang, string_id, *args, **kwargs):
    return get_locale(lang).format(string_id, *args, **kwargs)

# if __name__ == "__main__":
#     print(format("de-de", "player.now_playing.generic", title="test"))
