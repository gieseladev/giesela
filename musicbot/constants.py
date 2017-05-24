import os.path
import re

import requests

MAIN_VERSION = '2.8.9'
SUB_VERSION = 'Giesela-PLUS'
VERSION = MAIN_VERSION + "_" + SUB_VERSION

AUDIO_CACHE_PATH = os.path.join(os.getcwd(), 'audio_cache')
DISCORD_MSG_CHAR_LIMIT = 2000


def DEV_VERSION():
    page = requests.get(
        "https://raw.githubusercontent.com/siku2/MusicBot/dev/musicbot/constants.py")
    matches = re.search(
        r"MAIN_VERSION = '(\d.\d.\d)'\nSUB_VERSION = '(.+?)'", page.content.decode("utf-8"))

    if matches is None:
        return matches

    return "_".join(matches.groups((1, 2)))
