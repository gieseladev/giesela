from giesela.entry import Entry, GieselaEntry
from giesela.exceptions import ExtractionError, WrongEntryTypeError


def between(val, low, high):
    return high >= val >= low


async def _rebuild_entry(queue, entry):
    try:
        new_entry = await queue.get_entry(entry["url"], **entry.get("meta"))

        if entry["type"] == "GieselaEntry":
            print("[Entry-Fixer] \"{}\"({}) had GieselaEntry information in it, applying this information".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
            new_entry = GieselaEntry.upgrade(new_entry, entry["song_title"], entry["artist"], entry["artist_image"], entry["album"], entry["cover"])

        return new_entry
    except:
        return None


async def _fix_filename(queue, entry):
    try:
        new_info = await queue.get_ytdl_data(entry["url"])
        entry.update({
            "version": Entry.version,
            "expected_filename": queue.downloader.ytdl.prepare_filename(new_info)
        })

        return Entry.from_dict(queue, entry)
    except (ExtractionError, WrongEntryTypeError):
        return None


def _convert_spotify_to_giesela(queue, entry):
    video_id = entry.get("video_id")
    url = entry.get("url")
    title = entry.get("title")
    duration = entry.get("duration")
    thumbnail = entry.get("thumbnail")
    description = entry.get("description")
    song_title = entry.get("song_title")
    artist = entry.get("artist")
    artist_image = entry.get("artist_image")
    album = entry.get("album")
    cover = entry.get("cover")
    expected_filename = entry.get("expected_filename")
    meta = entry.get("meta")

    return GieselaEntry(queue, video_id, url, title, duration, thumbnail, description, song_title, artist, artist_image, album, cover, expected_filename=None, **meta).to_dict()


async def fix_entry(queue, entry):
    version = entry.get("version", 0)

    if version < 100:
        print("[Entry-Fixer] \"{}\"({}) is way too old, gotta rebuild completely!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
        return await _rebuild_entry(queue, entry)

    if entry.get("spotify_data", {}).get("id", None) == "custom":
        print("[Entry-Fixer] \"{}\"({}) is an old spotify entry, converting to the new GieselaEntry!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
        entry = _convert_spotify_to_giesela(queue, entry)

    if entry.get("broken"):
        print("[Entry-Fixer] \"{}\"({}) has been marked as broken, trying to recover".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
        try:
            data = await queue.downloader.extract_info(queue.loop, entry.get("url"), download=False)

            if (not data) or data.get("_type", None) == "playlist":
                print("[Entry-Fixer] \"{}\"({}) no data returned by youtube_dl... or it's a playlist".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
                return None

            entry["version"] = Entry.version
            entry.pop("broken", None)
            print("[Entry-Fixer] \"{}\"({}) got some data, creating the new entry!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
            return Entry.from_dict(queue, entry)
        except Exception:
            print("[Entry-Fixer] \"{}\"({}) something is wrong with this entry, youtube_dl raised an exception!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
            return None

    if not entry.get("expected_filename", False):
        print("[Entry-Fixer] \"{}\"({}) doesn't have \"expected_filename\" (needed for caching), fixing!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
        return await _fix_filename(queue, entry)

    try:
        print("[Entry-Fixer] \"{}\"({}) no idea what's wrong, setting to newest version, removing broken flag".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
        entry["version"] = Entry.version
        entry.pop("broken", None)
        return Entry.from_dict(queue, entry)
    except:
        try:
            print("[Entry-Fixer] \"{}\"({}) something went wrong with that, rebuilding!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
            return await _rebuild_entry(queue, entry)
        except:
            print("[Entry-Fixer] \"{}\"({}) rebuilding didn't work either... This entry is rip!".format(entry.get("title", "Unknown title")[:25], entry.get("url", "Unknown URL")))
            return None


async def fix_generator(queue, *entries):
    for ind, entry in enumerate(entries):
        yield ind, await fix_entry(queue, entry)
