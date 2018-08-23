import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from itertools import chain
from random import choice

import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse

from .config import ConfigDefaults
from .lib.api import energy


class StationInfo:

    def __init__(self, id, name, aliases, language, cover, url, website, thumbnails, poll_time=None, uncertainty=2):
        self.id = id
        self.name = name
        self._aliases = aliases
        self.aliases = [name, *aliases]
        self.language = language
        self.cover = cover
        self.url = url
        self.website = website
        self.thumbnails = list(
            chain(*[RadioStations.thumbnails[pointer] if pointer in RadioStations.thumbnails else [pointer] for pointer in thumbnails]))

        self.has_current_song_info = RadioSongExtractor.has_data(self)
        self.poll_time = poll_time
        self.uncertainty = uncertainty

        self._current_thumbnail = None
        self._ct_timestamp = 0

    @property
    def thumbnail(self):
        if not self._current_thumbnail or time.time() > self._ct_timestamp:
            self._current_thumbnail = choice(self.thumbnails)
            self._ct_timestamp = time.time() + (self.poll_time or 20)

        return self._current_thumbnail

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        data = {
            "id": self.id,
            "name": self.name,
            "aliases": self._aliases,
            "language": self.language,
            "cover": self.cover,
            "website": self.website,
            "url": self.url,
            "poll_time": self.poll_time,
            "uncertainty": self.uncertainty,
            "thumbnails": self.thumbnails
        }
        return data

    def to_web_dict(self):
        return self.to_dict()


def get_all_stations():
    RadioStations.init()
    return RadioStations.stations


def get_random_station():
    RadioStations.init()
    station = choice(RadioStations.stations)
    return station


class RadioStations:
    _initialised = False
    stations = []
    thumbnails = {}

    @staticmethod
    def init():
        if not RadioStations._initialised:
            data = json.load(open(ConfigDefaults.radios_file, "r"))
            RadioStations.thumbnails = data["thumbnails"]
            RadioStations.stations = [StationInfo.from_dict(
                station) for station in data["stations"]]
            _initialised = True

    @staticmethod
    def get_station(query):
        RadioStations.init()
        for station in RadioStations.stations:
            if station.id == query or query in station.aliases:
                return station

        return None


def _get_current_song_bbc():
    resp = requests.get(
        "http://np.radioplayer.co.uk/qp/v3/onair?rpIds=340")
    data = json.loads(
        re.match(r"callback\((.+)\)", resp.text).group(1))
    song_data = data["results"]["340"][-1]
    start_time = datetime.fromtimestamp(
        int(song_data["startTime"]))
    stop_time = datetime.fromtimestamp(
        int(song_data["stopTime"]))
    duration = round((stop_time - start_time).total_seconds())
    progress = round(
        (datetime.now() - start_time).total_seconds())

    return {
        "title": song_data["name"],
        "artist": song_data["artistName"],
        "cover": song_data["imageUrl"],
        "youtube": "http://www.bbc.co.uk/radio",
        "duration": duration,
        "progress": progress
    }


def _get_current_song_capital_fm():
    resp = requests.get("http://www.capitalfm.com/digital/radio/last-played-songs/")
    soup = BeautifulSoup(resp.text, ConfigDefaults.html_parser)

    tz_info = timezone(timedelta(hours=1))

    time_on = soup.select(".last_played_songs .show.on_now .details .time")[0].contents[-1].strip()
    start, end = time_on.split("-", maxsplit=1)

    start_time = datetime.combine(date.today(), datetime.strptime(start.strip(), "%I%p").time(), tz_info)
    end_time = datetime.combine(date.today(), datetime.strptime(end.strip(), "%I%p").time(), tz_info)

    duration = (end_time - start_time).total_seconds()
    progress = (datetime.now(tz=tz_info) - start_time).total_seconds()

    title = soup.find("span", attrs={"class": "track", "itemprop": "name"}).text.strip()
    artist = soup.find("span", attrs={"class": "artist", "itemprop": "byArtist"}).text
    artist = re.sub(r"[\n\s]+", " ", artist).strip()
    cover = soup.select(".song_wrapper .img_wrapper img")[0]["data-src"]

    return {
        "title": title,
        "artist": artist,
        "cover": cover,
        "youtube": "http://www.capitalfm.com",
        "duration": duration,
        "progress": progress
    }


def _get_current_song_energy_bern():
    playouts = energy.get_playouts()

    now_playing = playouts[0]
    progress = (datetime.now(tz=timezone(timedelta(hours=0))) - parse(now_playing["created_at"])).total_seconds()

    title = "Unknown"
    artist = "Unknown"
    cover = None
    link = None
    duration = None

    if now_playing.get("type") == "music":
        song = now_playing["song"]

        title = song["title"]
        artist = song["artists_full"]
        cover = song["cover_url"]
        link = song["youtube_url"] or song["spotify_url"] or "https://energy.ch/play/bern"
        duration = song["duration"]

    elif now_playing.get("type") == "news":
        program = now_playing["program"]

        title = program["title"]
        artist = "Energy Bern"
        cover = program["cover_url"]
        link = "https://energy.ch/play/bern"

    if duration:
        progress = min(progress, duration)

    return {
        "title": title,
        "artist": artist,
        "cover": cover,
        "youtube": link,
        "duration": duration,
        "progress": progress
    }


def init_extractor():
    if not RadioSongExtractor._initialised:
        RadioSongExtractor.extractors = {
            "energybern": _get_current_song_energy_bern,
            "capitalfm": _get_current_song_capital_fm,
            "bbc": _get_current_song_bbc
        }
        RadioSongExtractor._initialised = True


class RadioSongExtractor:
    _initialised = False
    extractors = None

    @staticmethod
    def has_data(station_info):
        init_extractor()
        return station_info.id in RadioSongExtractor.extractors

    @staticmethod
    def get_current_song(station_info):
        init_extractor()
        extractor = RadioSongExtractor.extractors.get(station_info.id, None)

        if not extractor:
            return None
        else:
            return extractor()

    @staticmethod
    async def async_get_current_song(loop, station_info):
        return await loop.run_in_executor(None, RadioSongExtractor.get_current_song, station_info)
