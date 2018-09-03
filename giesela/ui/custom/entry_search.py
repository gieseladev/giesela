from typing import Awaitable, List, Optional

from discord import Embed, TextChannel, User
from discord.ext import commands

from giesela import BaseEntry, GieselaEntry, GieselaPlayer, utils
from ..help import AutoHelpEmbed
from ..interactive import ItemPicker, MessageableEmbed


def get_entry_embed(entry: BaseEntry) -> Embed:
    em = Embed(title=entry.title, url=entry.url)

    if isinstance(entry, YoutubeEntry):
        em.set_thumbnail(url=entry.thumbnail)

    if isinstance(entry, GieselaEntry):
        em.title = entry.song_title
        em.set_author(name=entry.artist, icon_url=entry.artist_image)
        em.add_field(name="Album", value=entry.album)
        em.set_thumbnail(url=entry.cover)

    em.add_field(name="Duration", value=utils.format_time(entry.duration))

    return em


class EntrySearchUI(AutoHelpEmbed, MessageableEmbed, ItemPicker):
    player: GieselaPlayer
    results: List[Awaitable[BaseEntry]]

    def __init__(self, channel: TextChannel, player: GieselaPlayer, results: List[Awaitable[BaseEntry]], user: User = None, **kwargs):
        super().__init__(channel, user=user, **kwargs)
        self.player = player
        self.results = results

    @property
    def help_title(self) -> str:
        return "Entry Searcher"

    @property
    def normalised_index(self) -> int:
        return self.current_index % len(self.results)

    async def get_current_result(self) -> BaseEntry:
        return await self.results[self.normalised_index]

    async def get_current_embed(self) -> Embed:
        result = await self.get_current_result()
        em = get_entry_embed(result)
        em.set_footer(text=f"Result {self.normalised_index + 1}/{len(self.results)}")
        return em

    async def choose(self) -> Optional[BaseEntry]:
        result = await self.display()
        if result is not None:
            return await self.get_current_result()

    @commands.command("play")
    async def play_result(self, _):
        """Play next"""
        result = await self.get_current_result()
        self.player.queue.add_entry(result, placement=0)
