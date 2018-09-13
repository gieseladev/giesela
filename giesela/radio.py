import logging
import time
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple, Union

import yaml
from aiohttp import ClientSession

from . import utils
from .bot import Giesela
from .utils import Scraper

log = logging.getLogger(__name__)

RADIO_SONG_DATA_URL_FIELDS = ("artist_image", "cover")
RADIO_SONG_DATA_FIELDS = ("title", "artist", "album", "progress", "duration") + RADIO_SONG_DATA_URL_FIELDS
SONG_SCRAPER_FIELDS = ("url", "remaining_duration") + RADIO_SONG_DATA_FIELDS


class RadioSongData(NamedTuple):
    timestamp: float

    title: str
    artist: str = None
    artist_image: str = None
    album: str = None
    cover: str = None
    progress: float = None
    duration: float = None

    def __str__(self) -> str:
        origin = self.artist or self.album
        if self.title:
            if origin:
                return f"{origin} - {self.title}"
            return self.title
        return origin or "Unknown Song"

    @property
    def age(self) -> float:
        return time.time() - self.timestamp

    @property
    def estimated_progress(self) -> Optional[float]:
        if self.progress is not None:
            progress = self.progress + self.age
            if self.duration is not None and progress > self.duration:
                progress = self.duration
            return progress

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
        self.update_interval = kwargs.pop("update_interval", 25)
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

    def handle_remaining_duration(self, song_id: str, remaining: float) -> Tuple[float, float]:
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

        log.debug(f"scraping current song data for {self}")
        data = await self.song_scraper.scrape(self.manager.aiosession)

        kwargs = {key: value for key, value in data.items() if key in RADIO_SONG_DATA_FIELDS and value is not None}

        if "remaining_duration" in data:
            remaining = utils.parse_timestamp(data["remaining_duration"])
            song_id = "".join(filter(None, map(kwargs.get, ("title", "artist", "album"))))
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
        _station = self.get_station(station.name)
        if _station:
            raise ValueError(f"{self} already has {station} ({_station})")

        station.manager = self
        self.stations.append(station)

    def get_station(self, name: str) -> Optional[RadioStation]:
        return next((station for station in self if station.name == name), None)

    def find_station(self, query: str) -> Optional[RadioStation]:
        for station in self:
            if station.is_alias(query):
                return station
