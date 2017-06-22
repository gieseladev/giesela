import datetime
import decimal
import random
import re
import unicodedata
from datetime import timedelta
from difflib import SequenceMatcher
from hashlib import md5

import aiohttp
import requests
from bs4 import BeautifulSoup

from .constants import DISCORD_MSG_CHAR_LIMIT


def similarity(a, b):
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


def load_file(filename, skip_commented_lines=True, comment_char='#'):
    try:
        with open(filename, encoding='utf8') as f:
            results = []
            for line in f:
                line = line.strip()

                if line and not (skip_commented_lines and
                                 line.startswith(comment_char)):
                    results.append(line)

            return results

    except IOError as e:
        print("Error loading", filename, e)
        return []


def write_file(filename, contents):
    with open(filename, 'w', encoding='utf8') as f:
        for item in contents:
            f.write(str(item))
            f.write('\n')


def create_bar(progress, length=10, full_char="■", half_char=None, empty_char="□"):
    use_halves = half_char is not None
    fill_to = int(2 * length * progress)
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


def prettydate(d):
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days > 7 or diff.days < 0:
        return d.strftime('%d %b %y')
    elif diff.days == 1:
        return '1 day ago'
    elif diff.days > 1:
        return '{} days ago'.format(diff.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '{} seconds ago'.format(round_to_interval(s))
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '{} minutes ago'.format(round_to_interval(s / 60))
    elif s < 7200:
        return '1 hour ago'
    else:
        return '{} hours ago'.format(round_to_interval(s / 3600))


def ordinal(n):
    special_cases = {1: "st", 2: "nd", 3: "rd"}
    if not 10 <= n % 100 <= 20 and n % 10 in special_cases:
        return special_cases[n % 10]
    return "th"


def clean_songname(query):
    to_remove = [
        "ost", "original sound track", "original soundtrack", "from",
        "with lyrics", "lyrics", "hd", "soundtrack", "original", "official",
        "feat", "ft", "creditless", "music", "video", "edition", "special",
        "version", "ver", "dvd", "new", "raw", "textless", "mp3", "avi", "mp4",
        "english", "eng", "with", "album", "theme", "full"
    ]

    for key in to_remove:
        # mainly using \W over \b because I want to match [HD] too
        query = re.sub(r"(^|\W)" + key + r"(\W|$)",
                       " ", query, flags=re.IGNORECASE)

    query = re.sub(r"[^\w\s\-\&']|\d", " ", query)
    query = re.sub(r"\s+", " ", query)

    return query.strip()


def _run_timestamp_matcher(text):
    songs = {}
    for match in re.finditer(
            r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\s?.?\s?(?:\d{1,2}:)?(?:\d{1,2}):(?:\d{2}))?\W+(.+?)$",
            text,
            flags=re.MULTILINE):
        timestamp = int(match.group(3))
        timestamp += (
            int(match.group(2)) * 60) if match.group(2) is not None else 0
        timestamp += (
            int(match.group(1)) * 3600) if match.group(1) is not None else 0
        songs[timestamp] = match.group(4)

    if len(songs) < 1:
        for match in re.finditer(
                r"^(.+)\s[\(]?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\s?.?\s?(?:\d{1,2}:)?(?:\d{1,2}):(?:\d{2}))?[\)]?$",
                text,
                flags=re.MULTILINE):
            timestamp = int(match.group(4))
            timestamp += (
                int(match.group(3)) * 60) if match.group(3) is not None else 0
            timestamp += (int(match.group(2)) *
                          3600) if match.group(2) is not None else 0
            songs[timestamp] = match.group(1)

    if len(songs) > 0:
        return songs

    return None


def get_video_timestamps(url, song_dur=None):
    if song_dur:
        song_dur += 5  # I'm not that harsh, one second more or less ain't that bad

    try:
        desc = get_video_description(url)
    except:
        desc = None

    if desc is not None:
        songs = _run_timestamp_matcher(desc)

        if songs is not None:
            return songs

    try:
        if song_dur and song_dur < 200:  # I don't trust comments when the song is only about 3 mins loading
            return None

        video_id = re.match(
            r"(?:(?:https?:\/\/)(?:www)?\.?(?:youtu\.?be)(?:\.com)?\/(?:.*[=/])*)([^= &?/\r\n]{8,11})",
            url).group(1)
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/commentThreads?key=AIzaSyCvvKzdz-bVJUUyIzKMAYmHZ0FKVLGSJlo&part=snippet&order=relevance&textFormat=plainText&videoId="
            + video_id)
        data = resp.json()
        for comment in data["items"]:
            songs = _run_timestamp_matcher(comment["snippet"][
                "topLevelComment"]["snippet"]["textDisplay"])
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


def get_video_description(url):
    resp = requests.get(url)
    bs = BeautifulSoup(resp.text, "lxml")
    bs = bs.find("p", attrs={"id": "eow-description"})
    for br in bs.find_all("br"):
        br.replace_with("\n")
    return bs.text


def parse_timestamp(timestamp):
    parts = timestamp.split(":")
    if len(parts) < 1:  # Shouldn't occur, but who knows?
        return None

    # seconds, minutes, hours, days
    values = (1, 60, 60 * 60, 60 * 60 * 24)

    secs = 0
    for i in range(len(parts)):
        try:
            v = int(parts[i])
        except:
            continue

        j = len(parts) - i - 1
        if j >= len(
                values):  # If I don't have a conversion from this to seconds
            continue
        secs += v * values[j]

    return secs


def hex_to_dec(hex_code):
    return int(hex_code.lstrip("#"), 16)


def to_timestamp(seconds):
    sec = int(seconds)
    s = "{0:0>2}".format(sec % 60)
    m = (sec // 60) % 60
    h = (sec // 60 // 60) % 24
    d = (sec // 60 // 60 // 24)

    work_string = ""
    if d > 0:
        return ":".join(
            str(x) for x in (d, "{0:0>2}".format(h), "{0:0>2}".format(m), s))
    elif h > 0:
        return ":".join(str(x) for x in (h, "{0:0>2}".format(m), s))
    else:
        return ":".join(str(x) for x in (m, s))


def slugify(value):
    value = unicodedata.normalize('NFKD', value).encode(
        'ascii', 'ignore').decode('ascii')
    value = re.sub('[^\w\s-]', '', value).strip().lower()
    return re.sub('[-\s]+', '-', value)


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


def format_time(s,
                round_seconds=True,
                round_base=1,
                max_specifications=3,
                combine_with_and=False,
                replace_one=False,
                unit_length=2):
    if round_seconds:
        s = round_to_interval(s, round_base)

    minutes, seconds = divmod(s, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    return_list = []
    if days > 0:
        return_list.append(
            "{} {}{}".format("a" if days == 1 and replace_one else days, ["d", "day", "day"][unit_length], "s"
                             if days is not 1 and unit_length != 0 else ""))
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


def escape_dis(s):
    escape_char = "\\"
    escape_list = ["_", "*"]
    for c in escape_list:
        s = re.sub(re.escape(c), escape_char + c, s)

    return s


def random_line(afile):
    with open(afile) as myfile:
        line = next(myfile)
        for num, aline in enumerate(myfile):
            if random.randrange(num + 2):
                continue
            line = aline
        return line


def paginate(content, *, length=DISCORD_MSG_CHAR_LIMIT, reserve=0):
    """
    Split up a large string or list of strings into chunks for sending to discord.
    """
    if type(content) == str:
        contentlist = content.split('\n')
    elif type(content) == list:
        contentlist = content
    else:
        raise ValueError("Content must be str or list, not %s" % type(content))

    chunks = []
    currentchunk = ''

    for line in contentlist:
        if len(currentchunk) + len(line) < length - reserve:
            currentchunk += line + '\n'
        else:
            chunks.append(currentchunk)
            currentchunk = line + "\n"

    if currentchunk:
        chunks.append(currentchunk)

    return chunks


async def get_header(session, url, headerfield=None, *, timeout=5):
    with aiohttp.Timeout(timeout):
        async with session.head(url) as response:
            if headerfield:
                return response.headers.get(headerfield)
            else:
                return response.headers


def md5sum(filename, limit=0):
    fhash = md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            fhash.update(chunk)
    return fhash.hexdigest()[-limit:]
