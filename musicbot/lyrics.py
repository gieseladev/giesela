import re
import traceback

import requests
from bs4 import BeautifulSoup


def search_for_lyrics(query):
    return search_for_lyrics_google(query)


def search_for_lyrics_google(query):
    params = {
        "key": "AIzaSyCvvKzdz-bVJUUyIzKMAYmHZ0FKVLGSJlo",
        "cx": "002017775112634544492:7y5bpl2sn78",
        "q": query
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
                return "{}\n**Lyrics from \"{}\"**".format(lyrics, display_link)
            else:
                print("[LYRICS] Couldn't parse these lyrics")

    return None


def search_for_lyrics_genius(query):
    params = {"q": query}
    resp = requests.get("https://genius.com/search", params=params)
    bs4 = BeautifulSoup(resp.text, "lxml")

    results = bs4.find_all(
        "ul", {"class": "search_results song_list primary_list"})[0]
    first_res = results.li

    return _extract_lyrics_genius(first_res.a["href"])


def _extract_lyrics_genius(url):
    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, "lxml")
    lyrics_window = bs.find_all("div", {"class": "lyrics"})[0]
    lyrics = lyrics_window.text
    return lyrics.strip()


def _extract_lyrics_lyricsmode(url):
    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, "lxml")
    lyrics_window = bs.find_all(
        "p", {"id": "lyrics_text", "class": "ui-annotatable"})[0]
    lyrics = lyrics_window.text
    return lyrics.strip()


def _extract_lyrics_lyrical_nonsense(url):
    try:
        lyrics = None

        resp = requests.get(url)
        content = resp.text

        bs = BeautifulSoup(content, "lxml")
        # take the Romaji version if there is one, otherwise use the default
        # one
        lyrics_window = bs.find_all("div", {"id": "Romaji"})[
            0] or bs.find_all("div", {"id": "Lyrics"})[0]
        lyrics = lyrics_window.text
        return lyrics.strip()
    except IndexError:
        return None


def _extract_lyrics_musixmatch(url):
    lyrics = None

    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
    resp = requests.get(url, headers=headers)
    content = resp.text

    bs = BeautifulSoup(content, "lxml")
    lyrics_window = bs.find_all(
        "div", {"class": "mxm-lyrics"})[0].find_all("div", {"class": "mxm-lyrics"})[0].span

    for garbage in bs.find_all("script"):
        garbage.clear()

    lyrics = lyrics_window.text
    return lyrics.strip()


def _extract_lyrics_animelyrics(url):
    resp = requests.get(url)
    content = resp.text

    lyrics = None

    bs = BeautifulSoup(content, "lxml")
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

    return lyrics


lyric_parsers = {"genius.com": _extract_lyrics_genius,
                 "www.lyricsmode.com": _extract_lyrics_lyricsmode,
                 "www.lyrical-nonsense.com": _extract_lyrics_lyrical_nonsense,
                 "www.animelyrics.com": _extract_lyrics_animelyrics,
                 "www.musixmatch.com": _extract_lyrics_musixmatch}

# print(search_for_lyrics("Snow Fairy - Fairy Tail - English Version - Amy B"))
