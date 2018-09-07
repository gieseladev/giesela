import asyncio
from typing import Optional

from discord import Colour, Embed, Message, TextChannel

from giesela import BaseEntry, ChapterEntry, GieselaPlayer, RadioEntry, SpecificChapterData, utils
from giesela.ui import create_player_bar
from giesela.utils import ObjectChain
from .. import InteractableEmbed, IntervalUpdatingMessage, emoji_handler


def create_progress_bar(progress: float, duration: float, *, length: int = 18) -> str:
    progress_ratio = progress / duration if duration > 0 else 0
    progress_bar = create_player_bar(progress_ratio, length)
    return progress_bar


def get_description(progress: float, duration: float = None, is_playing: bool = None) -> str:
    if is_playing is None:
        prefix = ""
    else:
        prefix = "❚❚ | " if is_playing else "► | "

    progress_ts = utils.to_timestamp(progress)

    if duration is None:
        prefix = r"\🔴 "
        content = "**Live**"
        suffix = f"Playing for {progress_ts}"
    else:
        content = create_progress_bar(progress, duration)
        duration_ts = utils.to_timestamp(duration)
        suffix = f"`{progress_ts}/{duration_ts}`"

    return f"{prefix}{content} | {suffix}"


class NowPlayingEmbed(IntervalUpdatingMessage, InteractableEmbed):
    """
    Keyword Args:
        seek_amount: Amount of seconds to forward/rewind
    """
    _delayed_update_task: Optional[asyncio.Task]
    _show_detailed_task: Optional[asyncio.Task]

    def __init__(self, channel: TextChannel, *, player: GieselaPlayer, seek_amount: float = 30, show_detailed_duration: float = 20, **kwargs):
        super().__init__(channel, **kwargs)
        self.player = player
        self.seek_amount = seek_amount

        self.show_detailed_duration = show_detailed_duration
        self.showing_detailed = False

        self._delayed_update_task = None
        self._show_detailed_task = None

    async def get_embed(self) -> Embed:
        player_entry = self.player.current_entry

        if not player_entry:
            return Embed(description="Nothing playing")

        entry = player_entry.entry
        progress = player_entry.progress
        duration = entry.duration

        if not isinstance(entry, BaseEntry):
            return Embed(title=str(entry), footer="Unsupported entry type")

        if player_entry.has_chapters:
            chapter = player_entry.chapter
            if isinstance(chapter, SpecificChapterData):
                progress = chapter.get_chapter_progress(progress)
                duration = chapter.duration

            target = ObjectChain(chapter, entry)
        else:
            chapter = None
            target = entry

        playlist = player_entry.get("playlist", None)
        requester = player_entry.get("requester", None)

        description = get_description(progress, duration, self.player.is_playing)

        em = Embed(title=target.title, description=description, colour=Colour.greyple())

        if target.artist or target.artist_image:
            em.set_author(name=target.artist or "Unknown Artist", icon_url=target.artist_image or Embed.Empty)

        if target.cover:
            em.set_thumbnail(url=target.cover)

        if target.album:
            em.add_field(name="Album", value=target.album)

        if playlist:
            em.set_footer(text=playlist.name, icon_url=playlist.cover or Embed.Empty)

        if isinstance(entry, RadioEntry):
            em.set_footer(text=entry.station.name, icon_url=entry.station.logo or Embed.Empty)

        if requester and self.showing_detailed:
            em.add_field(name="Requested by", value=requester.mention)

        if chapter and isinstance(entry, ChapterEntry):
            index = entry.chapters.index(chapter)
            total_chapters = len(entry.chapters)
            em.set_footer(text=f"Chapter {index + 1}/{total_chapters} of {entry}", icon_url=entry.cover or Embed.Empty)

            if self.showing_detailed:
                em.add_field(name="Total Progress", value=get_description(self.player.progress, entry.duration))

        next_entry = self.player.queue.peek()
        if next_entry and self.showing_detailed:
            em.add_field(name="Up Next", value=str(next_entry.entry), inline=False)

        return em

    async def _show_detailed(self):
        self.showing_detailed = True
        try:
            await self.trigger_update()
            await asyncio.sleep(self.show_detailed_duration)
        finally:
            self.showing_detailed = False

        await self.trigger_update()

    async def on_create_message(self, msg: Message):
        await self.add_reactions(msg)

    async def start(self):
        await super().start()

    @emoji_handler("⏮", pos=1)
    async def prev_entry(self, *_):
        self.player.queue.replay(0, revert=True)

    @emoji_handler("⏪", pos=2)
    async def fast_rewind(self, *_):
        if self.player.can_seek:
            await self.player.seek(self.player.progress - self.seek_amount)

    @emoji_handler("⏯", pos=3)
    async def play_pause(self, *_):
        if self.player.is_playing:
            await self.player.pause()
        else:
            await self.player.resume()

    @emoji_handler("⏩", pos=4)
    async def fast_forward(self, *_):
        if self.player.can_seek:
            await self.player.seek(self.player.progress + self.seek_amount)

    @emoji_handler("⏭", pos=5)
    async def next_entry(self, *_):
        await self.player.skip()

    @emoji_handler("🔎", pos=10)
    async def show_detailed(self, *_):
        task = self._show_detailed_task
        if task and not task.done():
            task.cancel()
            return

        self._show_detailed_task = asyncio.ensure_future(self._show_detailed())

    async def delayed_update(self):
        await asyncio.sleep(.5)
        await self.trigger_update()

    async def on_any_emoji(self, *_):
        task = self._delayed_update_task
        if task and not task.done():
            return

        self._delayed_update_task = asyncio.ensure_future(self.delayed_update())
