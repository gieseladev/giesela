import os
import rapidjson
import re
from os import path
from pathlib import Path
from typing import Optional

import lyricsfinder
from lyricsfinder import Lyrics

from .config import static_config

lyrics_folder = path.join(os.getcwd(), static_config.lyrics_cache)

Path(lyrics_folder).mkdir(parents=True, exist_ok=True)


def ensure_cache_folder():
    if path.isdir(lyrics_folder):
        return True
    else:
        os.makedirs(lyrics_folder)
        return True


def escape_query(query: str) -> str:
    filename = re.sub(r"\s+", "_", query)
    filename = re.sub(r"\W+", "-", filename)

    return filename.lower().strip() + ".json"


def check_cache(query: str, load: bool = True) -> Optional[Lyrics]:
    ensure_cache_folder()

    file_path = path.join(lyrics_folder, escape_query(query))

    if path.isfile(file_path):
        print("[LYRICS] cached \"{}\"".format(query))

        if load:
            with open(file_path, "r+") as fp:
                lyrics = Lyrics.from_dict(rapidjson.load(fp))
            return lyrics
    return None


def cache_lyrics(query: str, lyrics: Lyrics) -> bool:
    ensure_cache_folder()

    if check_cache(query, load=False):
        return False
    else:
        file_path = path.join(lyrics_folder, escape_query(query))

        with open(file_path, "w+") as fp:
            lyrics.save(fp)

        print("[LYRICS] saved \"{}\"".format(query))
        return True


def search_for_lyrics(query: str) -> Lyrics:
    cached_lyrics = check_cache(query)

    if cached_lyrics:
        return cached_lyrics

    lyrics = next(lyricsfinder.search_lyrics(query, google_api_key=static_config.google_api_key), None)

    if lyrics:
        cache_lyrics(query, lyrics)

    return lyrics
