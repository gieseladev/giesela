import os.path
import re

import requests
from bs4 import BeautifulSoup

MAIN_VERSION = "3.7.0"
SUB_VERSION = "Weebiesela"
VERSION = MAIN_VERSION + "_" + SUB_VERSION

past_sub_versions = ***REMOVED***
    "3.7.0": "Giese_La_La_Land",
    "3.6.0": "Weebiesela",
    "3.5.0": "Veggiesela",
    "3.4.0": "Gunzulalela",
    "3.3.0": "Giselator",
    "3.2.0": "GG_iesela",
    "3.1.0": "age_of_Giesela",
    "3.0.0": "Giesela-PLUS"***REMOVED***

AUDIO_CACHE_PATH = os.path.join(os.getcwd(), "audio_cache")
DISCORD_MSG_CHAR_LIMIT = 2000


def get_dev_version():
    page = requests.get(
        "https://raw.githubusercontent.com/siku2/Giesela/dev/musicbot/constants.py"
    )
    matches = re.search(
        r"MAIN_VERSION = \"(\d.\d.\d)\"\nSUB_VERSION = \"(.*?)\"",
        page.content.decode("utf-8"))

    if matches is None:
        return matches

    return matches.groups((1, 2))


def get_master_version():
    page = requests.get(
        "https://raw.githubusercontent.com/siku2/Giesela/master/musicbot/constants.py"
    )
    matches = re.search(
        r"MAIN_VERSION = \"(\d.\d.\d)\"\nSUB_VERSION = \"(.*?)\"",
        page.content.decode("utf-8"))

    if matches is None:
        return matches

    return matches.groups((1, 2))


def get_dev_changelog():
    base_url = "https://siku2.github.io/Giesela/changelogs/changelog-"
    dev_version = re.sub(r"\D", "", get_dev_version()[0])

    changelog_page = requests.get(
        base_url + dev_version).content.decode("utf-8")
    bs = BeautifulSoup(changelog_page, "lxml")
    html_to_markdown = [(r"<\/?li>", "\t"), (r"<\/?ul>", ""), (r"<code.+?>(.+?)<\/code>", r"`\1`"), (r"<strong>(.+?)<\/strong>",
                                                                                                     r"**\1**"), (r"<a\shref=\"(.+?)\">(.+?)<\/a>", r"[`\2`](\1)"), (r"\n\W+\n", "\n")]

    changes = []

    for sib in (bs.body.li, *bs.body.li.next_siblings):
        line = str(sib).strip()
        for match, repl in html_to_markdown:
            line = re.sub(match, repl, line)

        line = line.strip()
        if line:
            changes.append(line)

    return changes
