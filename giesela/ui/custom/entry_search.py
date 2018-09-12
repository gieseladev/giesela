from typing import List, Optional

from discord import Embed, TextChannel
from discord.ext import commands
from discord.ext.commands import Context

from giesela import GieselaPlayer, PlayableEntry
from giesela.ui import prefab
from ..help import AutoHelpEmbed
from ..interactive import ItemPicker, MessageableEmbed


class EntrySearchUI(AutoHelpEmbed, MessageableEmbed, ItemPicker):
    def __init__(self, channel: TextChannel, *, player: GieselaPlayer, results: List[PlayableEntry], **kwargs):
        super().__init__(channel, **kwargs)
        self.player = player
        self.results = results

    @property
    def help_title(self) -> str:
        return "Entry Searcher"

    @property
    def normalised_index(self) -> int:
        return self.current_index % len(self.results)

    @property
    def current_result(self) -> PlayableEntry:
        return self.results[self.normalised_index]

    async def get_current_embed(self) -> Embed:
        result = self.current_result
        em = prefab.get_entry_embed(result)
        em.set_footer(text=f"Result {self.normalised_index + 1}/{len(self.results)}")
        return em

    async def choose(self) -> Optional[PlayableEntry]:
        result = await self.display()
        if result is not None:
            return self.current_result

    @commands.command("play")
    async def play_result(self, ctx: Context):
        """Play next"""
        result = self.current_result
        self.player.queue.add_entry(result, ctx.author)
