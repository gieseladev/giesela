import datetime
import time
import traceback
from collections import deque
from itertools import islice
from random import shuffle
from urllib.parse import quote

from youtube_dl.utils import DownloadError, ExtractorError, UnsupportedError

from .entry import (RadioSongEntry, RadioStationEntry, SpotifyEntry,
                    StreamEntry, TimestampEntry, YoutubeEntry)
from .exceptions import ExtractionError, WrongEntryTypeError
from .lib.event_emitter import EventEmitter
from .spotify import SpotifyTrack
from .utils import clean_songname, get_header, get_video_sub_queue


class Playlist(EventEmitter):
    """
        A playlist is manages the list of songs that will be played.
    """

    def __init__(self, bot, player):
        super().__init__()
        self.bot = bot
        self.player = player
        self.loop = bot.loop
        self.downloader = bot.downloader
        self.entries = deque()
        self.history = []

    def __iter__(self):
        return iter(self.entries)

    def get_web_dict(self):
        data = {
            "entries": [entry.to_web_dict() for entry in self.entries],
            "history": [entry.to_web_dict() for entry in self.history]
        }
        return data

    def shuffle(self):
        shuffle(self.entries)

    def clear(self):
        self.entries.clear()

    def push_history(self, entry):
        entry.meta["finish_time"] = time.time()
        self.history = [entry, *self.history[:9]]

    async def add_stream_entry(self, stream_url, **meta):
        info = {"title": song_url, "extractor": None}
        try:
            info = await self.downloader.extract_info(self.loop, stream_url, download=False)

        except DownloadError as e:
            if e.exc_info[0] == UnsupportedError:
                print("[STREAM] Assuming content is a direct stream")

            elif e.exc_info[0] == URLError:
                if os.path.exists(os.path.abspath(song_url)):
                    raise ExtractionError(
                        "This is not a stream, this is a file path.")

                else:  # it might be a file path that just doesn't exist
                    raise ExtractionError(
                        "Invalid input: {0.exc_info[0]}: {0.exc_info[1].reason}".format(e))

            else:
                raise ExtractionError("Unknown error: {}".format(e))

        except Exception as e:
            print('Could not extract information from {} ({}), falling back to direct'.format(
                stream_url, e))

        dest_url = stream_url
        if info.get("extractor"):
            dest_url = info.get("url")

        if info.get("extractor", None) == "twitch:stream":
            title = info.get("description")
        else:
            title = info.get("title", "Untitled")

        entry = StreamEntry(
            self,
            stream_url,
            title,
            destination=dest_url,
            **meta
        )

        self._add_entry(entry)

        return entry, len(self.entries)

    async def add_radio_entry(self, station_info, **meta):
        if station_info.has_current_song_info:
            entry = RadioSongEntry(self, station_info, **meta)
        else:
            entry = RadioStationEntry(self, station_info, **meta)

        self._add_entry(entry)

    async def add_entry(self, song_url, **meta):
        """
            Validates and adds a song_url to be played. This does not start the download of the song.

            Returns the entry & the position it is in the queue.

            :param song_url: The song url to add to the playlist.
            :param meta: Any additional metadata to add to the playlist entry.
        """

        entry = await self.get_entry(song_url, **meta)
        self._add_entry(entry)
        return entry, len(self.entries)

    async def add_entry_next(self, song_url, **meta):
        """
            Validates and adds a song_url to be played. This does not start the download of the song.

            Returns the entry & the position it is in the queue.

            :param song_url: The song url to add to the playlist.
            :param meta: Any additional metadata to add to the playlist entry.
        """

        entry = await self.get_entry(song_url, **meta)
        self._add_entry_next(entry)
        return entry, len(self.entries)

    async def get_entry_from_query(self, query, **meta):

        query = quote(query)

        info = await self.downloader.extract_info(
            self.loop, query, download=False, process=False)

        if not info:
            raise ExtractionError("Couldn't extract info")

        if info.get("url", "").startswith("ytsearch"):
            info = await self.downloader.extract_info(
                self.loop,
                query,
                download=False,
                process=True,
                retry_on_error=True
            )

            if not info:
                raise ExtractorError("Couldn't extract info")

            if not all(info.get("entries", [])):
                return None

            query = info["entries"][0]["webpage_url"]
            info = await self.downloader.extract_info(
                self.loop, query, download=False, process=False)

        if "entries" in info:
            return ["http://youtube.com/watch?v=" + entry["id"] for entry in info["entries"]]
        else:
            return await self.get_entry(query, **meta)

    async def get_entries_from_urls_gen(self, *urls, **meta):
        for ind, url in enumerate(urls):
            try:
                entry = await self.get_entry(url, **meta)
            except (ExtractionError, WrongEntryTypeError) as e:
                print("Error while dealing with url \"{}\":\n{}".format(url, e))
                yield ind, None
            yield ind, entry

    async def get_entry(self, song_url, **meta):

        try:
            info = await self.downloader.extract_info(self.loop, song_url, download=False)
        except Exception as e:
            raise ExtractionError(
                'Could not extract information from {}\n\n{}'.format(song_url, e))

        if not info:
            raise ExtractionError(
                'Could not extract information from %s' % song_url)

        if info.get('_type', None) == 'playlist':
            raise WrongEntryTypeError("This is a playlist.", True, info.get(
                'webpage_url', None) or info.get('url', None))

        if info['extractor'] in ['generic', 'Dropbox']:
            try:
                # unfortunately this is literally broken
                # https://github.com/KeepSafe/aiohttp/issues/758
                # https://github.com/KeepSafe/aiohttp/issues/852
                content_type = await get_header(self.bot.aiosession, info['url'], 'CONTENT-TYPE')
                print("Got content type", content_type)

            except Exception as e:
                print("[Warning] Failed to get content type for url %s (%s)" % (
                    song_url, e))
                content_type = None

            if content_type:
                if content_type.startswith(('application/', 'image/')):
                    if '/ogg' not in content_type:  # How does a server say `application/ogg` what the actual fuck
                        raise ExtractionError(
                            "Invalid content type \"%s\" for url %s" % (content_type, song_url))

                elif not content_type.startswith(('audio/', 'video/')):
                    print("[Warning] Questionable content type \"%s\" for url %s" % (
                        content_type, song_url))

        entry = None

        video_id = info.get("id")
        video_title = info.get("title")
        video_description = info.get("description")
        video_thumbnail = info.get("thumbnail")
        video_url = info.get("webpage_url")
        video_duration = info.get("duration", 0)

        clean_title = clean_songname(video_title) or video_title

        spotify_track = SpotifyTrack.from_query(clean_title)
        if spotify_track.certainty > .6:
            entry = SpotifyEntry(
                self,
                video_id,
                video_url,
                video_title,
                video_duration,
                video_thumbnail,
                video_description,
                spotify_track,
                self.downloader.ytdl.prepare_filename(info),
                **meta
            )
        else:
            sub_queue = get_video_sub_queue(
                video_description, video_id, video_duration)

            if sub_queue:
                entry = TimestampEntry(
                    self,
                    video_id,
                    video_url,
                    video_title,
                    video_duration,
                    video_thumbnail,
                    video_description,
                    sub_queue,
                    self.downloader.ytdl.prepare_filename(info),
                    **meta
                )
            else:
                entry = YoutubeEntry(
                    self,
                    video_id,
                    video_url,
                    video_title,
                    video_duration,
                    video_thumbnail,
                    video_description,
                    self.downloader.ytdl.prepare_filename(info),
                    **meta
                )

        return entry

    def add_entries(self, entries):
        for entry in entries:
            self._add_entry(entry)

    def _add_entry(self, entry):
        self.entries.append(entry)
        self.emit('entry-added', playlist=self, entry=entry)

        if self.peek() is entry:
            entry.get_ready_future()

    def _add_entry_next(self, entry):
        self.entries.insert(0, entry)
        self.emit('entry-added', playlist=self, entry=entry)

        if self.peek() is entry:
            entry.get_ready_future()

    def promote_position(self, position):
        rotDist = -1 * (position - 1)
        self.entries.rotate(rotDist)
        entry = self.entries.popleft()
        self.entries.rotate(-1 * rotDist)
        self.entries.appendleft(entry)
        self.emit('entry-added', playlist=self, entry=entry)
        entry.get_ready_future()

        return entry

    def promote_last(self):
        entry = self.entries.pop()
        self.entries.appendleft(entry)
        self.emit('entry-added', playlist=self, entry=entry)
        entry.get_ready_future()

        return entry

    def remove_position(self, position):
        rotDist = -1 * (position - 1)
        self.entries.rotate(rotDist)
        entry = self.entries.popleft()
        self.emit('entry-removed', playlist=self, entry=entry)
        self.entries.rotate(-1 * rotDist)

        return entry

    async def get_next_entry(self, predownload_next=True):
        """
            A coroutine which will return the next song or None if no songs left to play.

            Additionally, if predownload_next is set to True, it will attempt to download the next
            song to be played - so that it's ready by the time we get to it.
        """
        if not self.entries:
            return None

        entry = self.entries.popleft()

        if predownload_next:
            next_entry = self.peek()
            if next_entry:
                next_entry.get_ready_future()

        try:
            return await entry.get_ready_future()
        except:
            return await self.get_next_entry(predownload_next)

    def peek(self):
        """
            Returns the next entry that should be scheduled to be played.
        """
        if self.entries:
            return self.entries[0]

    async def estimate_time_until(self, position, player):
        """
            (very) Roughly estimates the time till the queue will 'position'
        """
        estimated_time = sum(
            [e.end_seconds for e in islice(self.entries, position - 1)])

        if not player.is_stopped and player.current_entry:
            estimated_time += player.current_entry.duration - player.progress

        return datetime.timedelta(seconds=estimated_time)
