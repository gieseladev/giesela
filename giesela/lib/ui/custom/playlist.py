import abc
import textwrap
from typing import List

from discord import Colour, Embed, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, Playlist
from giesela.cogs.player import Player
from ..help import HasHelp, get_command_help, get_message_help, get_reaction_help
from ..interactive import MessageableEmbed, VerticalTextViewer, emoji_handler


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
        title = textwrap.shorten(entry.title, 50)
        entries.append(f"`{index}.` {title}")

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
        self.player_cog = self.bot.cogs["Player"]
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
        self.bot = kwargs.pop("bot")
        self.playlist = kwargs.pop("playlist")
        entries = create_entry_list(self.playlist)
        embed_frame = create_basic_embed(self.playlist)
        super().__init__(channel, user, content=entries, embed_frame=embed_frame, **kwargs)

    @emoji_handler("🎵", pos=999)
    async def play_playlist(self, *_):
        await self.play(self.channel, self.user)
        await self.remove_handler(self.play_playlist)


class PlaylistBuilder(_PlaylistEmbed, MessageableEmbed, HasHelp, VerticalTextViewer):

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        self.bot = kwargs["bot"]
        self.playlist = kwargs.pop("playlist")
        entries = create_entry_list(self.playlist)
        embed_frame = create_basic_embed(self.playlist)
        super().__init__(channel, user, content=entries, embed_frame=embed_frame, **kwargs)

    def get_help_embed(self) -> Embed:
        embed = Embed(title="Playlist Builder Help", colour=Colour.blue())

        reaction_help = get_reaction_help(self)
        embed.add_field(name="Buttons", value=reaction_help)

        message_help = get_message_help(self)
        embed.add_field(name="Commands", value=message_help, inline=False)

        return embed

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_):
        """Close and save"""
        self.stop_listener()

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_):
        """Close without saving"""
        self.stop_listener()

    @emoji_handler("❓", pos=1001)
    async def show_help(self, *_):
        """Open this very box"""
        self.trigger_help_embed(self.channel, self.user)

    @commands.command()
    async def help(self, ctx: Context, *cmds: str):
        """Even more help"""
        if not cmds:
            await self.show_help_embed(self.channel, self.user)
            return

        embed = await get_command_help(ctx, *cmds)
        self.trigger_help_embed(self.channel, self.user, embed=embed)

    @commands.command("edit")
    async def edit_entry(self, ctx: Context, index: int):
        """Edit an entry"""
        print("this is the life", flush=True)

    @commands.command("add")
    async def add_entry(self, ctx: Context, *query: str):
        """Add an entry"""
        query = " ".join(query)

    @commands.command("remove", aliases=["rm"])
    async def remove_entry(self, ctx: Context, *indices: int):
        """Remove entries"""
        pass
