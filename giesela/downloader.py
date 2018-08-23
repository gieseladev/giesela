import asyncio
import functools
import logging
import os
import re
import urllib
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, List, Optional, Pattern, Tuple, Union
from urllib.parse import urlparse

import youtube_dl
from youtube_dl.utils import DownloadError, ExtractorError, UnsupportedError

from .bot import Giesela
from .entry import BaseEntry, GieselaEntry, StreamEntry, TimestampEntry, YoutubeEntry
from .exceptions import ExtractionError, WrongEntryTypeError
from .lib.api.VGMdb import get_entry as get_vgm_track
from .lib.api.discogs import get_entry as get_discogs_track
from .lib.api.spotify import get_spotify_track
from .utils import clean_songname, get_header, get_video_sub_queue

log = logging.getLogger(__name__)

ytdl_format_options = {
    "format": "bestaudio/best",
    "extractaudio": True,
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "geo_bypass": True
}

youtube_dl.utils.bug_reports_message = lambda: ""

_RE_RM_UNWANTED: Pattern = re.compile(r"[^a-z0-9]")
_RE_RM_HOST_PARTS: Pattern = re.compile(r"(\.\w{2,3}$)|(^www\.)")

RE_RM_UNWANTED = functools.partial(_RE_RM_UNWANTED.sub, "_")
RE_RM_HOST_PARTS = functools.partial(_RE_RM_HOST_PARTS.sub, "")


class Downloader:

    def __init__(self, bot: Giesela, download_folder=None):
        self.bot = bot
        self.loop = bot.loop

        self.thread_pool = ThreadPoolExecutor(max_workers=2)

        self.unsafe_ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        self.safe_ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        self.safe_ytdl.params["ignoreerrors"] = True

        self._patch_ytdl(self.unsafe_ytdl, self.safe_ytdl)

        self.download_folder = download_folder

    @property
    def ytdl(self):
        return self.safe_ytdl

    def _patch_ytdl(self, *ytdls: youtube_dl.YoutubeDL):
        for ytdl in ytdls:
            ytdl.prepare_filename = self.prepare_filename

    def prepare_filename(self, url: Union[dict, str]) -> str:
        if isinstance(url, dict):
            url = url["webpage_url"]
        parsed = urlparse(url)
        host = RE_RM_UNWANTED(RE_RM_HOST_PARTS(parsed.hostname.lower()))
        path = RE_RM_UNWANTED(parsed.path)
        query = RE_RM_UNWANTED(parsed.query)

        return os.path.join(self.download_folder, f"{host}-{path}-{query}.audio")

    async def extract_info(self, *args, on_error=None, filename: str = None, **kwargs):
        """
            Runs ytdl.extract_info within the threadpool. Returns a future that will fire when it"s done.
            If `on_error` is passed and an exception is raised, the exception will be caught and passed to
            on_error as an argument.
        """
        kwargs["download"] = bool(filename)
        try:
            return await self.loop.run_in_executor(self.thread_pool, functools.partial(self.unsafe_ytdl.extract_info, *args, **kwargs))
        except Exception as e:
            if not on_error:
                raise

            if asyncio.iscoroutinefunction(on_error):
                asyncio.ensure_future(on_error(e), loop=self.loop)

            elif asyncio.iscoroutine(on_error):
                asyncio.ensure_future(on_error, loop=self.loop)

            else:
                self.loop.call_soon_threadsafe(on_error, e)

    async def get_ytdl_data(self, song_url: str) -> dict:
        try:
            info = await self.extract_info(song_url)
        except Exception as e:
            raise ExtractionError(
                "Could not extract information from {}\n\n{}".format(song_url, e))

        if not info:
            raise ExtractionError(
                "Could not extract information from %s" % song_url)

        if info.get("_type", None) == "playlist":
            raise WrongEntryTypeError("This is a playlist.", True, info.get(
                "webpage_url", None) or info.get("url", None))

        if info["extractor"] in ["generic", "Dropbox"]:
            try:
                content_type = await get_header(self.bot.aiosession, info["url"], "CONTENT-TYPE")
                print("Got content type", content_type)

            except Exception as e:
                print("[Warning] Failed to get content type for url %s (%s)" % (
                    song_url, e))
                content_type = None

            if content_type:
                if content_type.startswith(("application/", "image/")):
                    if "/ogg" not in content_type:  # How does a server say `application/ogg` what the actual fuck
                        raise ExtractionError(
                            "Invalid content type \"%s\" for url %s" % (content_type, song_url))

                elif not content_type.startswith(("audio/", "video/")):
                    print("[Warning] Questionable content type \"%s\" for url %s" % (
                        content_type, song_url))

        return info

    async def get_stream_entry(self, stream_url: str, **meta) -> BaseEntry:
        info = {"title": stream_url, "url": stream_url}

        try:
            info = await self.extract_info(stream_url)

        except DownloadError as e:
            if e.exc_info[0] == UnsupportedError:
                print("[STREAM] Assuming content is a direct stream")

            elif e.exc_info[0] == urllib.error.URLError:
                if os.path.exists(os.path.abspath(stream_url)):
                    raise ExtractionError("This is not a stream, this is a file path.")

                else:  # it might be a file path that just doesn't exist
                    raise ExtractionError("Invalid input: {0.exc_info[0]}: {0.exc_info[1].reason}".format(e))

            else:
                raise ExtractionError("Unknown error: {}".format(e))

        except Exception as e:
            print("Could not extract information from {} ({}), falling back to direct".format(stream_url, e))

        if info.get("extractor") == "twitch:stream":
            title = info.get("description")
        else:
            title = info.get("title", "Untitled Stream")

        entry = StreamEntry(info["url"], title=title, **meta)
        return entry

    async def get_entry(self, song_url: Union[str, dict], **meta) -> BaseEntry:
        if isinstance(song_url, dict):
            info = song_url
        else:
            info = await self.get_ytdl_data(song_url)

        video_id = info.get("id")
        video_title = info.get("title")
        video_description = info.get("description")
        video_thumbnail = info.get("thumbnail")
        video_url = info.get("webpage_url")
        video_duration = info.get("duration", 0)

        clean_title = clean_songname(video_title) or video_title

        filename = self.prepare_filename(video_url)
        args = (filename, video_url, video_duration)
        kwargs = dict(video_id=video_id, title=video_title, thumbnail=video_thumbnail)
        kwargs.update(meta)

        spotify_searcher = asyncio.ensure_future(get_spotify_track(self.loop, clean_title))
        vgm_searcher = asyncio.ensure_future(get_vgm_track(self.loop, clean_title))
        discogs_searcher = asyncio.ensure_future(get_discogs_track(self.loop, clean_title))

        track = None

        pending = (spotify_searcher, vgm_searcher, discogs_searcher)

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED, timeout=3)
            done = next(iter(done), None)
            if not done:
                break

            result = done.result()
            if not result:
                continue
            track = result
            break

        if track:
            kwargs.update(track)
            entry = GieselaEntry(*args, **kwargs)
        else:
            sub_queue = get_video_sub_queue(video_description, video_id, video_duration)

            if sub_queue:
                entry = TimestampEntry(*args, sub_queue=sub_queue, **kwargs)
            else:
                entry = YoutubeEntry(*args, **kwargs)

        return entry

    async def get_entry_from_query(self, query: str, **meta) -> Optional[Union[BaseEntry, List[str]]]:
        try:
            info = await self.extract_info(query, process=False)
        except Exception as e:
            raise ExtractionError("Could not extract information from {}\n\n{}".format(query, e))

        if not info:
            raise ExtractionError("Couldn't extract info")

        if info.get("url", "").startswith("ytsearch"):
            info = await self.extract_info(query, process=True)

            if not info:
                raise ExtractorError("Couldn't extract info")

            if not info.get("entries", []):
                return None

            query = info["entries"][0]["webpage_url"]
            info = await self.extract_info(query, process=False)

        if "entries" in info:
            return [entry["url"] for entry in info["entries"]]
        else:
            return await self.get_entry(info, **meta)

    async def get_entry_gen(self, url: str, **meta) -> AsyncIterator[Tuple[int, BaseEntry]]:
        info = await self.extract_info(url, process=False)

        if "entries" in info:
            return self.get_entries_from_urls_gen(*[entry["url"] for entry in info["entries"]])
        else:
            async def _tuple_gen_creator(collection):
                for i, el in enumerate(collection):
                    yield i, el

            return _tuple_gen_creator([await self.get_entry(info, **meta)])

    async def get_entries_from_urls_gen(self, *urls: str, **meta) -> AsyncIterator[Tuple[int, BaseEntry]]:
        for ind, url in enumerate(urls):
            try:
                entry = await self.get_entry(url, **meta)
            except (ExtractionError, WrongEntryTypeError) as e:
                print("Error while dealing with url \"{}\":\n{}".format(url, e))
                yield ind, None
                continue

            yield ind, entry
