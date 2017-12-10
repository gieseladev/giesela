"""Giesela speaks languages."""

import json
import logging
import os
from os import path

import discord

from giesela import constants

log = logging.getLogger(__name__)

LOCALE_FOLDER = constants.FileLocations.LOCALE_FOLDER
FALLBACK_LANGUAGE = "_default"

locales = {}


class Settings:
    """Makes it possible to change the language per server."""

    client_language = FALLBACK_LANGUAGE
    languages = {}

    @classmethod
    def load(cls):
        """Load settings."""
        log.debug("Loading language settings!")

        try:
            with open(constants.FileLocations.LOCALISATION, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            log.warn("Couldn't parse language config.")
            return

        cls.client_language = data.get("client", FALLBACK_LANGUAGE)
        cls.languages = data.get("languages", {})
        log.debug("Loaded language settings")

    @classmethod
    def save(cls):
        """Save current settings to disk."""
        data = {
            "client": cls.client_language,
            "languages": cls.languages
        }
        with open(constants.FileLocations.LOCALISATION, "r") as f:
            json.dump(data, f)

        log.debug("saved language settings")

    @classmethod
    def set_client_language(cls, lang):
        """Set the language used by Giesela."""
        assert has_language(lang), "Can't set the language to {}, this language doesn't exist".format(lang)

        cls.client_language = lang
        cls.save()

    @classmethod
    def set_language(cls, obj, lang):
        """Set the language used for obj."""
        assert has_language(lang), "Can't set the language to {}, this language doesn't exist".format(lang)

        _id = obj

        if isinstance(obj, (discord.Server, discord.User)):
            _id = obj.id

        assert isinstance(_id, (str, int)), "Can't set the language for an object of type {}.".format(type(_id))

        cls.languages[_id] = lang
        cls.save()

    @classmethod
    def get_language(cls, lans):
        """Return the best language for lans."""
        if not lans:
            return cls.client_language

        if not isinstance(lans, (tuple, list)):
            lans = [lans]

        for lan in lans:
            if isinstance(lan, str) and has_language(lan):
                return lan.lower()

            _id = lan

            if isinstance(lan, (discord.User, discord.Server)):
                _id = lan.id

            res = cls.languages.get(_id)

            if res:
                return res

        return cls.client_language


Settings.load()


def unravel_id(string_id):
    """Unpack the id to a list."""
    return [s.lower() for s in string_id.split(".")]


def traverse(dictionary, directions):
    """Make your way through a dictionary by following the directions."""
    current_frame = dictionary
    for ind, loc in enumerate(directions):
        try:
            current_frame = current_frame[loc]
        except KeyError:
            ref = ".".join(directions[:ind])
            raise KeyError("{} doesn't exist in {}".format(loc, ref))

    return current_frame


def has_language(lang):
    """Find out whether Giesela speaks this language."""
    loc = path.join(LOCALE_FOLDER, lang)

    return path.isdir(loc)


def load_language(lang):
    """Load this language."""
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

    log.info("Loaded language {}".format(lang))
    return lan_data


class Locale:
    """A nice wrapper for a language."""

    def __init__(self, lang):
        """Initialise."""
        self.language = lang
        self.data = load_language(lang)

    def __getitem__(self, key):
        """Return string from key."""
        return self.get(key)

    def __str__(self):
        """Maek buutiful."""
        return "<Locale {}>".format(self.language)

    def get(self, string_id):
        """Get string from key."""
        location = unravel_id(string_id)

        return traverse(self.data, location)

    def format(self, string_id, *args, **kwargs):
        """Shorthand for get + str.format."""
        string = self.get(string_id)

        assert isinstance(string, str), "\"{}\" isn't explicit!".format(string_id)

        return string.format(*args, **kwargs)


_fallback = Locale(FALLBACK_LANGUAGE)


def get_locale(lang, use_fallback=True):
    """Get a locale object either by the language's name or a server."""
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
    """Shorthand for get_locale + get."""
    return get_locale(lang).get(string_id)


def format(lang, string_id, *args, **kwargs):
    """Shorthand for get_locale + get + str.format."""
    return get_locale(lang).format(string_id, *args, **kwargs)
