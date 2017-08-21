import json
import os
import re
import traceback
from os import path

import requests
from bs4 import BeautifulSoup

from musicbot.config import ConfigDefaults, static_config

lyrics_folder = os.getcwd() + "\\" + static_config.lyrics_cache
lyrics_version = 3
required_version = 2


def ensure_cache_folder():
    if path.isdir(lyrics_folder):
        return True
    else:
        os.makedirs(lyrics_folder)
        return True


def escape_query(query):
    filename = re.sub(r"\s+", "_", query)
    filename = re.sub(r"\W+", "-", filename)

    return filename.lower().strip() + ".json"


def check_cache(query, load=True):
    ensure_cache_folder()

    file_path = lyrics_folder + "\\" + escape_query(query)

    if path.isfile(file_path):
        print("[LYRICS] cached \"***REMOVED******REMOVED***\"".format(query))

        lyrics = json.load(open(file_path, "r+"))

        if lyrics.get("version", 0) >= required_version:
            return lyrics
        else:
            print("[LYRICS] \"***REMOVED******REMOVED***\" are outdated".format(query))
            return None
    else:
        return None


def cache_lyrics(query, lyrics):
    ensure_cache_folder()

    if check_cache(query, load=False):
        return False
    else:
        file_path = lyrics_folder + "\\" + escape_query(query)

        lyrics["version"] = lyrics_version

        json.dump(lyrics, open(file_path, "w+"), indent=4)

        print("[LYRICS] saved \"***REMOVED******REMOVED***\"".format(query))
        return True


def search_for_lyrics(query):
    cached_lyrics = check_cache(query)

    if cached_lyrics:
        return cached_lyrics
    else:
        lyrics = search_for_lyrics_google(query)
        cache_lyrics(query, lyrics)

    return lyrics


def search_for_lyrics_google(query):
    params = ***REMOVED***
        "key":  static_config.google_api_key,
        "cx":   "002017775112634544492:7y5bpl2sn78",
        "q":    query
    ***REMOVED***
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1", params=params)
    data = resp.json()
    items = data.get("items", [])

    for item in items:
        display_link = item["displayLink"]
        if display_link in lyric_parsers:
            print("[LYRICS] Found lyrics at " + display_link)
            lyrics = None
            try:
                lyrics = lyric_parsers[display_link](item["link"])
            except BaseException:
                print("Couldn't extract lyrics from ***REMOVED******REMOVED***:\n***REMOVED******REMOVED***".format(
                    display_link, traceback.format_exc()))
            if lyrics:
                lyrics["source"] = display_link
                return lyrics
            else:
                print("[LYRICS] Couldn't parse these lyrics")

    return None


def _extract_lyrics_genius(url):
    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)

    lyrics_window = bs.find_all("div", ***REMOVED***"class": "lyrics"***REMOVED***)[0]
    lyrics = lyrics_window.text

    title = bs.find("h1", attrs=***REMOVED***"class": "header_with_cover_art-primary_info-title"***REMOVED***).text.strip()

    return ***REMOVED***
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    ***REMOVED***


def _extract_lyrics_lyricsmode(url):
    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)
    lyrics_window = bs.find_all(
        "p", ***REMOVED***"id": "lyrics_text", "class": "ui-annotatable"***REMOVED***)[0]
    lyrics = lyrics_window.text

    title = bs.find("h1", attrs=***REMOVED***"class": "song_name fs32"***REMOVED***).text.strip()

    return ***REMOVED***
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    ***REMOVED***


def _extract_lyrics_lyrical_nonsense(url):
    try:
        lyrics = None

        resp = requests.get(url)
        content = resp.text

        bs = BeautifulSoup(content, ConfigDefaults.html_parser)
        # take the Romaji version if there is one, otherwise use the default
        # one
        lyrics_window = bs.find_all("div", ***REMOVED***"id": "Romaji"***REMOVED***)[0] or bs.find_all("div", ***REMOVED***"id": "Lyrics"***REMOVED***)[0]
        lyrics = lyrics_window.text

        title = bs.select("div.titletext2new h3")[0].text.strip()

        return ***REMOVED***
            "url": url,
            "title": title,
            "lyrics": lyrics.strip()
        ***REMOVED***
    except IndexError:
        return None


def _extract_lyrics_musixmatch(url):
    lyrics = None

    headers = ***REMOVED***"user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"***REMOVED***
    resp = requests.get(url, headers=headers)
    content = resp.text

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)
    lyrics_window = bs.find_all(
        "div", ***REMOVED***"class": "mxm-lyrics"***REMOVED***)[0].find_all("div", ***REMOVED***"class": "mxm-lyrics"***REMOVED***)[0].span

    for garbage in bs.find_all("script"):
        garbage.clear()

    lyrics = lyrics_window.text

    title = bs.find("h1", attrs=***REMOVED***"class": "mxm-track-title__track"***REMOVED***).contents[-2].strip()

    return ***REMOVED***
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    ***REMOVED***


def _extract_lyrics_azlyrics(url):
    headers = ***REMOVED***"user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"***REMOVED***
    resp = requests.get(url, headers=headers)
    bs = BeautifulSoup(resp.text, ConfigDefaults.html_parser)

    center = bs.body.find("div", ***REMOVED***"class": "col-xs-12 col-lg-8 text-center"***REMOVED***)
    lyrics = center.find("div", ***REMOVED***"class": None***REMOVED***).text

    lyrics = re.sub(r"<br>", " ", lyrics)
    lyrics = re.sub(r"<i?>\W*", "[", lyrics)
    lyrics = re.sub(r"\W*<\/i>", "]", lyrics)
    lyrics = re.sub(r"(?=)(\&quot\;)", "\"", lyrics)
    lyrics = re.sub(r"<\/div>", "", lyrics)

    title = center.find("h1").text.strip()[1:-8]

    return ***REMOVED***
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    ***REMOVED***


def _extract_lyrics_animelyrics(url):
    resp = requests.get(url)
    content = resp.text

    lyrics = None

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)
    main_body = bs.find_all("table")[0]
    lyrics_window = main_body.find_all("table")

    if lyrics_window:  # shit's been translated
        lyrics_window = lyrics_window[0]

        lines = lyrics_window.find_all("tr")
        lyrics = ""
        for line in lines:
            p = line.td
            if p:
                p.span.dt.replace_with("")
                for br in p.span.find_all("br"):
                    br.replace_with("\n")

                lyrics += p.span.text
        lyrics = lyrics.strip()
    else:
        raw = requests.get(re.sub(r"\.html?", ".txt", url),
                           allow_redirects=False)
        content = raw.text.strip()
        match = re.search(r"-***REMOVED***10,***REMOVED***(.+?)-***REMOVED***10,***REMOVED***",
                          content, flags=re.DOTALL)
        if match:
            lyrics = match.group(1).strip()

    title = bs.find("td", attrs=***REMOVED***"valign": "top"***REMOVED***).find("h1").text.strip()

    return ***REMOVED***
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    ***REMOVED***


lyric_parsers = ***REMOVED***
    "genius.com":                  _extract_lyrics_genius,
    "www.lyricsmode.com":          _extract_lyrics_lyricsmode,
    "www.lyrical-nonsense.com":    _extract_lyrics_lyrical_nonsense,
    "www.musixmatch.com":          _extract_lyrics_musixmatch,
    "www.azlyrics.com":            _extract_lyrics_azlyrics,
    "www.animelyrics.com":         _extract_lyrics_animelyrics
***REMOVED***

# print(search_for_lyrics("Snow Fairy - Fairy Tail - English Version - Amy B"))
# print(_extract_lyrics_animelyrics("https://www.animelyrics.com/anime/bakuon/feelalive.htm"))
