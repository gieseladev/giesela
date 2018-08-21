import abc
import textwrap
from typing import List

from discord import Colour, Embed, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, Playlist
from giesela.cogs.player import Player
from giesela.playlists import EditPlaylistProxy, PlaylistEntry
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


class _PlaylistEmbed(VerticalTextViewer, metaclass=abc.ABCMeta):
    """
    Keyword Args:
        bot: `Giesela`.
        playlist: `Playlist`.
    """
    PASS_BOT: bool = False

    bot: Giesela
    player_cog = Player
    playlist: Playlist

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        self.bot = kwargs.pop("bot")
        self.playlist = kwargs.pop("playlist")
        embed_frame = create_basic_embed(self.playlist)

        if self.PASS_BOT:
            kwargs["bot"] = self.bot

        super().__init__(channel, user, embed_frame=embed_frame, **kwargs)

        self.player_cog = self.bot.cogs["Player"]

    @property
    def entries(self) -> List[PlaylistEntry]:
        return self.playlist.entries

    @property
    def index_padding(self) -> int:
        return len(str(len(self.entries)))

    @property
    def total_lines(self) -> int:
        return len(self.entries)

    async def get_line(self, line: int) -> str:
        entry = self.entries[line]
        index = str(line + 1).rjust(self.index_padding, "0")
        title = textwrap.shorten(entry.title, 50)

        return f"`{index}.` {title}"

    async def play(self, channel: TextChannel, user: User):
        player = await self.player_cog.get_player(channel.guild, member=user)
        await self.playlist.play(player.queue, channel=channel, author=user)


class PlaylistViewer(_PlaylistEmbed):
    @emoji_handler("🎵", pos=999)
    async def play_playlist(self, *_):
        await self.play(self.channel, self.user)
        await self.remove_handler(self.play_playlist)


class PlaylistBuilder(HasHelp, _PlaylistEmbed, MessageableEmbed):
    PASS_BOT = True

    playlist_editor: EditPlaylistProxy

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        super().__init__(channel, user, **kwargs)
        self.playlist_editor = self.playlist.edit()

    @property
    def entries(self) -> List[PlaylistEntry]:
        return self.playlist_editor.entries

    def get_help_embed(self) -> Embed:
        embed = Embed(title="Playlist Builder Help", colour=Colour.blue())

        reaction_help = get_reaction_help(self)
        embed.add_field(name="Buttons", value=reaction_help)

        message_help = get_message_help(self)
        embed.add_field(name="Commands", value=message_help, inline=False)

        return embed

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_) -> List[str]:
        """Close and save"""
        self.stop_listener()
        self.playlist_editor.apply()
        return self.playlist_editor.get_changelog()

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Close without saving"""
        self.stop_listener()
        return None

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
        entry = None  # TODO get entry
        entry = self.playlist_editor.add_entry(entry)
        await self.show_line(self.playlist_editor.index_of(entry))

    @commands.command("remove", aliases=["rm"])
    async def remove_entry(self, ctx: Context, *indices: int):
        """Remove entries"""
        if not indices:
            raise commands.CommandError("Please provide at least one index to remove")

        for index in sorted(indices, reverse=True):
            self.playlist_editor.remove_entry(index - 1)

        if len(indices) == 1:
            await self.show_line(indices[0])
        else:
            await self.show_window()

        print(self.playlist_editor.get_changelog())
