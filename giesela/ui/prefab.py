from discord import Colour, Embed

from giesela import utils
from giesela.entry import BaseEntry, CanWrapEntryType, EntryWrapper, PlayableEntry, RadioEntry


def get_entry_embed(entry: CanWrapEntryType):
    if isinstance(entry, EntryWrapper):
        entry = entry.entry
    elif isinstance(entry, (PlayableEntry, BaseEntry)):
        entry = entry
    else:
        raise TypeError(f"Can't build embed for {entry}")

    if not isinstance(entry, BaseEntry):
        return Embed(title=str(entry), colour=Colour.dark_green())

    em = Embed(title=entry.title, colour=Colour.greyple())

    if entry.artist or entry.artist_image:
        em.set_author(name=entry.artist or "Unknown Artist", icon_url=entry.artist_image or Embed.Empty)

    if entry.cover:
        em.set_thumbnail(url=entry.cover)

    if entry.album:
        em.add_field(name="Album", value=entry.album)

    duration = getattr(entry, "duration", None)
    if duration is not None:
        em.add_field(name="Duration", value=utils.format_time(duration))

    if isinstance(entry, RadioEntry):
        em.set_footer(text=entry.station.name, icon_url=entry.station.logo or Embed.Empty)

    return em
