import json
import re
import time
from datetime import datetime, timedelta, timezone
from itertools import chain
from random import choice

import aiohttp
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse

from .config import ConfigDefaults
from .utils import parse_timestamp


class StationInfo:

    def __init__(self, id, name, aliases, language, cover, url, website, thumbnails):
        self.id = id
        self.name = name
        self._aliases = aliases
        self.aliases = [name, *aliases]
        self.language = language
        self.cover = cover
        self.url = url
        self.website = website
        self.thumbnails = list(chain(*[RadioStations.thumbnails[pointer] if pointer in RadioStations.thumbnails else [
            pointer, ] for pointer in thumbnails]))
        self.has_current_song_info = RadioSongExtractor.has_data(self)

    @property
    def thumbnail(self):
        return choice(self.thumbnails)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        data = ***REMOVED***
            "id":           self.id,
            "name":         self.name,
            "aliases":      self._aliases,
            "language":     self.language,
            "cover":        self.cover,
            "website":      self.website,
            "url":          self.url,
            "thumbnails":   self.thumbnails
        ***REMOVED***
        return data


class RadioStations:
    _initialised = False
    stations = []
    thumbnails = ***REMOVED******REMOVED***

    def init():
        if not RadioStations._initialised:
            data = json.load(open(ConfigDefaults.radios_file, "r"))
            RadioStations.thumbnails = data["thumbnails"]
            RadioStations.stations = [StationInfo.from_dict(
                station) for station in data["stations"]]
            _initialised = True

    def get_random_station():
        RadioStations.init()
        station = choice(RadioStations.stations)
        return station

    def get_station(query):
        RadioStations.init()
        for station in RadioStations.stations:
            if station.id == query or query in station.aliases:
                return station

        return None

    def get_all_stations():
        RadioStations.init()
        return RadioStations.stations


class RadioSongExtractor:
    _initialised = False
    extractors = None

    def init():
        if not RadioSongExtractor._initialised:
            RadioSongExtractor.extractors = ***REMOVED***
                "energybern":   RadioSongExtractor._get_current_song_energy_bern,
                "capitalfm":    RadioSongExtractor._get_current_song_capital_fm,
                "bbc":          RadioSongExtractor._get_current_song_bbc,
                "heartlondon":  RadioSongExtractor._get_current_song_heart_london,
                "radio32":      RadioSongExtractor._get_current_song_radio32
            ***REMOVED***
            RadioSongExtractor._initialised = True

    def has_data(station_info):
        RadioSongExtractor.init()
        return station_info.id in RadioSongExtractor.extractors

    def get_current_song(station_info):
        RadioSongExtractor.init()
        extractor = RadioSongExtractor.extractors.get(station_info.id, None)

        if not extractor:
            return None
        else:
            return extractor()

    def _get_current_song_energy_bern():
        try:
            resp = requests.get(
                "http://www.energyzueri.com/legacy-feed-converter/files/json/timeline/timeline_energybern_0.json")
            queue = resp.json()
            entry = queue[0]
            start_time = datetime.fromtimestamp(
                int(entry["timestamp"]))
            progress = round(
                (datetime.now() - start_time).total_seconds())
            duration = parse_timestamp(entry["duration"])

            return ***REMOVED***
                "title": entry["title"].strip(),
                "artist": entry["artist"].strip(),
                "cover": entry["cover"],
                "youtube": entry["youtube"],
                "duration": duration,
                "progress": progress
            ***REMOVED***
        except:
            raise
            return None

    def _get_current_song_capital_fm():
        try:
            resp = requests.get(
                "http://www.capitalfm.com/dynamic/now-playing-card/digital/")
            soup = BeautifulSoup(resp.text, ConfigDefaults.html_parser)
            title = " ".join(soup.find_all(
                "div",
                attrs=***REMOVED***"itemprop": "name", "class": "track"***REMOVED***
            )[0].text.strip().split())
            artist = " ".join(soup.find_all("div",
                                            attrs=***REMOVED***"itemprop": "byArtist", "class": "artist"***REMOVED***)[
                0].text.strip().split())
            cover = soup.find_all("img", itemprop="image")[
                0]["data-src"]

            return ***REMOVED***
                "title": title,
                "artist": artist,
                "cover": cover,
                "youtube": "http://www.capitalfm.com",
                "duration": 0,
                "progress": 0
            ***REMOVED***
        except:
            raise
            return None

    def _get_current_song_bbc():
        try:
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

            return ***REMOVED***
                "title": song_data["name"],
                "artist": song_data["artistName"],
                "cover": song_data["imageUrl"],
                "youtube": "http://www.bbc.co.uk/radio",
                "duration": duration,
                "progress": progress
            ***REMOVED***
        except:
            raise
            return None

    def _get_current_song_heart_london():
        try:
            resp = requests.get("http://www.heart.co.uk/london/on-air/last-played-songs/")
            soup = BeautifulSoup(resp.text, ConfigDefaults.html_parser)

            title = soup.findAll("h3", ***REMOVED***"class": "track"***REMOVED***)[0].text.strip()
            artist = soup.findAll("p", ***REMOVED***"class": "artist"***REMOVED***)[0].text.strip()
            cover = soup.findAll("li", ***REMOVED***"class": "clearfix odd first"***REMOVED***)[0].findAll("img")[0]["src"]
            start_hour, start_minute = soup.findAll("p", ***REMOVED***"class": "dtstart"***REMOVED***)[0].text.strip().split(":")
            start_hour = (int(start_hour) + 1) % 24

            time_now = datetime.now()

            start_time = datetime(time_now.year, time_now.month, time_now.day, start_hour, int(start_minute))
            progress = round((time_now - start_time).total_seconds())

            return ***REMOVED***
                "title": title,
                "artist": artist,
                "cover": cover,
                "youtube": "http://www.heart.co.uk/london/on-air/last-played-songs/",
                "duration": 0,
                "progress": progress
            ***REMOVED***
        except:
            raise
            return None

    def _get_current_song_radio32():
        try:
            resp = requests.get("http://player.radio32.ch/data/generated_content/radio32/production/playlist/playlist_onair.json")
            data = resp.json()
            now_playing = data["live"][0]

            start_time = parse(now_playing["playtime"]).timestamp()
            duration = parse_timestamp(now_playing["duration"])

            end_time = start_time + duration

            if time.time() >= end_time:
                print("[RADIO] <radio 32> \"live\" is outdated, switching to coming[0]")
                start_time += duration

                now_playing = data["coming"][0]
                duration = parse_timestamp(now_playing["duration"])

            return ***REMOVED***
                "title": now_playing["title"],
                "artist": now_playing["interpret"].replace(",", " & "),
                "cover": now_playing["imageFullURL"],
                "youtube": "http://www.radio32.ch/",
                "duration": duration,
                "progress": time.time() - start_time
            ***REMOVED***
        except:
            raise
            return None
