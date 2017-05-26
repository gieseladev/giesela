import datetime
import decimal
import random
import re
import unicodedata
from datetime import timedelta
from hashlib import md5

import aiohttp
import requests
from bs4 import BeautifulSoup

from .constants import DISCORD_MSG_CHAR_LIMIT


def load_file(filename, skip_commented_lines=True, comment_char='#'):
    try:
        with open(filename, encoding='utf8') as f:
            results = []
            for line in f:
                line = line.strip()

                if line and not (skip_commented_lines and line.startswith(comment_char)):
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

    return ("***REMOVED***0:" + empty_char + "<" + str(length) + "***REMOVED***").format("".join(chrs))


def prettydate(d):
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days > 7 or diff.days < 0:
        return d.strftime('%d %b %y')
    elif diff.days == 1:
        return '1 day ago'
    elif diff.days > 1:
        return '***REMOVED******REMOVED*** days ago'.format(diff.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '***REMOVED******REMOVED*** seconds ago'.format(round_to_interval(s))
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '***REMOVED******REMOVED*** minutes ago'.format(round_to_interval(s / 60))
    elif s < 7200:
        return '1 hour ago'
    else:
        return '***REMOVED******REMOVED*** hours ago'.format(round_to_interval(s / 3600))


def ordinal(n):
    special_cases = ***REMOVED***1: "st", 2: "nd", 3: "rd"***REMOVED***
    if not 10 <= n % 100 <= 20 and n % 10 in special_cases:
        return special_cases[n % 10]
    return "th"


def _run_timestamp_matcher(text):
    songs = ***REMOVED******REMOVED***
    for match in re.finditer(r"(?:(\d***REMOVED***1,2***REMOVED***):)?(\d***REMOVED***1,2***REMOVED***):(\d***REMOVED***2***REMOVED***)(?:\s?.?\s?(?:\d***REMOVED***1,2***REMOVED***:)?(?:\d***REMOVED***1,2***REMOVED***):(?:\d***REMOVED***2***REMOVED***))?\W+(.+?)(?:\n|$)", text):
        timestamp = int(match.group(3))
        timestamp += (int(match.group(2)) *
                      60) if match.group(2) is not None else 0
        timestamp += (int(match.group(1)) *
                      3600) if match.group(1) is not None else 0
        songs[timestamp] = match.group(4)

    if len(songs) > 0:
        return songs

    return None


def get_video_timestamps(url):
    try:
        desc = get_video_description(url)
    except:
        desc = None

    if desc is not None:
        songs = _run_timestamp_matcher(desc)

        if songs is not None:
            return songs

    video_id = re.match(
        r"(?:(?:https?:\/\/)(?:www)?\.?(?:youtu\.?be)(?:\.com)?\/(?:.*[=/])*)([^= &?/\r\n]***REMOVED***8,11***REMOVED***)", url).group(1)
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/commentThreads?key=AIzaSyCvvKzdz-bVJUUyIzKMAYmHZ0FKVLGSJlo&part=snippet&order=relevance&textFormat=plainText&videoId=" + video_id)
    data = resp.json()
    for comment in data["items"]:
        songs = _run_timestamp_matcher(
            comment["snippet"]["topLevelComment"]["snippet"]["textDisplay"])
        if songs is not None and len(songs) > 1:
            return songs

    return None


def get_video_description(url):
    resp = requests.get(url)
    bs = BeautifulSoup(resp.text, "lxml")
    bs = bs.find("p", attrs=***REMOVED***"id": "eow-description"***REMOVED***)
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
        if j >= len(values):  # If I don't have a conversion from this to seconds
            continue
        secs += v * values[j]

    return secs


def hex_to_dec(hex_code):
    return int(hex_code, 16)


def to_timestamp(seconds):
    sec = int(seconds)
    s = "***REMOVED***0:0>2***REMOVED***".format(sec % 60)
    m = (sec // 60) % 60
    h = (sec // 60 // 60) % 24
    d = (sec // 60 // 60 // 24)

    work_string = ""
    if d > 0:
        return ":".join(str(x) for x in (d, "***REMOVED***0:0>2***REMOVED***".format(h), "***REMOVED***0:0>2***REMOVED***".format(m), s))
    elif h > 0:
        return ":".join(str(x) for x in (h, "***REMOVED***0:0>2***REMOVED***".format(m), s))
    else:
        return ":".join(str(x) for x in (m, s))


def slugify(value):
    value = unicodedata.normalize('NFKD', value).encode(
        'ascii', 'ignore').decode('ascii')
    value = re.sub('[^\w\s-]', '', value).strip().lower()
    return re.sub('[-\s]+', '-', value)


def sane_round_int(x):
    return int(decimal.Decimal(x).quantize(1, rounding=decimal.ROUND_HALF_UP))


def format_time_ffmpeg(s):
    total_msec = s * 1000
    total_seconds = s
    total_minutes = s / 60
    total_hours = s / 3600
    msec = int(total_msec % 1000)
    sec = int(total_seconds % 60 - (msec / 3600000))
    mins = int(total_minutes % 60 - (sec / 3600) - (msec / 3600000))
    hours = int(total_hours - (mins / 60) - (sec / 3600) - (msec / 3600000))

    return "***REMOVED***:02d***REMOVED***:***REMOVED***:02d***REMOVED***:***REMOVED***:02d***REMOVED***".format(hours, mins, sec)


def round_to_interval(num, interval=5):
    return int(interval * round(float(num) / interval))


def format_time(s, round_seconds=False, round_base=5, max_specifications=None, combine_with_and=False, replace_one=False):
    if round_seconds:
        s = round_to_interval(s, round_base)

    minutes, seconds = divmod(s, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    return_list = []
    if days > 0:
        return_list.append("***REMOVED******REMOVED*** day***REMOVED******REMOVED***".format(
            "a" if days == 1 and replace_one else days, "s" if days is not 1 else ""))
    if hours > 0:
        return_list.append("***REMOVED******REMOVED*** hour***REMOVED******REMOVED***".format(
            "an" if hours == 1 and replace_one else hours, "s" if hours is not 1 else ""))
    if minutes > 0:
        return_list.append("***REMOVED******REMOVED*** minute***REMOVED******REMOVED***".format(
            "a" if minutes == 1 and replace_one else minutes, "s" if minutes is not 1 else ""))
    if seconds > 0 or s is 0:
        return_list.append("***REMOVED******REMOVED*** second***REMOVED******REMOVED***".format(
            "a" if seconds == 1 and replace_one else seconds, "s" if seconds is not 1 else ""))

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
            currentchunk = ''

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
