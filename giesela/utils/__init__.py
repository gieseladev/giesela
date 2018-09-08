import logging
import re
from difflib import SequenceMatcher
from string import punctuation, whitespace
from typing import Callable, Iterable, List, NamedTuple, Optional, Pattern, TYPE_CHECKING, Tuple, Union

import aiohttp
import requests

from .object_chain import *
from .scraper import *
from .structures import *
from .url import *

if TYPE_CHECKING:
    from giesela import BaseEntry

log = logging.getLogger(__name__)


async def content_is_image(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url) as resp:
            content_type = resp.headers["content-type"]
    except aiohttp.ClientError:
        return False

    return content_type.startswith("image/")


async def search_image(session: aiohttp.ClientSession, google_api_token: str, query: str, *, min_squareness: float = None, num_pages: int = 3) -> \
        Optional[str]:
    items_per_page = 10
    params = dict(key=google_api_token, cx="002017775112634544492:t0ynfpg8y0e", searchType="image", count=items_per_page,
                  fields="items(image)", q=query)

    for i in range(num_pages):
        params["start"] = i * items_per_page + 1

        async with session.get("https://www.googleapis.com/customsearch/v1", params=params) as resp:
            data = await resp.json()

        for item in data["items"]:
            image = item.get("image")
            if image:
                if min_squareness:
                    height = image["height"]
                    width = image["width"]
                    if min(height, width) / max(height, width) < min_squareness:
                        continue
                return image["thumbnailLink"]


def similarity(a: str, b: Union[str, Tuple[str, ...]], *, lower: bool = False, junk: Union[Callable[[str], bool], Iterable[str]] = None,
               auto_junk: bool = True) -> float:
    if isinstance(b, tuple):
        return max(similarity(a, _b, lower=lower, junk=junk, auto_junk=auto_junk) for _b in b if _b)

    if lower:
        a = a.lower()
        b = b.lower()

    if junk and not isinstance(junk, Callable):
        _junk = set(junk)

        def junk(s: str) -> bool: return s in _junk

    return SequenceMatcher(junk, a, b, autojunk=auto_junk).ratio()


class SplitSongName(NamedTuple):
    name: str
    artist: Optional[str]


RE_SPLIT_SONG_NAME_PATTERNS: List[Pattern] = [
    re.compile(r"(?P<name>.+)\b\s*by\b\s*(?P<artist>.+)"),
    re.compile(r"(?P<artist>.+)\b\s*[-|]\b\s*(?P<name>.+)")
]


def split_song_name(title: Union[str, "BaseEntry"]) -> SplitSongName:
    if not isinstance(title, str):
        title = getattr(title, "_title", False) or title.title

    for pattern in RE_SPLIT_SONG_NAME_PATTERNS:
        match = pattern.match(title)
        if match:
            return SplitSongName(*match.group("name", "artist"))

    return SplitSongName(title, None)


def clean_songname(query):
    """Clean a Youtube video title so it's shorter and easier to read."""
    to_remove = (
        "1080", "1080p", "4k", "720", "720p", "album", "amv", "audio", "avi", "creditless", "dvd",
        "edition", "eng", "english", "from", "full", "hd", "jap", "japanese", "lyrics", "mix",
        "mp3", "mp4", "musicvideo", "new", "nightcore", "official", "original",
        "original sound track", "original soundtrack", "ost", "raw", "size", "soundtrack",
        "special", "sub", "textless", "theme", "tv", "ver", "version", "video", "with lyrics",
        "youtube"
    )

    replacers = (
        # replace common indicators for the artist with a simple dash
        ((r"[\|:\/]", r"(^|\W)by(\W|$)"), " - "),
        # remove all parentheses and their content and remove "opening 5" stuff
        ((r"\(.*\)", r"(?:^|\b)op(?:ening)?(?:\s+\d{1,2})?(?:\b|$)"), " "),
        # replace several artist things with &
        ((r"(?:^|\b)(?:feat|ft)(?:\b|$)",), " & "),
        # replace w/ with with
        ((r"w\/",), "with")
    )

    special_regex = (
        # (r"\b([\w\s]{3,})\b(?=.*\1)", ""),
        # (r"\(f(?:ea)?t\.?\s?([\w\s\&\-\']{2,})\)", r" & \1"),
    )
    special_regex_after = (
        # rip w/
        (r"w\/", " "),
        # make sure that everything apart from [',] has space ("test -test"
        # converts to "test - test")
        # " -test"
        (r"(\s)([^\w\s\',])(\w)", r"\1 \2 \3"),
        # "- test"
        (r"(\w)([^\w\s\',])(\s)", r"\1 \2 \3"),
        # remove multiple non-words in a row like "test - - test"
        (r"[^\w\s]\s*[^\w\s]", " ")
    )

    for target, replacement in special_regex:
        query = re.sub(target, replacement, query, flags=re.IGNORECASE)

    for targets, replacement in replacers:
        for target in targets:
            query = re.sub(target, replacement, query, flags=re.IGNORECASE)

    for key in to_remove:
        # mainly using \W over \b because I want to match [HD] too
        query = re.sub(r"(^|\W)" + key + r"(\W|$)",
                       " ", query, flags=re.IGNORECASE)

    for target, replacement in special_regex_after:
        query = re.sub(target, replacement, query, flags=re.IGNORECASE)

    # remove everything apart from the few allowed characters
    query = re.sub(r"[^\w\s\-&\',]", " ", query)
    # remove unnecessary whitespaces
    query = re.sub(r"\s+", " ", query)

    no_capitalisation = ("a", "an", "and", "but", "for", "his",
                         "my", "nor", "of", "or", "s", "t", "the", "to", "your", "re", "my")

    # title everything except if it's already UPPER because then it's probably
    # by design. Also don't title no-title words (I guess) if they're not in
    # first place
    word_elements = []
    parts = re.split(r"(\W+)", query)
    for sub_ind, part in enumerate(parts):
        word_elements.append(part if (part.isupper() and len(part) > 2) or (
                part.lower() in no_capitalisation and sub_ind != 0) else part.title())

    query = "".join(word_elements)

    return query.strip(" -&,")


def timestamp_to_queue(timestamps, song_dur):
    queue = []
    entries = sorted(list(timestamps.keys()))
    for index, key in enumerate(entries):
        start = int(key)
        next_start = int(entries[index + 1]) if index + 1 < len(entries) else song_dur

        dur = next_start - start
        sub_entry = {
            "name": timestamps[key].strip(punctuation + whitespace),
            "duration": dur,
            "start": start,
            "index": index,
            "end": next_start
        }
        queue.append(sub_entry)

    return queue


def _run_timestamp_matcher(text):
    songs = {}

    timestamp_match = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\s?.?\s?(?:\d{1,2}:)?(?:\d{1,2}):(?:\d{2}))?"

    for match in re.finditer(
            r"^[^\w]*" + timestamp_match + r"\W+(.+?)$",
            text,
            flags=re.MULTILINE):
        timestamp = int(match.group(3))
        timestamp += (int(match.group(2)) * 60) if match.group(2) else 0
        timestamp += (int(match.group(1)) * 3600) if match.group(1) else 0
        songs[timestamp] = match.group(4).strip(punctuation + " ")

    if len(songs) < 1:
        for match in re.finditer(
                r"^(.+?)(?:at)?\s[(]?" + timestamp_match + r"[)]?$",
                text,
                flags=re.MULTILINE):
            timestamp = int(match.group(4))
            timestamp += (int(match.group(3)) * 60) if match.group(3) else 0
            timestamp += (int(match.group(2)) * 3600) if match.group(2) else 0
            songs[timestamp] = match.group(1).strip(punctuation + " ")

    if len(songs) > 0:
        return songs

    return None


def get_video_sub_queue(description, video_id, song_dur):
    timestamps = get_video_timestamps(description, video_id, song_dur)
    if not timestamps:
        return None

    return timestamp_to_queue(timestamps, song_dur)


def get_video_timestamps(google_api_token: str, description, video_id, song_dur=None):
    if song_dur:
        song_dur += 5  # I'm not that harsh, one second more or less ain't that bad

    if description:
        songs = _run_timestamp_matcher(description)

        if songs is not None:
            # probably for the best to trust the description. Even if not all
            # of them are as reliable as they should be.
            return songs

    if not video_id:
        return None

    try:
        if song_dur and song_dur < 200:  # I don't trust comments when the song is only about 3 mins loading
            return None

        params = {
            "key": google_api_token,
            "part": "snippet",
            "order": "relevance",
            "textFormat": "plainText",
            "videoId": video_id
        }
        resp = requests.get("https://www.googleapis.com/youtube/v3/commentThreads", params=params)
        data = resp.json()
        for comment in data["items"]:
            songs = _run_timestamp_matcher(comment["snippet"]["topLevelComment"]["snippet"]["textDisplay"])
            if songs is not None and len(songs) > 2:
                # If we know the song duration I don't want ANY of those duckers to be out of bounds. That's the amount of distrust I have
                if song_dur:
                    for ts in songs.keys():
                        if ts > song_dur:
                            print(
                                "[TIMESTAMPS] Won't use comment-timestamps because at least one of them is totally out of bounds"
                            )
                            return None  # Yes **NONE**!
                return songs
    except Exception:
        pass

    return None


def parse_timestamp(timestamp):
    parts = timestamp.split(":")
    if len(parts) < 1:  # Shouldn't occur, but who knows?
        return None

    values = (
        1,  # seconds
        60,  # minutes
        60 * 60,  # hours
        60 * 60 * 24  # days
    )

    secs = 0
    for i in range(len(parts)):
        try:
            v = int(parts[i])
        except Exception:
            continue

        j = len(parts) - i - 1
        if j >= len(values):  # Can't convert
            continue
        secs += v * values[j]

    return secs


def to_timestamp(seconds):
    sec = int(seconds)
    s = "{0:0>2}".format(sec % 60)
    m = (sec // 60) % 60
    h = (sec // 60 // 60) % 24
    d = (sec // 60 // 60 // 24)

    if d > 0:
        return ":".join(
            str(x) for x in (d, "{0:0>2}".format(h), "{0:0>2}".format(m), s))
    elif h > 0:
        return ":".join(str(x) for x in (h, "{0:0>2}".format(m), s))
    else:
        return ":".join(str(x) for x in (m, s))


def round_to_interval(num, interval=5):
    return int(interval * round(float(num) / interval))


def format_time(s, round_seconds=True, round_base=1, max_specifications=2, combine_with_and=False, replace_one=False, unit_length=2):
    if round_seconds:
        s = round_to_interval(s, round_base)

    minutes, seconds = divmod(s, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    return_list = []
    if days > 0:
        return_list.append(
            "{} {}{}".format("a" if days == 1 and replace_one else days, ["d", "day", "day"][unit_length],
                             "s" if days is not 1 and unit_length != 0 else ""))
    if hours > 0:
        return_list.append(
            "{} {}{}".format("an" if hours == 1 and replace_one else hours, ["h", "hr", "hour"][unit_length],
                             "s" if hours is not 1 and unit_length != 0 else ""))
    if minutes > 0:
        return_list.append(
            "{} {}{}".format("a" if minutes == 1 and replace_one else
                             minutes, ["m", "min", "minute"][unit_length], "s" if minutes is not 1 and unit_length != 0 else ""))
    if seconds > 0 or s is 0:
        return_list.append(
            "{} {}{}".format("a" if seconds == 1 and replace_one else
                             seconds, ["s", "sec", "second"][unit_length], "s" if seconds is not 1 and unit_length != 0 else ""))

    if max_specifications is not None:
        return_list = return_list[:max_specifications]

    if combine_with_and and len(return_list) > 1:
        return_list.insert(-1, "and")

    return " ".join(return_list)
