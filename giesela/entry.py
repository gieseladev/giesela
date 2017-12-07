import asyncio
import copy
import os
import time
import traceback

from discord import Channel, Member, Server, User

from giesela.exceptions import (BrokenEntryError, ExtractionError,
                                OutdatedEntryError)
from giesela.lyrics import search_for_lyrics
from giesela.radio import RadioSongExtractor, StationInfo
from giesela.spotify import SpotifyTrack
from giesela.utils import (clean_songname, get_header, get_image_brightness,
                           md5sum, slugify)
from giesela.web_author import WebAuthor


class Entry:
    version_code = "1.0.3"
    version = int(version_code.replace(".", ""))
    can_encode = (int, dict, list, str, int, float, bool)
    default_encode = (Channel, Member, Server, User)
    meta_dict_keys = ("author", "playlist")

    @classmethod
    def from_dict(cls, queue, data):
        entry_version = data.get("version", 0)

        if entry_version < Entry.version:
            raise OutdatedEntryError("Version parameter signifies an outdated entry")

        if data.get("broken", False):
            raise BrokenEntryError("This entry has been marked as broken")

        entry_type = data.get("type", None)
        if not entry_type:
            raise KeyError("Data does not include a type parameter")

        target = globals().get(entry_type, None)

        if not target:
            raise TypeError("Cannot create an entry with this type")

        return target.from_dict(queue, data)

    @staticmethod
    def create_meta_dict(meta):
        meta_dict = {}
        for key, value in meta.items():
            if key is None or value is None:
                continue

            # remove unwanted meta stuff
            if str(key).lower() not in Entry.meta_dict_keys:
                continue

            ser_value = {"type": value.__class__.__name__}
            if isinstance(value, Entry.can_encode) or value is None:
                ser_value.update({
                    "type": "built-in/" + ser_value["type"],
                    "value": value
                })
            else:
                if isinstance(value, Entry.default_encode):
                    ser_value.update({
                        "id": value.id,
                        "name": value.name,
                    })

            meta_dict[key] = ser_value

        return meta_dict

    @staticmethod
    def meta_from_dict(data, bot):
        meta = {}
        for key, ser_value in data.items():
            value = None
            value_type = ser_value["type"]
            if value_type.startswith("built-in"):
                value = ser_value["value"]
            elif value_type in ("Member", "User"):
                value = bot.get_global_user(ser_value["id"])
            elif value_type == "Server":
                value = bot.get_server(ser_value["id"])
            elif value == "Channel":
                value = bot.get_channel(ser_value["id"])

            if value:
                meta[key] = value
        return meta


class BaseEntry:

    def __init__(self, queue, url, **meta):
        self.queue = queue
        self.url = url
        self.meta = meta

        self.filename = None
        self.duration = 0
        self._is_downloading = False
        self._waiting_futures = []

        self._lyrics = None
        self._lyrics_dirty = False

    @property
    def title(self):
        raise NotImplementedError

    @property
    def lyrics_title(self):
        return self.title

    @property
    def lyrics(self):
        if self._lyrics_dirty or not self._lyrics:
            self._lyrics = search_for_lyrics(self.lyrics_title)
            self._lyrics_dirty = False

        return self._lyrics

    @property
    def _is_current_entry(self):
        current_entry = self.queue.player.current_entry
        return self == current_entry

    @property
    def is_downloaded(self):
        if self._is_downloading:
            return False

        return bool(self.filename)

    @property
    def sortby(self):
        return self.url

    @property
    def start_seconds(self):
        return None

    async def _download(self):
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data, queue):
        raise NotImplementedError

    def copy(self):
        return copy.copy(self)

    def to_dict(self):
        raise NotImplementedError

    def to_web_dict(self):
        return self.to_dict()

    def get_ready_future(self):
        """
        Returns a future that will fire when the song is ready to be played. The future will either fire with the result (being the entry) or an exception
        as to why the song download failed.
        """
        future = asyncio.Future()
        if self.is_downloaded:
            # In the event that we're downloaded, we're already ready for
            # playback.
            future.set_result(self)

        else:
            # If we request a ready future, let's ensure that it'll actually
            # resolve at one point.
            asyncio.ensure_future(self._download())
            self._waiting_futures.append(future)

        return future

    def _for_each_future(self, cb):
        """
            Calls `cb` for each future that is not cancelled. Absorbs and logs any errors that may have occurred.
        """
        futures = self._waiting_futures
        self._waiting_futures = []

        for future in futures:
            if future.cancelled():
                continue

            try:
                cb(future)

            except:
                traceback.print_exc()

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)


class StreamEntry(BaseEntry):

    def __init__(self, queue, url, title, destination=None, **meta):
        super().__init__(queue, url, **meta)

        self._title = title
        self.destination = destination

        if self.destination:
            self.filename = self.destination

    @property
    def title(self):
        return self._title

    @property
    def sortby(self):
        return self._title

    def set_start(self, sec):
        raise NotImplementedError

    def set_end(self, sec):
        raise NotImplementedError

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        url = data["url"]
        title = data["title"]

        return cls(queue, url, title, **meta)

    def to_dict(self):
        meta_dict = Entry.create_meta_dict(self.meta)

        data = {
            "version":  Entry.version,
            "type":     self.__class__.__name__,
            "url":      self.url,
            "title":    self._title,
            "meta":     meta_dict
        }
        return data

    def to_web_dict(self):
        origin = None
        if self.meta:
            if "playlist" in self.meta:
                origin = {"type": "playlist"}
                origin.update(self.meta["playlist"])
            elif "author" in self.meta:
                origin = {"type": "user"}
                web_author = WebAuthor.from_id(self.meta["author"].id)
                origin.update(web_author.to_dict())

        data = {
            "type":     self.__class__.__name__,
            "url":      self.url,
            "origin":   origin,
            "title":    self.title
        }

        return data

    async def _download(self, *, fallback=False):
        self._is_downloading = True

        url = self.destination if fallback else self.url

        try:
            result = await self.queue.downloader.extract_info(
                self.queue.loop, url, download=False)
        except Exception as e:
            if not fallback and self.destination:
                return await self._download(fallback=True)

            raise ExtractionError(e)
        else:
            self.filename = result["url"]
        finally:
            self._is_downloading = False


class RadioStationEntry(StreamEntry):

    def __init__(self, queue, station_data, destination=None, **meta):
        super().__init__(queue, station_data.url, station_data.name, destination, **meta)
        self.station_data = station_data
        self.station_name = station_data.name
        self._cover = self.station_data.cover

    @property
    def title(self):
        return self._title

    @property
    def cover(self):
        return self._cover

    @property
    def thumbnail(self):
        return self.station_data.thumbnail

    @property
    def link(self):
        return self.station_data.website

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        url = data["url"]
        title = data["title"]
        station_data = StationInfo.from_dict(data["station_data"])

        return cls(queue, url, title, station_data, **meta)

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "station_data": self.station_data.to_dict()
        })

        return d

    def to_web_dict(self):
        origin = None
        if self.meta:
            if "playlist" in self.meta:
                origin = {"type": "playlist"}
                origin.update(self.meta["playlist"])
            elif "author" in self.meta:
                origin = {"type": "user"}
                web_author = WebAuthor.from_id(self.meta["author"].id)
                origin.update(web_author.to_dict())

        data = {
            "type":                 self.__class__.__name__,
            "url":                  self.url,
            "thumbnail":            self.thumbnail,
            "thumbnail_brightness": get_image_brightness(url=self.thumbnail),
            "origin":               origin,
            "title":                self.title,
            "cover":                self.cover,
            "link":                 self.link
        }

        return data


class RadioSongEntry(RadioStationEntry):

    def __init__(self, queue, station_data, destination=None, **meta):
        super().__init__(queue, station_data, destination, **meta)
        self._current_song_info = None
        self._csi_poll_time = 0

        self.poll_time = station_data.poll_time
        self.uncertainty = station_data.uncertainty

    @property
    def sortby(self):
        return self.title

    @property
    def lyrics_title(self):
        return "{} - {}".format(self.title, self.artist)

    def _get_new_song_info(self):
        self._current_song_info = RadioSongExtractor.get_current_song(
            self.station_data)
        self._csi_poll_time = time.time()

    @property
    def current_song_info(self):
        if self._current_song_info is None or (time.time() - self._csi_poll_time) > 5:
            print("[RadioEntry] getting new current_song_info")
            self._lyrics_dirty = True
            self._get_new_song_info()

        return self._current_song_info

    @property
    def song_progress(self):
        if not self._is_current_entry:
            return None

        return self.current_song_info["progress"]

    @property
    def song_duration(self):
        if not self._is_current_entry:
            return None

        return self.current_song_info["duration"]

    @property
    def link(self):
        if not self._is_current_entry:
            return super().link

        return self.current_song_info["youtube"] or super().link

    @property
    def title(self):
        if not self._is_current_entry:
            return super().title

        return self.current_song_info["title"]

    @property
    def artist(self):
        if not self._is_current_entry:
            return None

        return self.current_song_info["artist"]

    @property
    def cover(self):
        if not self._is_current_entry:
            return super().cover

        return self.current_song_info["cover"]

    def to_web_dict(self):
        data = super().to_web_dict()

        data.update({
            "station":          self.station_data.to_dict(),
            "title":            self.title,
            "artist":           self.artist,
            "cover":            self.cover,
            "song_progress":    self.song_progress,
            "song_duration":    self.song_duration
        })

        return data


class YoutubeEntry(BaseEntry):

    def __init__(self, queue, video_id, url, title, duration, thumbnail, description, expected_filename=None, thumbnail_brightness=None, **meta):
        super().__init__(queue, url, **meta)

        self.video_id = video_id
        self._title = title
        self.thumbnail = thumbnail
        self._thumbnail_brightness = thumbnail_brightness
        self.description = description
        self.duration = duration

        self.end_seconds = meta.get("end_seconds", duration)
        self._start_seconds = meta.get("start_seconds", 0)
        self._seek_seconds = meta.get("seek_seconds", None)

        self.expected_filename = expected_filename

        self.download_folder = self.queue.downloader.download_folder

    @property
    def title(self):
        return clean_songname(self._title)

    @property
    def thumbnail_brightness(self):
        if not self._thumbnail_brightness:
            self._thumbnail_brightness = get_image_brightness(url=self.thumbnail)

        return self._thumbnail_brightness

    @property
    def sortby(self):
        return clean_songname(self._title)

    @property
    def start_seconds(self):
        secs = 0

        if self._seek_seconds is not None:
            secs = self._seek_seconds
        else:
            secs = self._start_seconds

        return secs

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        filename = data["expected_filename"]
        video_id = data["video_id"]
        url = data["url"]
        title = data["title"]
        duration = data["duration"]
        thumbnail = data["thumbnail"]
        thumbnail_brightness = data.get("thumbnail_brightness")
        description = data["description"]

        return cls(queue, video_id, url, title, duration, thumbnail, description, expected_filename=filename, thumbnail_brightness=thumbnail_brightness, **meta)

    def seek(self, secs):
        if not 0 <= secs < self.end_seconds:
            return False

        self._seek_seconds = secs
        return True

    def set_start(self, secs):
        if not 0 <= secs < self.end_seconds:
            return False

        self._start_seconds = secs
        return True

    def set_end(self, secs):
        if not 0 < secs <= self.duration:
            return False

        self.end_seconds = sec
        return True

    def copy(self):
        new = copy.copy(self)
        new._seek_seconds = None

        return new

    def to_dict(self):
        meta_dict = Entry.create_meta_dict(self.meta)

        data = {
            "version":              Entry.version,
            "type":                 self.__class__.__name__,
            "expected_filename":    self.expected_filename,
            "video_id":             self.video_id,
            "url":                  self.url,
            "title":                self._title,
            "duration":             self.duration,
            "thumbnail":            self.thumbnail,
            "thumbnail_brightness": self._thumbnail_brightness,
            "description":          self.description,
            "meta":                 meta_dict
        }
        return data

    def to_web_dict(self):
        origin = None
        if self.meta:
            if "playlist" in self.meta:
                origin = {"type": "playlist"}
                origin.update(self.meta["playlist"])
            elif "author" in self.meta:
                origin = {"type": "user"}
                web_author = WebAuthor.from_id(self.meta["author"].id)
                origin.update(web_author.to_dict())

        data = {
            "type":                 self.__class__.__name__,
            "url":                  self.url,
            "thumbnail":            self.thumbnail,
            "origin":               origin,
            "title":                self.title,
            "duration":             self.duration,
        }

        return data

    async def _download(self):
        if self._is_downloading:
            return

        self._is_downloading = True
        try:
            # Ensure the folder that we're going to move into exists.
            if not os.path.exists(self.download_folder):
                os.makedirs(self.download_folder)

            # self.expected_filename:
            # audio_cache\youtube-9R8aSKwTEMg-NOMA_-_Brain_Power.m4a

            if self.expected_filename is None:
                self.expected_filename = slugify("unknown" + self.title)

            extractor = os.path.basename(self.expected_filename).split("-")[0]

            # the generic extractor requires special handling
            if extractor == "generic":
                # print("Handling generic")
                flistdir = [
                    f.rsplit("-", 1)[0]
                    for f in os.listdir(self.download_folder)
                ]
                expected_fname_noex, fname_ex = os.path.basename(
                    self.expected_filename).rsplit(".", 1)

                if expected_fname_noex in flistdir:
                    try:
                        rsize = int(
                            await get_header(self.queue.bot.aiosession,
                                             self.url, "CONTENT-LENGTH"))
                    except:
                        rsize = 0

                    lfile = os.path.join(self.download_folder,
                                         os.listdir(self.download_folder)
                                         [flistdir.index(expected_fname_noex)])

                    # print("Resolved %s to %s" % (self.expected_filename, lfile))
                    lsize = os.path.getsize(lfile)
                    # print("Remote size: %s Local size: %s" % (rsize, lsize))

                    if lsize != rsize:
                        await self._really_download(hash=True)
                    else:
                        # print("[Download] Cached:", self.url)
                        self.filename = lfile

                else:
                    # print("File not found in cache (%s)" % expected_fname_noex)
                    await self._really_download(hash=True)

            else:
                ldir = os.listdir(self.download_folder)
                flistdir = [f.rsplit(".", 1)[0] for f in ldir]
                expected_fname_base = os.path.basename(self.expected_filename)
                expected_fname_noex = expected_fname_base.rsplit(".", 1)[0]

                # idk wtf this is but its probably legacy code
                # or i have youtube to blame for changing shit again

                if expected_fname_base in ldir:
                    self.filename = os.path.join(self.download_folder,
                                                 expected_fname_base)
                    print("[Download] Cached:", self.url)

                elif expected_fname_noex in flistdir:
                    print("[Download] Cached (different extension):", self.url)
                    self.filename = os.path.join(
                        self.download_folder,
                        ldir[flistdir.index(expected_fname_noex)])
                    print("Expected %s, got %s" %
                          (self.expected_filename.rsplit(".", 1)[-1],
                           self.filename.rsplit(".", 1)[-1]))

                else:
                    await self._really_download()

            # Trigger ready callbacks.
            self._for_each_future(lambda future: future.set_result(self))

        except Exception as e:
            traceback.print_exc()
            self._for_each_future(lambda future: future.set_exception(e))

        finally:
            self._is_downloading = False

    async def _really_download(self, *, hash=False):
        print("[Download] Started:", self.url)

        try:
            result = await self.queue.downloader.extract_info(
                self.queue.loop, self.url, download=True)
        except Exception as e:
            raise ExtractionError(e)

        print("[Download] Complete:", self.url)

        if result is None:
            raise ExtractionError("ytdl broke and hell if I know why")
            # What the duck do I do now?

        self.filename = unhashed_fname = self.queue.downloader.ytdl.prepare_filename(
            result)

        if hash:
            # insert the 8 last characters of the file hash to the file name to
            # ensure uniqueness
            self.filename = md5sum(
                unhashed_fname,
                8).join("-.").join(unhashed_fname.rsplit(".", 1))

            if os.path.isfile(self.filename):
                # Oh bother it was actually there.
                os.unlink(unhashed_fname)
            else:
                # Move the temporary file to it's final location.
                os.rename(unhashed_fname, self.filename)


class TimestampEntry(YoutubeEntry):

    def __init__(self, queue, video_id, url, title, duration, thumbnail, description, sub_queue, expected_filename=None, thumbnail_brightness=None, **meta):
        super().__init__(queue, video_id, url, title, duration, thumbnail, description, expected_filename=expected_filename, thumbnail_brightness=thumbnail_brightness, **meta)

        self.sub_queue = sub_queue

    @property
    def current_sub_entry(self):
        if not self._is_current_entry:
            return self.sub_queue[0]

        progress = self.queue.player.progress

        sub_entry = None
        for entry in self.sub_queue:
            if progress >= entry["start"] or sub_entry is None:
                sub_entry = entry

        sub_entry["progress"] = max(progress - sub_entry["start"], 0)

        self._lyrics_dirty = True
        return sub_entry

    @property
    def title(self):
        if self._is_current_entry:
            return clean_songname(self.current_sub_entry["name"])
        else:
            return clean_songname(self._title)

    @property
    def whole_title(self):
        return clean_songname(self._title)

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        filename = data["expected_filename"]
        video_id = data["video_id"]
        url = data["url"]
        title = data["title"]
        duration = data["duration"]
        thumbnail = data["thumbnail"]
        thumbnail_brightness = data.get("thumbnail_brightness")
        description = data["description"]
        sub_queue = data["sub_queue"]

        return cls(queue, video_id, url, title, duration, thumbnail, description, sub_queue, expected_filename=filename, thumbnail_brightness=thumbnail_brightness, **meta)

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "sub_queue": self.sub_queue
        })

        return d

    def to_web_dict(self):
        data = super().to_web_dict()

        data.update({
            "whole_title":  self.whole_title,
            "title":        self.title,
            "sub_entry":    self.current_sub_entry
        })

        return data


class GieselaEntry(YoutubeEntry):

    def __init__(self, queue, video_id, url, title, duration, thumbnail, description, song_title, artist, artist_image, album, cover, expected_filename=None, thumbnail_brightness=None, **meta):
        super().__init__(queue, video_id, url, title, duration, thumbnail, description, expected_filename=expected_filename, thumbnail_brightness=thumbnail_brightness, **meta)

        self.song_title = song_title
        self.artist = artist
        self.artist_image = artist_image
        self.cover = cover
        self.album = album

    @property
    def title(self):
        return "{} - {}".format(self.artist, self.song_title)

    @property
    def lyrics_title(self):
        return "{} - {}".format(self.song_title, self.artist)

    @property
    def sortby(self):
        return self.song_title

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        filename = data["expected_filename"]
        video_id = data["video_id"]
        url = data["url"]
        title = data["title"]
        duration = data["duration"]
        thumbnail = data["thumbnail"]
        thumbnail_brightness = data.get("thumbnail_brightness")
        description = data["description"]

        song_title = data["song_title"]
        artist = data["artist"]
        artist_image = data["artist_image"]
        cover = data["cover"]
        album = data["album"]

        return cls(queue, video_id, url, title, duration, thumbnail, description, song_title, artist, artist_image, album, cover, expected_filename=filename, thumbnail_brightness=thumbnail_brightness, **meta)

    @classmethod
    def upgrade(cls, previous_entry, song_title, artist, artist_image, album, cover):
        kwargs = {
            "queue":                previous_entry.queue,
            "video_id":             previous_entry.video_id,
            "url":                  previous_entry.url,
            "title":                previous_entry._title,
            "duration":             previous_entry.duration,
            "thumbnail":            previous_entry.thumbnail,
            "description":          previous_entry.description,
            "expected_filename":    previous_entry.expected_filename,
            "song_title":           song_title,
            "artist":               artist,
            "artist_image":         artist_image,
            "album":                album,
            "cover":                cover
        }

        kwargs.update(previous_entry.meta)

        return cls(**kwargs)

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "song_title":   self.song_title,
            "artist":       self.artist,
            "artist_image": self.artist_image,
            "cover":        self.cover,
            "album":        self.album
        })

        return d

    def to_web_dict(self):
        data = super().to_web_dict()

        data.update({
            "title":    self.song_title,
            "artist":   self.artist,
            "album":    self.album,
            "cover":    self.cover
        })

        return data


class VGMEntry(GieselaEntry):
    pass


class DiscogsEntry(GieselaEntry):
    pass


class SpotifyEntry(GieselaEntry):

    def __init__(self, queue, video_id, url, title, duration, thumbnail, description, spotify_track, expected_filename=None, thumbnail_brightness=None, **meta):
        super().__init__(
            queue, video_id, url, title, duration, thumbnail, description,
            spotify_track.name,
            spotify_track.artist_string,
            spotify_track.artists[0].image,
            spotify_track.album.name,
            spotify_track.cover_url,
            expected_filename=expected_filename,
            thumbnail_brightness=thumbnail_brightness,
            **meta
        )

        self.spotify_data = spotify_track

        self.popularity = spotify_track.popularity / 100

    @classmethod
    def from_dict(cls, queue, data):
        if data["type"] != cls.__name__:
            raise AttributeError("This data isn't of this entry type")

        meta_dict = data.get("meta", None)
        if meta_dict:
            meta = Entry.meta_from_dict(meta_dict, queue.bot)
        else:
            meta = {}

        filename = data["expected_filename"]
        video_id = data["video_id"]
        url = data["url"]
        title = data["title"]
        duration = data["duration"]
        thumbnail = data["thumbnail"]
        thumbnail_brightness = data.get("thumbnail_brightness")
        description = data["description"]
        spotify_data = SpotifyTrack.from_dict(data["spotify_data"])

        return cls(queue, video_id, url, title, duration, thumbnail, description, spotify_data, expected_filename=filename, thumbnail_brightness=thumbnail_brightness, **meta)

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "spotify_data": self.spotify_data.get_dict()
        })

        return d
