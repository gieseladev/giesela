from musicbot.entry import Entry


def between(val, low, high):
    return high >= val >= low

async def _rebuild_entry(queue, entry):
    return await get_entry(entry.url, **entry.meta)

async def _fix_filename(queue, entry):
    new_info = await queue.get_ytdl_data(entry["url"])
    entry.update({
        "version": Entry.version,
        "expected_filename": queue.downloader.ytdl.prepare_filename(new_info)
    })

    return Entry.from_dict(queue, entry)

async def fix_entry(queue, entry):
    version = entry.get("version", 0)

    if version < 100:
        return await _rebuild_entry(queue, entry)

    if between(version, 100, 101) and "expected_filename" not in entry:
        return await _fix_filename(queue, entry)

async def fix_generator(queue, *entries):
    for ind, entry in enumerate(entries):
        yield ind, await fix_entry(queue, entry)
