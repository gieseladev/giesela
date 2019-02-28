from typing import Generic, List, Optional, TypeVar

from discord import Client, Embed, Message, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import GieselaPlayer, PlayableEntry
from giesela.permission.utils import ensure_entry_add_permissions
from giesela.ui import prefab
from ..help import AutoHelpEmbed
from ..interactive import ItemPicker, MessageableEmbed

T = TypeVar("T", bound=PlayableEntry)


class EntrySearchUI(AutoHelpEmbed, MessageableEmbed, ItemPicker, Generic[T]):
    def __init__(self, channel: TextChannel, *,
                 player: GieselaPlayer,
                 results: List[T],
                 bot: Client,
                 user: Optional[User],
                 message: Message = None,
                 delete_msgs: bool = True,
                 **kwargs) -> None:
        super().__init__(channel, bot=bot, user=user, delete_msgs=delete_msgs, message=message, **kwargs)
        self.player = player
        self.results = results

    @property
    def help_title(self) -> str:
        return "Entry Searcher"

    @property
    def normalised_index(self) -> int:
        return self.current_index % len(self.results)

    @property
    def current_result(self) -> T:
        return self.results[self.normalised_index]

    async def get_current_embed(self) -> Embed:
        result = self.current_result
        em = prefab.get_entry_embed(result)
        em.set_footer(text=f"Result {self.normalised_index + 1}/{len(self.results)}")
        return em

    async def choose(self) -> Optional[T]:
        result = await self.display()
        if result is not None:
            return self.current_result

    @commands.command("play")
    async def play_result(self, ctx: Context):
        """Play next"""
        result = self.current_result

        await ensure_entry_add_permissions(ctx, result)
        self.player.queue.add_entry(result, ctx.author)
