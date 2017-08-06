from musicbot.entry import Entry, GieselaEntry

from .exceptions import ExtractionError, WrongEntryTypeError


def between(val, low, high):
    return high >= val >= low

async def _rebuild_entry(queue, entry):
    try:
        return await get_entry(entry.url, **entry.meta)
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
        return await _rebuild_entry(queue, entry)

    if entry.get("spotify_data", {}).get("id", None) == "custom":
        entry = _convert_spotify_to_giesela(queue, entry)

    if not entry.get("expected_filename", False):
        return await _fix_filename(queue, entry)

    try:
        entry["version"] = Entry.version
        entry.pop("broken", None)
        return Entry.from_dict(queue, entry)
    except:
        try:
            return await _rebuild_entry(queue, entry)
        except:
            return None

async def fix_generator(queue, *entries):
    for ind, entry in enumerate(entries):
        yield ind, await fix_entry(queue, entry)
