import logging
import time
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple, Union

import yaml
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from bs4.element import Tag

from . import utils
from .bot import Giesela

log = logging.getLogger(__name__)


class Resolver:
    selector: str
    attribute: Optional[str]

    def __init__(self, selector: str, attribute: str = None):
        self.selector = selector
        self.attribute = attribute

    @classmethod
    def from_config(cls, config: Union[str, Dict[str, Any]]) -> "Resolver":
        if isinstance(config, str):
            selector = config
            attribute = None
        else:
            selector = config.pop("selector")
            attribute = config.pop("attribute", None)
        return cls(selector, attribute)

    def process_value(self, value: str) -> str:
        return " ".join(value.split()).strip()

    def resolve_one(self, bs: Tag) -> str:
        target = bs.select_one(self.selector)

        if self.attribute:
            value = target[self.attribute]
            if value and isinstance(value, list):
                value = " ".join(value)
            value = str(value)
        else:
            value = str(target.text)

        return self.process_value(value)


class Scraper:
    url: str
    targets: Dict[str, Resolver]

    def __init__(self, url: str, targets: Dict[str, Resolver]):
        self.url = url
        self.targets = targets

    @property
    def keys(self) -> List[str]:
        return list(self.targets.keys())

    @classmethod
    def from_config(cls, config: Dict[str, Union[str, Dict[str, Any]]]) -> "Scraper":
        url = config.pop("url")
        targets = {key: Resolver.from_config(value) for key, value in config.items()}
        return cls(url, targets)

    def absolute_url(self, url: str, *, https: bool = True) -> str:
        if url.startswith("//"):
            pre = "https" if https else "http"
            return f"{pre}:{url}"
        elif url.startswith("/") or not url.startswith(("http://", "https://")):
            base_url = self.url.rstrip("/")
            url = url.lstrip("/")
            return f"{base_url}/{url}"
        return url

    async def get_soup(self, session: ClientSession) -> BeautifulSoup:
        async with session.get(self.url) as resp:
            text = await resp.text()
        return BeautifulSoup(text, "lxml")

    async def scrape(self, session: ClientSession, *, silent: bool = True) -> Dict[str, Any]:
        bs = await self.get_soup(session)
        data = {}
        for key, resolver in self.targets.items():
            try:
                value = resolver.resolve_one(bs)
            except Exception:
                if not silent:
                    raise
                log.exception(f"Couldn't fetch {key} with {resolver}")
                value = None

            data[key] = value

        return data


RADIO_SONG_DATA_URL_FIELDS = ("artist_image", "cover")
RADIO_SONG_DATA_FIELDS = ("song_title", "artist", "album", "progress", "duration") + RADIO_SONG_DATA_URL_FIELDS
SONG_SCRAPER_FIELDS = ("url", "remaining_duration") + RADIO_SONG_DATA_FIELDS


class RadioSongData(NamedTuple):
    timestamp: float

    song_title: str = None
    artist: str = None
    artist_image: str = None
    album: str = None
    cover: str = None
    progress: float = None
    duration: float = None

    def __str__(self) -> str:
        origin = self.artist or self.album
        if self.song_title:
            if origin:
                return f"{origin} - {self.song_title}"
            return self.song_title
        return origin or "Unknown Song"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._asdict())


class RadioStation:
    manager: "RadioStationManager"

    name: str
    aliases: List[str]
    stream: str
    website: Optional[str]
    logo: Optional[str]

    song_scraper: Optional[Scraper]
    update_interval: int
    extra_update_delay: int

    def __init__(self, **kwargs):
        self.name = kwargs.pop("name")
        self.aliases = kwargs.pop("aliases", [])
        self.stream = kwargs.pop("stream")
        self.website = kwargs.pop("website", None)
        self.logo = kwargs.pop("logo", None)

        self.song_scraper = kwargs.pop("song_scraper", None)
        self.update_interval = kwargs.pop("update_interval", 40)
        self.extra_update_delay = kwargs.pop("extra_update_delay", 0.5)

    def __str__(self) -> str:
        return f"Radio {self.name}"

    @property
    def has_song_data(self) -> bool:
        return bool(self.song_scraper)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RadioStation":
        song_scraper_config = config.pop("current_song", None)
        if song_scraper_config:
            song_scraper = Scraper.from_config({key: value for key, value in song_scraper_config.items() if key in SONG_SCRAPER_FIELDS})
            config["song_scraper"] = song_scraper
        return cls(**config)

    def to_dict(self) -> Dict[str, Any]:
        return dict(name=self.name, aliases=self.aliases, website=self.website, logo=self.logo)

    def is_alias(self, name: str) -> bool:
        return name.lower() == self.name.lower() or name in self.aliases

    def handle_remaining_duration(self, song_id: str, remaining: int) -> Tuple[int, int]:
        prev_id, duration = getattr(self, "_remaining_duration_data", (None, None))
        if prev_id == song_id and duration >= remaining:
            progress = duration - remaining
        else:
            progress = 0
            duration = remaining
            setattr(self, "_remaining_duration_data", (song_id, duration))
        return progress, duration

    def fix_url_fields(self, data: Dict[str, Any]):
        for field in RADIO_SONG_DATA_URL_FIELDS:
            if field in data:
                value = data[field]
                data[field] = self.song_scraper.absolute_url(value)

    async def get_song_data(self) -> Optional[RadioSongData]:
        if not self.song_scraper:
            return None
        data = await self.song_scraper.scrape(self.manager.aiosession)

        kwargs = {key: value for key, value in data.items() if key in RADIO_SONG_DATA_FIELDS and value is not None}

        if "remaining_duration" in data:
            remaining = utils.parse_timestamp(data["remaining_duration"])
            song_id = "".join(filter(None, map(kwargs.get, ("song_title", "artist", "album"))))
            if song_id:
                progress, duration = self.handle_remaining_duration(song_id, remaining)
                kwargs.update(progress=progress, duration=duration)
        else:
            if "duration" in kwargs:
                kwargs["duration"] = utils.parse_timestamp(data["duration"])
            if "progress" in kwargs:
                kwargs["progress"] = utils.parse_timestamp(data["progress"])

        self.fix_url_fields(kwargs)

        return RadioSongData(time.time(), **kwargs)


class RadioStationManager:
    bot: Giesela
    stations: List[RadioStation]

    aiosession: ClientSession

    def __init__(self, bot: Giesela, stations: List[RadioStation] = None):
        self.bot = bot
        self.stations = stations or []

        self.aiosession = getattr(bot, "aiosession", None) or ClientSession()

    def __iter__(self) -> Iterator[RadioStation]:
        return iter(self.stations)

    @classmethod
    def load(cls, bot: Giesela, fp: Union[str, List[Dict[str, Any]]]) -> "RadioStationManager":
        if isinstance(fp, str):
            with open(fp, "r") as f:
                stations = yaml.safe_load(f)
        else:
            stations = fp

        inst = cls(bot)

        for station_data in stations:
            station = RadioStation.from_config(station_data)
            inst.add_station(station)

        return inst

    def add_station(self, station: RadioStation):
        station.manager = self
        self.stations.append(station)

    def find_station(self, query: str) -> Optional[RadioStation]:
        for station in self:
            if station.is_alias(query):
                return station
