import json
import os
import re
import traceback
from threading import Thread

import requests

import asyncio

from .exceptions import ExtractionError
from .spotify import SpotifyTrack
from .utils import (clean_songname, get_header, get_video_timestamps, md5sum,
                    slugify)


class BasePlaylistEntry:

    def __init__(self):
        self.filename = None
        self._is_downloading = False
        self._waiting_futures = []
        self.start_seconds = 0
        self.end_seconds = None
        self.duration = 0
        self._spotify_track = None
        self.provided_song_timestamps = None
        self.searched_additional_information = False
        self._sub_queue = None
        self.video_id = None

    @property
    def is_downloaded(self):
        if self._is_downloading:
            return False

        return bool(self.filename)

    @property
    def provides_timestamps(self):
        return self.provided_song_timestamps is not None

    @property
    def thumbnail(self):
        return None

    def sub_queue(self, min_progress=-1):
        if not self.provides_timestamps:
            return None

        if not self._sub_queue:
            queue = []
            entries = sorted(list(self.provided_song_timestamps.keys()))
            for index, key in enumerate(entries):
                entry = int(key)

                dur = (int(entries[index + 1])
                       if index + 1 < len(entries) else self.duration) - entry
                e = {
                    "name": self.provided_song_timestamps[key],
                    "duration": dur,
                    "start": entry,
                    "index": index,
                    "end": dur + entry
                }
                queue.append(e)

            self._sub_queue = queue

        if min_progress >= 0:
            queue = []
            for sub_entry in self._sub_queue:
                if sub_entry["start"] < min_progress:
                    continue
                queue.append(sub_entry)
        else:
            queue = self._sub_queue

        return queue

    def get_current_song_from_timestamp(self, progress):
        if not self.provides_timestamps:
            return False

        current_title = None
        for entry in self.sub_queue():
            if progress >= entry["start"] or current_title is None:
                current_title = entry

        return current_title

    def get_timestamped_song(self, index):
        return self.sub_queue()[index]

    def get_local_progress(self, progress):
        if not self.provides_timestamps:
            return False
        entry = self.get_current_song_from_timestamp(progress)
        return progress - entry["start"], entry["duration"]

    async def _download(self):
        raise NotImplementedError

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


class URLPlaylistEntry(BasePlaylistEntry):

    def __init__(self, queue, url, title, duration=0, expected_filename=None, start_seconds=0, end_seconds=None, spotify_track=None, provided_song_timestamps=None, youtube_data=None, update_additional_information=True, **meta):
        super().__init__()

        self.playlist = queue
        self.url = url
        self.video_id = re.search(
            r"(?:https?:\/{2})?(?:w{3}\.)?youtu(?:be)?\.(?:com|be)(?:\/watch\?v=|\/)([^\s&]+)", url).group(1)
        self._title = title
        self.duration = duration
        self.end_seconds = end_seconds if end_seconds else duration

        self.start_seconds = start_seconds
        self.expected_filename = expected_filename
        self.meta = meta

        self.download_folder = self.playlist.downloader.download_folder

        self.provided_song_timestamps = provided_song_timestamps
        self._spotify_track = spotify_track
        self.youtube_data = youtube_data
        self.running_threads = []

        if update_additional_information:
            self.search_additional_info()

    @property
    def title(self):
        if self.spotify_track is not None and self.spotify_track.certainty > .6:
            return self.spotify_track.name + " - " + self.spotify_track.artist
        else:
            return clean_songname(self._title)

    @property
    def thumbnail(self):
        if not self.youtube_data:
            self.get_youtube_data()

        try:
            thumbnails = self.youtube_data["snippet"]["thumbnails"]
            ranks = ["maxres", "high", "medium", "standard", "default"]
            for res in ranks:
                if res in thumbnails:
                    return thumbnails[res]["url"]
        except (KeyError, TypeError):
            return None

    @property
    def spotify_track(self):
        return self._spotify_track if self._spotify_track and self._spotify_track.certainty > .6 else None

    def threaded_spotify_search(self):
        self._spotify_track = SpotifyTrack.from_query(self._title)

    @classmethod
    def from_dict(cls, playlist, data, update_additional_information=True):
        url = data['url']
        title = data['title']
        duration = data['duration']
        downloaded = data['downloaded']
        filename = data['filename'] if downloaded else None
        spotify_track = SpotifyTrack.from_dict(data.get("spotify_track", None))
        provided_song_timestamps = data.get("provided_song_timestamps", None)
        youtube_data = data.get("youtube_data", None)
        start_seconds = data.get("start_seconds", 0)
        start_seconds = 0 if start_seconds is None else start_seconds
        end_seconds = data.get("end_seconds", duration)
        meta = {}

        if "meta" in data:
            if 'channel' in data['meta']:
                ch = playlist.bot.get_channel(data['meta']['channel']['id'])
                meta['channel'] = ch or data['meta']['channel']['name']

            if 'author' in data['meta']:
                meta['author'] = playlist.bot.get_global_user(
                    data['meta']['author']['id'])

            if "playlist" in data["meta"]:
                meta["playlist"] = data["meta"]["playlist"]

        return cls(
            playlist,
            url,
            title,
            duration,
            filename,
            start_seconds,
            end_seconds,
            spotify_track=spotify_track,
            provided_song_timestamps=provided_song_timestamps,
            youtube_data=youtube_data,
            update_additional_information=update_additional_information,
            **meta)

    def search_additional_info(self):
        if self._spotify_track is None:
            t = Thread(target=self.threaded_spotify_search)
            t.start()
            self.running_threads.append(t)

        if self.provided_song_timestamps is None:
            t = Thread(target=self.search_for_timestamps)
            t.start()
            self.running_threads.append(t)

        if self.youtube_data is None:
            t = Thread(target=self.get_youtube_data).start()
            t.start()
            self.running_threads.append(t)

        self.searched_additional_information = True

    def search_for_timestamps(self):
        songs = get_video_timestamps(self.url, self.duration)

        if songs is None or len(songs) < 1:
            return

        self.provided_song_timestamps = songs

    def get_youtube_data(self):
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos?key=AIzaSyCvvKzdz-bVJUUyIzKMAYmHZ0FKVLGSJlo&part=snippet,statistics&id=" + self.video_id)
        items = resp.json()["items"]

        if not items:
            # video doesn't exist
            return

        try:
            self.youtube_data = items[0]
        except:
            print(self.video_id)
            print(resp.json())
            raise

    def to_dict(self):
        meta_dict = {}
        for i in self.meta:
            if i is None or self.meta[i] is None:
                continue

            meta_dict[i] = {
                'type': self.meta[i].__class__.__name__,
                'id': self.meta[i].id,
                'name': self.meta[i].name
            }

        data = {
            'type': self.__class__.__name__,
            'url': self.url,
            'title': self._title,
            'duration': self.duration,
            'downloaded': self.is_downloaded,
            'filename': self.filename,
            "expected_filename": self.expected_filename,
            'meta': meta_dict,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "spotify_track": self.spotify_track.get_dict() if self.spotify_track is not None else None,
            "provided_song_timestamps": self.provided_song_timestamps,
            "youtube_data": self.youtube_data,
            "thumbnail": self.thumbnail if self.youtube_data else None
        }
        return data

    def set_start(self, sec):
        if sec >= (self.end_seconds
                   if self.end_seconds is not None else self.duration):
            return False

        self.start_seconds = sec
        return True

    def set_end(self, sec):
        if sec <= self.start_seconds:
            return False

        self.end_seconds = sec
        return True

    def set_title(self, new_title):
        new_title = new_title.strip()

        if len(new_title) > 300 or len(new_title) < 3:
            return False

        self.title = new_title
        return True

    def get_ready_future(self):
        self.search_additional_info()
        return BasePlaylistEntry.get_ready_future(self)

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

            extractor = os.path.basename(self.expected_filename).split('-')[0]

            # the generic extractor requires special handling
            if extractor == 'generic':
                # print("Handling generic")
                flistdir = [
                    f.rsplit('-', 1)[0]
                    for f in os.listdir(self.download_folder)
                ]
                expected_fname_noex, fname_ex = os.path.basename(
                    self.expected_filename).rsplit('.', 1)

                if expected_fname_noex in flistdir:
                    try:
                        rsize = int(
                            await get_header(self.playlist.bot.aiosession,
                                             self.url, 'CONTENT-LENGTH'))
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
                flistdir = [f.rsplit('.', 1)[0] for f in ldir]
                expected_fname_base = os.path.basename(self.expected_filename)
                expected_fname_noex = expected_fname_base.rsplit('.', 1)[0]

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
                          (self.expected_filename.rsplit('.', 1)[-1],
                           self.filename.rsplit('.', 1)[-1]))

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
            result = await self.playlist.downloader.extract_info(
                self.playlist.loop, self.url, download=True)
        except Exception as e:
            raise ExtractionError(e)

        print("[Download] Complete:", self.url)

        if result is None:
            raise ExtractionError("ytdl broke and hell if I know why")
            # What the fuck do I do now?

        self.filename = unhashed_fname = self.playlist.downloader.ytdl.prepare_filename(
            result)

        if hash:
            # insert the 8 last characters of the file hash to the file name to
            # ensure uniqueness
            self.filename = md5sum(
                unhashed_fname,
                8).join('-.').join(unhashed_fname.rsplit('.', 1))

            if os.path.isfile(self.filename):
                # Oh bother it was actually there.
                os.unlink(unhashed_fname)
            else:
                # Move the temporary file to it's final location.
                os.rename(unhashed_fname, self.filename)


class StreamPlaylistEntry(BasePlaylistEntry):

    def __init__(self, playlist, url, title, station_data=None, *, destination=None, **meta):
        super().__init__()

        self.playlist = playlist
        self.url = url
        if station_data is None:
            self.title = title
        else:
            self.title = station_data.name

        self.radio_station_data = station_data
        self.destination = destination
        self.duration = 0
        self.meta = meta

        if self.destination:
            self.filename = self.destination

    def to_dict(self):
        meta_dict = {}
        for i in self.meta:
            if i is None or self.meta[i] is None:
                continue

            meta_dict[i] = {
                'type': self.meta[i].__class__.__name__,
                'id': self.meta[i].id,
                'name': self.meta[i].name
            }

        data = {
            'type': self.__class__.__name__,
            'url': self.url,
            'title': self._title,
            'downloaded': self.is_downloaded,
            'filename': self.filename,
            "expected_filename": self.expected_filename,
            'meta': meta_dict,
            "station_data": self.radio_station_data.to_dict() if self.radio_station_data else None
        }
        return data

    async def _download(self, *, fallback=False):
        self._is_downloading = True

        url = self.destination if fallback else self.url

        try:
            result = await self.playlist.downloader.extract_info(
                self.playlist.loop, url, download=False)
        except Exception as e:
            if not fallback and self.destination:
                return await self._download(fallback=True)

            raise ExtractionError(e)
        else:
            self.filename = result['url']
            # I might need some sort of events or hooks or shit
            # for when ffmpeg inevitebly fucks up and i have to restart
            # although maybe that should be at a slightly lower level
        finally:
            self._is_downloading = False
