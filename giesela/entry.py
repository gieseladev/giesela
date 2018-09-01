import abc
import asyncio
import copy
import logging
import os
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .exceptions import (ExtractionError, OutdatedEntryError)
from .lyrics import search_for_lyrics
from .radio import RadioSongData, RadioStation
from .utils import clean_songname

if TYPE_CHECKING:
    from .queue import Queue
    from .player import MusicPlayer

log = logging.getLogger(__name__)


class BaseEntry(metaclass=abc.ABCMeta):
    filename: Optional[str]
    url: str
    meta: Dict[str, Any]
    duration: Optional[int]

    _lyrics: Optional[str]

    def __init__(self, filename: Optional[str], url: str, duration: int = None, **meta):
        self.filename = filename
        self.url = url
        self.meta = meta

        self.duration = duration

        self._is_downloading = False
        self._waiting_futures = []

        self._lyrics = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.url}>"

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other) -> bool:
        return self is other

    @property
    @abc.abstractmethod
    def title(self) -> str:
        raise NotImplementedError

    @property
    def link(self) -> str:
        return self.url

    @property
    def sort_attr(self) -> str:
        return self.url

    @property
    def lyrics_search_query(self) -> str:
        return self.sort_attr

    @property
    def lyrics(self) -> str:
        if not self._lyrics:
            self._lyrics = search_for_lyrics(self.lyrics_search_query)

        return self._lyrics

    @property
    def is_downloaded(self) -> bool:
        if self._is_downloading:
            return False
        return self.filename and os.path.isfile(self.filename)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEntry":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return dict(version=Entry.VERSION, type=type(self).__name__, filename=self.filename, url=self.url, duration=self.duration)

    def to_web_dict(self, player: "MusicPlayer") -> Dict[str, Any]:
        data = self.to_dict()
        del data["version"]
        del data["filename"]
        data.update(link=self.link)
        return data

    def copy(self) -> "BaseEntry":
        return copy.copy(self)

    def get_ready_future(self, queue: "Queue") -> asyncio.Future:
        future = asyncio.Future()
        if self.is_downloaded:
            future.set_result(self)
        else:
            asyncio.ensure_future(self._download(queue))
            self._waiting_futures.append(future)

        return future

    def _for_each_future(self, cb):
        futures = self._waiting_futures
        self._waiting_futures = []

        for future in futures:
            if future.cancelled():
                continue

            try:
                cb(future)
            except Exception:
                log.exception(f"error while running {cb} on {future}")

    async def _download(self, queue: "Queue", **kwargs):
        if self._is_downloading:
            return

        self._is_downloading = True

        downloader = queue.downloader
        download_folder = downloader.download_folder

        if not self.filename:
            self.filename = downloader.prepare_filename(self.url)

        if not os.path.exists(download_folder):
            os.makedirs(download_folder)

        try:
            downloaded_file_names = os.listdir(download_folder)
            downloaded_names = [f.rsplit(".", 1)[0] for f in downloaded_file_names]
            expected_file_name = os.path.basename(self.filename)
            expected_name = expected_file_name.rsplit(".", 1)[0]

            if expected_file_name in downloaded_file_names:
                log.debug(f"found {self} in cache")
            elif expected_name in downloaded_names:
                real_filename = downloaded_file_names[downloaded_names.index(expected_name)]

                expected = self.filename.rsplit(".", 1)[-1]
                seen = real_filename.rsplit(".", 1)[-1]

                log.debug(f"found {self} (with different extension \"{expected}\" vs \"{seen}\") in cache")
                self.filename = os.path.join(download_folder, real_filename)
            else:
                await self._really_download(queue)

            self._for_each_future(lambda future: future.set_result(self))

        except Exception as e:
            log.exception("error while downloading")
            self._for_each_future(lambda future: future.set_exception(e))

        finally:
            self._is_downloading = False

    async def _really_download(self, queue: "Queue"):
        log.info(f"downloading {self}")

        try:
            result = await queue.downloader.extract_info(self.url, filename=self.filename)
        except Exception as e:
            raise ExtractionError(e)

        log.info(f"download complete ({self})")

        if not result:
            raise ExtractionError("ytdl broke and hell if I know why")

        self.filename = queue.downloader.prepare_filename(result["webpage_url"])


class StreamEntry(BaseEntry):
    _title: str

    def __init__(self, url: str, title: str, **kwargs):
        super().__init__(url, url, None, **kwargs)

        self._title = title

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self._title}>"

    @property
    def title(self) -> str:
        return self._title

    @property
    def sort_attr(self):
        return self.title

    @property
    def is_downloaded(self) -> bool:
        if self._is_downloading:
            return False
        return bool(self.filename)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(title=self._title)
        return data

    async def _download(self, queue: "Queue", **kwargs):
        self._is_downloading = True

        fallback = kwargs.get("fallback", False)
        url = self.filename if fallback else self.url

        try:
            result = await queue.downloader.extract_info(url, download=False)
        except Exception as e:
            if not fallback and self.filename:
                return await self._download(queue, fallback=True)
            raise ExtractionError(e)
        else:
            self.filename = result["url"]
        finally:
            self._is_downloading = False


class RadioStationEntry(StreamEntry):
    station: RadioStation

    def __init__(self, station: RadioStation, **kwargs):
        kwargs.setdefault("title", station.name)
        super().__init__(station.stream, **kwargs)
        self.station = station

    @property
    def link(self) -> str:
        return self.station.website or self.station.stream

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RadioStationEntry":
        data["station"] = RadioStation.from_config(data.pop("station"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(station=self.station.to_dict())
        return data

    @property
    def is_downloaded(self) -> bool:
        return True


class RadioSongEntry(RadioStationEntry):
    _current_song_data: RadioSongData

    def __init__(self, station: RadioStation, song_data: RadioSongData, **kwargs):
        super().__init__(station, **kwargs)
        self._current_song_data = song_data

    async def update(self):
        self._current_song_data = await self.station.get_song_data()

    @property
    def next_update_delay(self) -> float:
        if self.song_data.duration and self.song_data.progress is not None:
            timeout = self.song_data.duration - self.song_progress
        else:
            timeout = self.station.update_interval - self.song_data_age

        if timeout <= 0:
            return 0
        else:
            return timeout + self.station.extra_update_delay

    @property
    def song_data_age(self) -> float:
        return time.time() - self._current_song_data.timestamp

    @property
    def song_data(self) -> RadioSongData:
        return self._current_song_data

    @property
    def song_progress(self) -> Optional[float]:
        if self.song_data.progress is not None:
            progress = self.song_data.progress + self.song_data_age
            if self.song_data.duration:
                progress = min(progress, self.song_data.duration)
            return progress

    @property
    def title(self) -> str:
        artist = self.song_data.artist
        song = self.song_data.song_title
        if song:
            return f"{artist or self.station.name} - {song}"
        elif artist:
            return f"{self.station.name} - {artist}"
        else:
            return super().title

    def to_web_dict(self, player: "MusicPlayer"):
        data = super().to_web_dict(player)

        if player.current_entry is self:
            data.update(song_progress=self.song_progress, song_data=self.song_data.to_dict())

        return data


class YoutubeEntry(BaseEntry):
    video_id: str
    _title: str
    thumbnail: str

    def __init__(self, *args, video_id: str, title: str, thumbnail: str, **kwargs):
        super().__init__(*args, **kwargs)

        self.video_id = video_id
        self._title = title
        self.thumbnail = thumbnail

    @property
    def title(self) -> str:
        return clean_songname(self._title)

    @property
    def sort_attr(self) -> str:
        return self.title

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(video_id=self.video_id, title=self.title, thumbnail=self.thumbnail)
        return data


class TimestampEntry(YoutubeEntry):
    sub_queue: List[dict]

    def __init__(self, *args, sub_queue: List[dict], **kwargs):
        super().__init__(*args, **kwargs)

        self.sub_queue = sub_queue

    def sub_entry_at(self, timestamp: float) -> Optional[dict]:
        sub_entry = None
        for entry in self.sub_queue:
            if timestamp >= entry["start"] or sub_entry is None:
                sub_entry = entry
            else:
                break

        sub_entry["progress"] = max(timestamp - sub_entry["start"], 0)
        return sub_entry

    def get_sub_entry(self, player: "MusicPlayer") -> Optional[dict]:
        if player.current_entry is not self:
            return None

        return self.sub_entry_at(player.progress)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update(sub_queue=self.sub_queue)
        return data


class GieselaEntry(YoutubeEntry):
    song_title: str
    artist: str
    artist_image: str
    cover: str
    album: str

    def __init__(self, *args, song_title: str, artist: str, artist_image: str, album: str, cover: str, **kwargs):
        super().__init__(*args, **kwargs)

        self.song_title = song_title
        self.artist = artist
        self.artist_image = artist_image
        self.cover = cover
        self.album = album

    @property
    def title(self) -> str:
        return f"{self.artist} - {self.song_title}"

    @property
    def sort_attr(self):
        return self.song_title

    @property
    def lyrics_search_query(self) -> str:
        return f"{self.song_title} - {self.artist}"

    @classmethod
    def upgrade(cls, entry: BaseEntry, **kwargs):
        data = entry.to_dict()
        data.update(entry.meta)
        data.update(kwargs)
        return cls.from_dict(data)

    def to_dict(self):
        data = super().to_dict()
        data.update(song_title=self.song_title, artist=self.artist, artist_image=self.artist_image, cover=self.cover, album=self.album)
        return data


class Entry:
    VERSION = 3
    MAPPING = {
        "StreamEntry": StreamEntry,
        "RadioSongEntry": RadioSongEntry,
        "RadioStationEntry": RadioStationEntry,
        "YoutubeEntry": YoutubeEntry,
        "TimestampEntry": TimestampEntry,
        "GieselaEntry": GieselaEntry
    }

    def __new__(cls, *args, **kwargs):
        raise Exception("This class is static")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEntry":
        entry_version = data.get("version", 0)

        if entry_version < Entry.VERSION:
            raise OutdatedEntryError("Version parameter signifies an outdated entry")

        entry_type = data.get("type", None)
        if not entry_type:
            raise KeyError("Data does not include a type parameter")

        target = cls.MAPPING.get(entry_type, None)

        if not target:
            raise TypeError("Cannot create an entry with this type")

        return target.from_dict(data)
