import json
import re
from datetime import datetime, timedelta
from random import choice

import aiohttp
import requests
from bs4 import BeautifulSoup

from .config import ConfigDefaults
from .utils import parse_timestamp


class StationInfo:

    def __init__(self, id, name, aliases, language, cover, url, website):
        self.id = id
        self.name = name
        self._aliases = aliases
        self.aliases = [name, *aliases]
        self.language = language
        self.cover = cover
        self.url = url
        self.website = website
        self.has_current_song_info = RadioSongExtractor.has_data(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        data = ***REMOVED***
            "id":       self.id,
            "name":     self.name,
            "aliases":  self._aliases,
            "language": self.language,
            "cover":    self.cover,
            "website":  self.website,
            "url":      self.url
        ***REMOVED***
        return data


class RadioStations:
    _initialised = False
    stations = []

    def init():
        if not RadioStations._initialised:
            RadioStations.stations = [StationInfo.from_dict(
                station) for station in json.load(open(ConfigDefaults.radios_file, "r"))]
            _initialised = True

    def get_random_station(self):
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
            soup = BeautifulSoup(resp.text)
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
            resp = requests.get(
                "http://www.heart.co.uk/london/on-air/last-played-songs/")
            soup = BeautifulSoup(resp.text)
            title = soup.findAll("h3", ***REMOVED***"class": "track"***REMOVED***)[
                0].text.strip()
            artist = soup.findAll("p", ***REMOVED***"class": "artist"***REMOVED***)[
                0].text.strip()
            cover = soup.findAll("li", ***REMOVED***"class": "clearfix odd first"***REMOVED***)[
                0].findAll("img")[0]["src"]
            start_hour, start_minute = soup.findAll("p", ***REMOVED***"class": "dtstart"***REMOVED***)[
                0].text.strip().split(":")
            time_now = datetime.now()
            start_time = datetime(time_now.year, time_now.month, time_now.day, int(
                start_hour) + 1, int(start_minute))
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
            resp = requests.get(
                "http://www.radio32.ch/pages/rpc/rpc_panorama_programm_2015.cfm")
            cover_url, artist, song_name = re.search(
                r"<td class=\"cover\".+?background-image: url\((.+?)\).+\n.+\n<p class=\"next\">Zurzeit läuft<\/p>\n<p class=.+?>(.+?)<\/p>\n<p><p>(.+?)<\/p><\/p>", resp.text).groups((1, 2, 3))

            return ***REMOVED***
                "title": song_name,
                "artist": artist,
                "cover": "http://www.radio32.ch" + cover_url,
                "youtube": "http://www.radio32.ch/",
                "duration": 0,
                "progress": 0
            ***REMOVED***
        except:
            raise
            return None
