import json
import os
import re
import traceback
from os import path

import requests
from bs4 import BeautifulSoup

from musicbot.config import ConfigDefaults, static_config

lyrics_folder = path.join(os.getcwd(), static_config.lyrics_cache)
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

    file_path = path.join(lyrics_folder, escape_query(query))

    if path.isfile(file_path):
        print("[LYRICS] cached \"{}\"".format(query))

        lyrics = json.load(open(file_path, "r+"))

        if lyrics.get("version", 0) >= required_version:
            return lyrics
        else:
            print("[LYRICS] \"{}\" are outdated".format(query))
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

        print("[LYRICS] saved \"{}\"".format(query))
        return True


def search_for_lyrics(query):
    cached_lyrics = check_cache(query)

    if cached_lyrics:
        return cached_lyrics
    else:
        lyrics = search_for_lyrics_google(query)

        if lyrics:
            cache_lyrics(query, lyrics)

    return lyrics


def search_for_lyrics_google(query):
    params = {
        "key":  static_config.google_api_key,
        "cx":   "002017775112634544492:7y5bpl2sn78",
        "q":    query
    }
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
                print("Couldn't extract lyrics from {}:\n{}".format(
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

    lyrics_window = bs.find_all("div", {"class": "lyrics"})[0]
    lyrics = lyrics_window.text

    title = bs.find("h1", attrs={"class": "header_with_cover_art-primary_info-title"}).text.strip()

    return {
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    }


def _extract_lyrics_lyricsmode(url):
    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)
    lyrics_window = bs.find_all(
        "p", {"id": "lyrics_text", "class": "ui-annotatable"})[0]
    lyrics = lyrics_window.text

    title = bs.find("h1", attrs={"class": "song_name fs32"}).text.strip()

    return {
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    }


def _extract_lyrics_lyrical_nonsense(url):
    try:
        lyrics = None

        resp = requests.get(url)
        content = resp.text

        bs = BeautifulSoup(content, ConfigDefaults.html_parser)
        # take the Romaji version if there is one, otherwise use the default
        # one
        lyrics_window = bs.find_all("div", {"id": "Romaji"})[0] or bs.find_all("div", {"id": "Lyrics"})[0]
        lyrics = lyrics_window.text

        title = bs.select("div.titletext2new h3")[0].text.strip()

        return {
            "url": url,
            "title": title,
            "lyrics": lyrics.strip()
        }
    except IndexError:
        return None


def _extract_lyrics_musixmatch(url):
    lyrics = None

    headers = {"user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
    resp = requests.get(url, headers=headers)
    content = resp.text

    bs = BeautifulSoup(content, ConfigDefaults.html_parser)
    lyrics_window = bs.find_all(
        "div", {"class": "mxm-lyrics"})[0].find_all("div", {"class": "mxm-lyrics"})[0].span

    for garbage in bs.find_all("script"):
        garbage.clear()

    lyrics = lyrics_window.text

    title = bs.find("h1", attrs={"class": "mxm-track-title__track"}).contents[-2].strip()

    return {
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    }


def _extract_lyrics_azlyrics(url):
    headers = {"user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
    resp = requests.get(url, headers=headers)
    bs = BeautifulSoup(resp.text, ConfigDefaults.html_parser)

    center = bs.body.find("div", {"class": "col-xs-12 col-lg-8 text-center"})
    lyrics = center.find("div", {"class": None}).text

    lyrics = re.sub(r"<br>", " ", lyrics)
    lyrics = re.sub(r"<i?>\W*", "[", lyrics)
    lyrics = re.sub(r"\W*<\/i>", "]", lyrics)
    lyrics = re.sub(r"(?=)(\&quot\;)", "\"", lyrics)
    lyrics = re.sub(r"<\/div>", "", lyrics)

    title = center.find("h1").text.strip()[1:-8]

    return {
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    }


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
        match = re.search(r"-{10,}(.+?)-{10,}",
                          content, flags=re.DOTALL)
        if match:
            lyrics = match.group(1).strip()

    title = bs.find("td", attrs={"valign": "top"}).find("h1").text.strip()

    return {
        "url": url,
        "title": title,
        "lyrics": lyrics.strip()
    }


lyric_parsers = {
    "genius.com":                  _extract_lyrics_genius,
    "www.lyricsmode.com":          _extract_lyrics_lyricsmode,
    "www.lyrical-nonsense.com":    _extract_lyrics_lyrical_nonsense,
    "www.musixmatch.com":          _extract_lyrics_musixmatch,
    "www.azlyrics.com":            _extract_lyrics_azlyrics,
    "www.animelyrics.com":         _extract_lyrics_animelyrics
}

# print(search_for_lyrics("Snow Fairy - Fairy Tail - English Version - Amy B"))
# print(_extract_lyrics_animelyrics("https://www.animelyrics.com/anime/bakuon/feelalive.htm"))
