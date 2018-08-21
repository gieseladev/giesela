import asyncio
import functools
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, List, Optional, Tuple, Union

import youtube_dl
from youtube_dl.utils import ExtractorError

from .bot import Giesela
from .entry import BaseEntry, GieselaEntry, TimestampEntry, YoutubeEntry
from .exceptions import ExtractionError, WrongEntryTypeError
from .lib.api.VGMdb import get_entry as get_vgm_track
from .lib.api.discogs import get_entry as get_discogs_track
from .lib.api.spotify import get_spotify_track
from .utils import clean_songname, get_header, get_video_sub_queue

log = logging.getLogger(__name__)

ytdl_format_options = {
    "format": "bestaudio/best",
    "extractaudio": True,
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
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


class Downloader:

    def __init__(self, bot: Giesela, download_folder=None):
        self.bot = bot
        self.loop = bot.loop

        self.thread_pool = ThreadPoolExecutor(max_workers=2)
        self.unsafe_ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        self.safe_ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        self.safe_ytdl.params["ignoreerrors"] = True
        self.download_folder = download_folder

        if download_folder:
            otmpl = self.unsafe_ytdl.params["outtmpl"]
            self.unsafe_ytdl.params["outtmpl"] = os.path.join(download_folder, otmpl)

            otmpl = self.safe_ytdl.params["outtmpl"]
            self.safe_ytdl.params["outtmpl"] = os.path.join(download_folder, otmpl)

    @property
    def ytdl(self):
        return self.safe_ytdl

    async def extract_info(self, loop, *args, on_error=None, retry_on_error=False, **kwargs):
        """
            Runs ytdl.extract_info within the threadpool. Returns a future that will fire when it"s done.
            If `on_error` is passed and an exception is raised, the exception will be caught and passed to
            on_error as an argument.
        """
        if callable(on_error):
            try:
                return await loop.run_in_executor(self.thread_pool, functools.partial(self.unsafe_ytdl.extract_info, *args, **kwargs))

            except Exception as e:

                # (youtube_dl.utils.ExtractorError, youtube_dl.utils.DownloadError)
                # I hope I don"t have to deal with ContentTooShortErrors
                if asyncio.iscoroutinefunction(on_error):
                    asyncio.ensure_future(on_error(e), loop=loop)

                elif asyncio.iscoroutine(on_error):
                    asyncio.ensure_future(on_error, loop=loop)

                else:
                    loop.call_soon_threadsafe(on_error, e)

                if retry_on_error:
                    return await self.safe_extract_info(loop, *args, **kwargs)
        else:
            return await loop.run_in_executor(self.thread_pool, functools.partial(self.unsafe_ytdl.extract_info, *args, **kwargs))

    async def safe_extract_info(self, loop, *args, **kwargs):
        return await loop.run_in_executor(self.thread_pool, functools.partial(self.safe_ytdl.extract_info, *args, **kwargs))

    async def get_ytdl_data(self, song_url: str) -> dict:
        try:
            info = await self.extract_info(self.loop, song_url, download=False)
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

        filename = self.ytdl.prepare_filename(info)
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
            info = await self.extract_info(self.loop, query, download=False, process=False)
        except Exception as e:
            raise ExtractionError("Could not extract information from {}\n\n{}".format(query, e))

        if not info:
            raise ExtractionError("Couldn't extract info")

        if info.get("url", "").startswith("ytsearch"):
            info = await self.extract_info(
                self.loop,
                query,
                download=False,
                process=True,
                retry_on_error=True
            )

            if not info:
                raise ExtractorError("Couldn't extract info")

            if not info.get("entries", []):
                return None

            query = info["entries"][0]["webpage_url"]
            info = await self.extract_info(self.loop, query, download=False, process=False)

        if "entries" in info:
            return [entry["url"] for entry in info["entries"]]
        else:
            return await self.get_entry(info, **meta)

    async def get_entry_gen(self, url: str, **meta) -> AsyncIterator[Tuple[int, BaseEntry]]:
        info = await self.extract_info(self.loop, url, download=False, process=False)

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
