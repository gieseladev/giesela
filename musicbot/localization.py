"""
use some kind of dot notation
> "player.now_playing.generic"
should map to the generic string in the now_playing dict within the player.json file
"""

import json
import os
from os import path

LOCALE_FOLDER = "locale"


language = ""
language_data = ***REMOVED******REMOVED***


def unravel_id(string_id):
    return [s.lower() for s in string_id.split(".")]


def traverse(dictionary, directions):
    current_frame = dictionary
    for loc in directions:
        current_frame = current_frame[loc]

    return current_frame


def load_language(lang):
    loc = path.join(LOCALE_FOLDER, lang)

    lan_data = ***REMOVED******REMOVED***

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
        raise ValueError("This language doesn't exist")

    return lan_data


def set_language(lang):
    global language, language_data

    language = lang
    language_data = load_language(lang)


def get(string_id):
    location = unravel_id(string_id)

    return traverse(language_data, location)


if __name__ == "__main__":
    set_language("en")
    print(language)
    print(language_data)
