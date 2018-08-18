from typing import List

from discord import Embed, TextChannel, User

from giesela import Giesela, Playlist
from giesela.cogs.player import Player
from ..interactive import VerticalTextViewer, emoji_handler


def create_basic_embed(playlist: Playlist) -> Embed:
    embed = Embed(title=playlist.name)
    if playlist.description:
        embed.add_field(name="Description", value=playlist.description, inline=False)
    if playlist.cover:
        embed.set_thumbnail(url=playlist.cover)
    embed.set_author(name=playlist.author.display_name, icon_url=playlist.author.avatar_url)
    embed.set_footer(text="{progress_bar}")
    return embed


def create_entry_list(playlist: Playlist) -> List[str]:
    entries = []
    index_padding = len(str(len(playlist)))

    for ind, entry in enumerate(playlist, 1):
        index = str(ind).rjust(index_padding, "0")
        entries.append(f"`{index}.` {entry.title}")

    return entries


class PlaylistViewer(VerticalTextViewer):
    bot: Giesela
    player_cog = Player
    playlist: Playlist

    def __init__(self, bot: Giesela, channel: TextChannel, user: User, playlist: Playlist, **kwargs):
        entries = create_entry_list(playlist)
        embed_frame = create_basic_embed(playlist)
        super().__init__(channel, user, content=entries, embed_frame=embed_frame, **kwargs)

        self.bot = bot
        self.player_cog = bot.cogs["Player"]
        self.playlist = playlist

    @emoji_handler("▶", pos=999)
    async def play_playlist(self, *_):
        player = await self.player_cog.get_player(self.channel.guild, member=self.user)
        await self.playlist.play(player.queue, channel=self.channel, author=self.user)

        await self.disable_handler(self.play_playlist)
