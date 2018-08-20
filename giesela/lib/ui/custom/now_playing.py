import asyncio

from discord import Embed, Message, TextChannel

from giesela import GieselaEntry, MusicPlayer, RadioSongEntry, RadioStationEntry, StreamEntry, \
    TimestampEntry, YoutubeEntry
from giesela.lib.ui import create_player_bar
from giesela.utils import (ordinal, to_timestamp)
from .. import InteractableEmbed, IntervalUpdatingMessage, emoji_handler


def create_progress_bar(progress: float, duration: float) -> str:
    progress_ratio = progress / duration
    progress_bar = create_player_bar(progress_ratio, 20)
    return progress_bar


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

    def get_stream_entry_embed(self, entry: StreamEntry) -> Embed:
        desc = f"🔴 Live [`{to_timestamp(self.player.progress)}`]"
        footer = {}
        cover = None
        colour = 0xa23dd1

        if isinstance(entry, RadioStationEntry):
            station_name = entry.station_name
            footer = dict(text=f"From {station_name}", icon_url=entry.thumbnail)
            cover = entry.cover
            colour = 0xbe7621

        em = Embed(
            title=entry.title,
            description=desc,
            url=entry.link,
            colour=colour
        )
        if footer:
            em.set_footer(**footer)
        if cover:
            em.set_thumbnail(url=cover)
        return em

    async def get_embed(self) -> Embed:
        entry = self.player.current_entry

        if not entry:
            return Embed(description="Nothing playing")

        if isinstance(entry, StreamEntry) and not isinstance(entry, RadioSongEntry):
            return self.get_stream_entry_embed(entry)

        fields = []
        author = {}
        footer = {}

        playing_state = "►" if self.player.is_paused else "❚❚"
        progress_bar = None
        song_progress = self.player.progress
        song_duration = entry.duration

        title = entry.title
        colour = 0xa9b244

        if isinstance(entry, (RadioSongEntry, GieselaEntry)):
            author = dict(name=entry.artist)
            cover = entry.cover
        else:
            cover = entry.thumbnail
            if "playlist" in entry.meta:
                # TODO is this even possible anymore?
                pl = entry.meta["playlist"]
                author = dict(name=pl["name"], icon_url=pl.get("cover", False) or Embed.Empty)
            elif "author" in entry.meta:
                author = entry.meta["author"]
                author = dict(name=author.display_name, icon_url=author.avatar_url)

        if isinstance(entry, RadioSongEntry):
            colour = 0xa23dd1
            footer = dict(text="🔴 Live from {entry.station_name}", icon_url=entry.thumbnail)
            song_progress = entry.song_progress
            song_duration = entry.song_duration
        elif isinstance(entry, GieselaEntry):
            colour = 0xF9FF6E
            author["icon_url"] = entry.artist_image
            fields.append(dict(name="Album", value=entry.album))
        elif isinstance(entry, TimestampEntry):
            colour = 0x00FFFF
            sub_entry = entry.current_sub_entry
            title = sub_entry["name"]
            sub_index = sub_entry["index"]

            footer = dict(text=f"{sub_index + 1}{ordinal(sub_index + 1)} sub-entry of \"{entry.whole_title}\" "
                               f"[{to_timestamp(song_progress)}/{to_timestamp(song_duration)}]")

            song_progress = sub_entry["progress"]
            song_duration = sub_entry["duration"]

            cover = entry.thumbnail
        elif isinstance(entry, YoutubeEntry):
            colour = 0xa9b244

        progress_bar = progress_bar or create_progress_bar(song_progress, song_duration)
        desc = f"{playing_state} {progress_bar} `[{to_timestamp(song_progress)}/{to_timestamp(song_duration)}]`"

        em = Embed(
            title=title,
            description=desc,
            url=entry.url,
            colour=colour
        )

        for field in fields:
            em.add_field(**field)

        if footer:
            em.set_footer(**footer)
        if cover:
            em.set_thumbnail(url=cover)
        if author:
            em.set_author(**author)

        return em

    async def on_create_message(self, msg: Message):
        await self.add_reactions(msg)

    async def start(self):
        await super().start()

    @emoji_handler("⏮", pos=1)
    async def prev_entry(self, *_):
        self.player.queue.replay(0, revert=True)

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

    async def delayed_update(self):
        await asyncio.sleep(.5)
        await self.trigger_update()

    async def on_any_emoji(self, *_):
        asyncio.ensure_future(self.delayed_update())
