import asyncio

from discord import Embed, Message, TextChannel

from giesela import GieselaEntry, MusicPlayer, RadioSongEntry, RadioStationEntry, StreamEntry, \
    TimestampEntry, YoutubeEntry
from giesela.utils import (create_bar, ordinal, to_timestamp)
from .. import InteractableEmbed, IntervalUpdatingMessage, emoji_handler


class NowPlayingEmbed(IntervalUpdatingMessage, InteractableEmbed):
    """
    Keyword Args:
        seek_amount: Amount of seconds to forward/rewind
    """
    seek_amount: float
    player: MusicPlayer

    def __init__(self, channel: TextChannel, player: MusicPlayer, **kwargs):
        self.seek_amount = kwargs.pop("seek_amount", 30)
        super().__init__(channel, **kwargs)
        self.player = player

    async def get_embed(self) -> Embed:
        entry = self.player.current_entry

        if not entry:
            return Embed(description="Nothing playing")

        if isinstance(entry, RadioSongEntry):
            progress_ratio = entry.song_progress / \
                             (entry.song_duration or 1)
            desc = "{} `[{}/{}]`".format(
                create_bar(progress_ratio, length=20),
                to_timestamp(entry.song_progress),
                to_timestamp(entry.song_duration)
            )
            foot = "🔴 Live from {}".format(entry.station_name)

            em = Embed(
                title=entry.title,
                description=desc,
                url=entry.link,
                colour=0xa23dd1
            )

            em.set_footer(text=foot)
            em.set_thumbnail(url=entry.cover)
            em.set_author(
                name=entry.artist
            )
        elif isinstance(entry, RadioStationEntry):
            desc = "`{}`".format(
                to_timestamp(self.player.progress)
            )
            foot = "🔴 Live from {}".format(entry.station_name)

            em = Embed(
                title=entry.title,
                description=desc,
                url=entry.link,
                colour=0xbe7621
            )

            em.set_footer(text=foot)
            em.set_thumbnail(url=entry.cover)
        elif isinstance(entry, StreamEntry):
            desc = "🔴 Live [`{}`]".format(to_timestamp(self.player.progress))

            em = Embed(
                title=entry.title,
                description=desc,
                colour=0xa23dd1
            )
        elif isinstance(entry, GieselaEntry):
            artist_name = entry.artist
            artist_avatar = entry.artist_image
            progress_ratio = self.player.progress / entry.end_seconds
            desc = "{} `[{}/{}]`".format(
                create_bar(progress_ratio, length=20),
                to_timestamp(self.player.progress),
                to_timestamp(entry.end_seconds)
            )

            em = Embed(
                title=entry.song_title,
                description=desc,
                url=entry.url,
                colour=0xF9FF6E
            )

            em.set_thumbnail(url=entry.cover)
            em.set_author(
                name=artist_name,
                icon_url=artist_avatar
            )
            em.add_field(name="Album", value=entry.album)
        elif isinstance(entry, TimestampEntry):
            sub_entry = entry.current_sub_entry
            index = sub_entry["index"] + 1
            progress_ratio = sub_entry["progress"] / sub_entry["duration"]
            desc = "{} `[{}/{}]`".format(
                create_bar(progress_ratio, length=20),
                to_timestamp(sub_entry["progress"]),
                to_timestamp(sub_entry["duration"])
            )
            foot = "{}{} sub-entry of \"{}\" [{}/{}]".format(
                index,
                ordinal(index),
                entry.whole_title,
                to_timestamp(self.player.progress),
                to_timestamp(entry.end_seconds)
            )

            em = Embed(
                title=sub_entry["name"],
                description=desc,
                url=entry.url,
                colour=0x00FFFF
            )

            em.set_footer(text=foot)
            em.set_thumbnail(url=entry.thumbnail)
            if "playlist" in entry.meta:
                pl = entry.meta["playlist"]
                em.set_author(name=pl["name"], icon_url=pl.get("cover", None) or Embed.Empty)
            elif "author" in entry.meta:
                author = entry.meta["author"]
                em.set_author(
                    name=author.display_name,
                    icon_url=author.avatar_url
                )
        elif isinstance(entry, YoutubeEntry):
            progress_ratio = self.player.progress / entry.end_seconds
            desc = "{} `[{}/{}]`".format(
                create_bar(progress_ratio, length=20),
                to_timestamp(self.player.progress),
                to_timestamp(entry.end_seconds)
            )

            em = Embed(
                title=entry.title,
                description=desc,
                url=entry.url,
                colour=0xa9b244
            )

            em.set_thumbnail(url=entry.thumbnail)
            if "playlist" in entry.meta:
                pl = entry.meta["playlist"]
                em.set_author(name=pl["name"], icon_url=pl.get("cover", None) or Embed.Empty)
            elif "author" in entry.meta:
                author = entry.meta["author"]
                em.set_author(
                    name=author.display_name,
                    icon_url=author.avatar_url
                )
        else:
            em = Embed(description="No idea what you're playing")

        return em

    async def on_create_message(self, msg: Message):
        await super().add_reactions(msg)

    async def start(self):
        await super().start()
        await self.listen()

    @emoji_handler("⏮", pos=1)
    async def prev_entry(self, *_):
        self.player.queue.replay(0, revert=True)
        await self.trigger_update()

    @emoji_handler("⏪", pos=2)
    async def fast_rewind(self, *_):
        self.player.seek(self.player.progress - self.seek_amount)

    @emoji_handler("⏯", pos=3)
    async def play_pause(self, *_):
        if self.player.is_playing:
            self.player.pause()
        else:
            self.player.resume()

    @emoji_handler("⏩", pos=4)
    async def fast_forward(self, *_):
        self.player.seek(self.player.progress + self.seek_amount)

    @emoji_handler("⏭", pos=5)
    async def next_entry(self, *_):
        self.player.skip()

    async def slow_update(self):
        await asyncio.sleep(1)
        await self.trigger_update()

    async def on_any_emoji(self, *_):
        asyncio.ensure_future(self.slow_update())
