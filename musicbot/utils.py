import decimal
import random
import re
import unicodedata
from hashlib import md5

import aiohttp

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


def slugify(value):
    value = unicodedata.normalize('NFKD', value).encode(
        'ascii', 'ignore').decode('ascii')
    value = re.sub('[^\w\s-]', '', value).strip().lower()
    return re.sub('[-\s]+', '-', value)


def sane_round_int(x):
    return int(decimal.Decimal(x).quantize(1, rounding=decimal.ROUND_HALF_UP))


def round_to_interval(num, interval=5):
    return int(interval * round(float(num) / interval))


def format_time(s, round_seconds=False, round_base=5, max_specifications=None):
    if round_seconds:
        s = round_to_interval(s, round_base)

    minutes, seconds = divmod(s, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    return_list = []
    if days > 0:
        return_list.append("{} day{}".format(
            days, "s" if days is not 1 else ""))
    if hours > 0:
        return_list.append("{} hour{}".format(
            hours, "s" if hours is not 1 else ""))
    if minutes > 0:
        return_list.append("{} minute{}".format(
            minutes, "s" if minutes is not 1 else ""))
    if seconds > 0 or s is 0:
        return_list.append("{} second{}".format(
            seconds, "s" if seconds is not 1 else ""))

    if max_specifications is not None:
        return_list = return_list[:max_specifications]

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
