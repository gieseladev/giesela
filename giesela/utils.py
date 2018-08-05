import re
import traceback
import urllib.parse
from difflib import SequenceMatcher
from io import BytesIO
from string import punctuation, whitespace

import aiohttp
import math
import requests
from PIL import Image, ImageStat
from bs4 import BeautifulSoup

from .config import ConfigDefaults, static_config


def wrap_string(target, wrapping, handle_special=True, reverse_closer=True):
    special_wrap = {
        "(": ")",
        "[": "]",
        "{": "}",
        "<": ">"
    } if handle_special else {}
    opener = wrapping
    closer = special_wrap.get(wrapping, wrapping)
    if reverse_closer:
        closer = closer[::-1]

    return "{}{}{}".format(opener, target, closer)


def create_cmd_params(params: dict):
    param_list = []
    for key, value in params.items():
        if value is not None:
            param_list.append("-{} {}".format(key, value))
        else:
            param_list.append("-{}".format(key))

    return " ".join(param_list)


def is_image(url):
    try:
        resp = requests.head(url, timeout=.5)
        if resp.headers.get("content-type") in ["image/jpeg", "image/png"]:
            return True
        return False
    except requests.exceptions.RequestException:
        return False


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def nice_cut(s, max_length, ending="..."):
    if len(s) <= max_length:
        return s

    parts = s.split()
    chunk = ""
    for part in parts:
        # if there's enough space to fit in EVERYTHING
        if len(chunk) + len(part) + len(ending) <= max_length:
            chunk += part + " "
        else:
            chunk = chunk.rstrip() + ending
            return chunk

    return chunk  # this really shouldn't happen...


def create_bar(progress, length=10, full_char="■", half_char=None, empty_char="□"):
    use_halves = half_char is not None
    fill_to = 2 * round(length * progress)
    residue = fill_to % 2
    chrs = []
    for i in range(1, length + 1):
        if i <= fill_to / 2:
            chrs.append(full_char)
        else:
            break

    if residue > 0 and use_halves:
        chrs.append(half_char)

    return ("{0:" + empty_char + "<" + str(length) + "}").format("".join(chrs))


def get_image_brightness(**kwargs):
    """
    Keyword Arguments:
    image       -- A Pillow Image object
    location    -- a file path to the image
    url         -- the online location of the image
    """
    if "image" in kwargs:
        im = kwargs["image"]
    elif "location" in kwargs:
        im = Image.open(kwargs["location"])
    elif "url" in kwargs:
        resp = requests.get(kwargs["url"])
        content = BytesIO(resp.content)
        im = Image.open(content)
    else:
        raise AttributeError("No image provided")

    stat = ImageStat.Stat(im)
    mean = stat.mean

    if len(mean) >= 3:
        r, g, b, *_ = mean
        return math.sqrt(0.241 * (r ** 2) + 0.691 * (g ** 2) + 0.068 * (b ** 2))
    elif len(mean) == 1:
        return mean[0]
    else:
        return 0


def ordinal(n, combine=False):
    """
    Return the ordinal of the number n.

    If combine then return the number concatenated with the ordinal
    """
    number_string = str(n) if combine else ""
    special_cases = {1: "st", 2: "nd", 3: "rd"}
    if not 10 <= n % 100 <= 20 and n % 10 in special_cases:
        return number_string + special_cases[n % 10]
    return number_string + "th"


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
            r"^[\s\->]*" + timestamp_match + r"\W+(.+?)$",
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


def get_video_timestamps(description, video_id, song_dur=None):
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
            "key": static_config.google_api_key,
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
                if song_dur:  # If we know the song duration I don't want ANY of those duckers to be out of bounds. That's the amount of distrust I have
                    for ts in songs.keys():
                        if ts > song_dur:
                            print(
                                "[TIMESTAMPS] Won't use comment-timestamps because at least one of them is totally out of bounds"
                            )
                            return None  # Yes **NONE**!
                return songs
    except:
        pass

    return None


def _choose_best_thumbnail(thumbnails):
    ranks = ["maxres", "high", "medium", "standard", "default"]
    for res in ranks:
        if res in thumbnails:
            return thumbnails[res]["url"]


def get_related_videos(video_id):
    params = {
        "part": "snippet",
        "relatedToVideoId": video_id,
        "topicId": "/m/04rlf",
        "type": "video",
        "key": static_config.google_api_key
    }
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search", params=params)
    data = resp.json()
    videos = data["items"]
    if not videos:
        return None
    video_list = []
    for vid in videos:
        video = {
            "id": vid["id"]["videoId"],
            "title": vid["snippet"]["title"],
            "channel": vid["snippet"]["channelTitle"],
            "thumbnail": _choose_best_thumbnail(vid["snippet"]["thumbnails"]),
            "url": "https://www.youtube.com/watch?v=" + vid["id"]["videoId"]
        }

        video_list.append(video)

    return video_list


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
        except:
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


def format_time_ffmpeg(s):
    total_msec = s * 1000
    total_seconds = s
    total_minutes = s / 60
    total_hours = s / 3600
    msec = int(total_msec % 1000)
    sec = int(total_seconds % 60 - (msec / 3600000))
    mins = int(total_minutes % 60 - (sec / 3600) - (msec / 3600000))
    hours = int(total_hours - (mins / 60) - (sec / 3600) - (msec / 3600000))

    return "{:02d}:{:02d}:{:02d}".format(hours, mins, sec)


def round_to_interval(num, interval=5):
    return int(interval * round(float(num) / interval))


def format_time(s, round_seconds=True, round_base=1, max_specifications=3, combine_with_and=False, replace_one=False, unit_length=2):
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


async def get_header(session, url, header_field=None, *, timeout=5):
    with aiohttp.ClientTimeout(timeout):
        async with session.head(url) as response:
            if header_field:
                return response.headers.get(header_field)
            else:
                return response.headers


def get_dev_version():
    page = requests.get(
        "https://raw.githubusercontent.com/GieselaDev/Giesela/dev/musicbot/constants.py"
    )
    matches = re.search(
        r"MAIN_VERSION = \"(\d+\.\d+\.\d+)\"\nSUB_VERSION = \"(.*?)\"",
        page.content.decode("utf-8"))

    if matches is None:
        return None, None

    return matches.groups()


def html2md(html):
    """Convert html to markdown.

    :param html: html text to convert.
    """
    html_to_markdown = [
        # HTML tag to Markdown
        (r"<code.+?>(.+?)<\/code>", r"`\1`"),  # code
        (r"<strong>(.+?)<\/strong>", r"**\1**"),  # bold
        (r"<a\shref=\"(.+?)\">(.+?)<\/a>", r"[`\2`](\1)"),  # links
        # that's all
    ]

    html = urllib.parse.unquote(html)

    for target, replacement in html_to_markdown:
        html = re.sub(target, replacement, html)

    return html


def get_version_changelog(version_code=None):
    version_code = version_code or get_dev_version()[0]
    if not version_code:
        return ["Changelog not available"]

    base_url = "https://gieseladev.github.io/Giesela/changelogs/changelog-"
    v_code = re.sub(r"\D", "", version_code)

    resp = requests.get(base_url + v_code)

    if not resp.ok:
        return ["Changelog not yet available"]

    changelog_page = resp.text

    bs = BeautifulSoup(changelog_page, ConfigDefaults.html_parser)
    html_to_markdown = [
        (r"<\/?li>", "\t"),  # indent list elements
        (r"<\/?ul>", ""),  # remove their wrapper

        # HTML tag to Markdown
        (r"<code.+?>(.+?)<\/code>", r"`\1`"),  # code
        (r"<strong>(.+?)<\/strong>", r"**\1**"),  # bold
        (r"<a\shref=\"(.+?)\">(.+?)<\/a>", r"[`\2`](\1)"),  # links
        # that's all

        (r"\n\W+\n", "\n")  # remove useless stuff between new lines
    ]

    changes = []

    try:
        for sib in (bs.body.li, *bs.body.li.next_siblings):
            line = str(sib).strip()
            for match, repl in html_to_markdown:
                line = re.sub(match, repl, line)

            line = line.strip()
            if line:
                changes.append(line)

        return changes
    except Exception:
        traceback.print_exc()
        return ["Couldn't find the changelog"]
