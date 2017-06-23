import re

import requests
from bs4 import BeautifulSoup


def search_for_lyrics(query):
    params = {
        "key": "AIzaSyCvvKzdz-bVJUUyIzKMAYmHZ0FKVLGSJlo",
        "cx": "002017775112634544492:7y5bpl2sn78",
        "q": query}
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1", params=params)
    data = resp.json()
    items = data.get("items", [])

    for item in items:
        display_link = item["displayLink"]
        if display_link in lyric_parsers:
            return lyric_parsers[display_link](item["link"])

    return None


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
    lyrics = None

    resp = requests.get(url)
    content = resp.text

    bs = BeautifulSoup(content, "lxml")
    lyrics_window = bs.find_all(
        "div", {"id": "Lyrics"})[1]
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
                 "www.animelyrics.com": _extract_lyrics_animelyrics}
