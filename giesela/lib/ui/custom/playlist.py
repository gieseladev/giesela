import abc
from typing import List

from discord import Embed, TextChannel, User

from giesela import Giesela, Playlist
from giesela.cogs.player import Player
from ..interactive import MessageableEmbed, VerticalTextViewer, emoji_handler, message_handler


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


class _PlaylistEmbed(metaclass=abc.ABCMeta):
    """
    Keyword Args:
        bot: `Giesela`.
        playlist: `Playlist`.
    """
    bot: Giesela
    player_cog = Player
    playlist: Playlist

    def __init__(self, *args, **kwargs):
        self.bot = kwargs.pop("bot")
        self.player_cog = self.bot.cogs["Player"]
        self.playlist = kwargs.pop("playlist")
        super().__init__(*args, **kwargs)

    async def play(self, channel: TextChannel, user: User):
        player = await self.player_cog.get_player(channel.guild, member=user)
        await self.playlist.play(player.queue, channel=channel, author=user)


class PlaylistViewer(_PlaylistEmbed, VerticalTextViewer):
    """
    Keyword Args:
        playlist: `Playlist`. Playlist which is to be displayed
    """

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        playlist = kwargs.pop("playlist")
        entries = create_entry_list(playlist)
        embed_frame = create_basic_embed(playlist)
        super().__init__(channel, user, content=entries, embed_frame=embed_frame, playlist=playlist, **kwargs)

    @emoji_handler("🎵", pos=999)
    async def play_playlist(self, *_):
        await self.play(self.channel, self.user)
        await self.disable_handler(self.play_playlist)


class PlaylistEditor(_PlaylistEmbed, MessageableEmbed, VerticalTextViewer):
    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        super().__init__(channel, user, **kwargs)

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_):
        self.signal_stop()

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_):
        self.signal_stop()

    @emoji_handler("❓", pos=1001)
    async def show_help(self, *_):
        pass

    @message_handler("edit")
    async def edit_entry(self, index: int):
        """Edit an entry"""
        pass

    @message_handler("add")
    async def add_entry(self, *query: str):
        """Add an entry"""
        query = " ".join(query)

    @message_handler("remove", aliases=["rm"])
    async def remove_entry(self, *indices: int):
        """Remove entries"""
        pass
