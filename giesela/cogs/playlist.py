import json
import random
from io import BytesIO

from discord import Colour, Embed, File, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, Playlist, PlaylistManager, utils
from giesela.lib.ui import EmbedPaginator, EmbedViewer, PromptYesNo
from giesela.lib.ui.custom import PlaylistViewer
from .info import help_formatter
from .player import Player

LOAD_ORDER = 1


def playlist_embed(playlist: Playlist) -> Embed:
    description = playlist.description or "No description"
    embed = Embed(title=playlist.name, description=description)
    embed.set_thumbnail(url=playlist.cover)
    embed.set_author(name=playlist.author.display_name, icon_url=playlist.author.avatar_url)
    embed.set_footer(text=f"Playlist with {len(playlist)} entries")
    return embed


def ensure_user_can_edit_playlist(playlist: Playlist, user: User):
    if not playlist.can_edit(user):
        raise commands.CommandError("You're not allowed to edit this playlist!")


def ensure_user_is_author(playlist: Playlist, user: User, operation="perform this command"):
    # TODO let bot owner do as they please!
    if not playlist.is_author(user):
        raise commands.CommandError(f"Only the author of this may {operation} ({playlist.author.mention})!")


class Playlist:
    bot: Giesela
    playlist_manager: PlaylistManager

    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.playlist_manager = PlaylistManager.load(self.bot, self.bot.config.playlists_file)

        self.player_cog = bot.cogs["Player"]

    def find_playlist(self, playlist: str) -> Playlist:
        _playlist = self.playlist_manager.find_playlist(playlist)
        if not _playlist:
            raise commands.CommandError(f"Couldn't this playlist {playlist}")
        return _playlist

    async def play_playlist(self, ctx: Context, playlist: Playlist):
        player = await self.player_cog.get_player(ctx)
        await playlist.play(player.queue, channel=ctx.channel, author=ctx.author)
        await ctx.send("Loaded playlist", embed=playlist_embed(playlist))

    @commands.group(invoke_without_command=True, aliases=["pl"])
    async def playlist(self, ctx: Context, playlist: str = None):
        """Playlist stuff"""
        if playlist:
            playlist = self.playlist_manager.find_playlist(playlist)

        if not playlist:
            await help_formatter.send_help_for(ctx, self.playlist)

        viewer = PlaylistViewer(self.bot, ctx.channel, ctx.author, playlist)
        await viewer.display()

    @playlist.group("play", aliases=["load"])
    async def playlist_play(self, ctx: Context, playlist: str):
        """Play a playlist"""
        playlist = self.find_playlist(playlist)
        await self.play_playlist(ctx, playlist)

    @playlist_play.command("random")
    async def playlist_play_random(self, ctx: Context):
        """Play a random playlist"""
        playlists = list(self.playlist_manager.playlists)
        if not playlists:
            raise commands.CommandError("No playlists to choose from")

        playlist = random.choice(playlists)
        await self.play_playlist(ctx, playlist)

    @playlist.command("delete", aliases=["rm", "remove"])
    async def playlist_delete(self, ctx: Context, playlist: str):
        """Delete a playlist"""
        playlist = self.find_playlist(playlist)
        ensure_user_is_author(playlist, ctx.author, "delete it")
        embed = playlist_embed(playlist)
        playlist.delete()
        await ctx.send("Deleted playlist", embed=embed)

    @playlist.command("transfer")
    async def playlist_transfer(self, ctx: Context, playlist: str, user: User):
        """Transfer a playlist to someone else."""
        playlist = self.find_playlist(playlist)
        ensure_user_is_author(playlist, ctx.author, "transfer it")
        playlist.transfer(user)
        await ctx.send(f"Transferred **{playlist.name}** to {user.mention}")

    @playlist.group("editor", invoke_without_command=True, aliases=["editors"])
    async def playlist_editor(self, ctx: Context, playlist: str):
        """Manage editors of a playlist."""
        playlist = self.find_playlist(playlist)

        text = f"author: {playlist.author.mention}\n"

        if playlist.editors:
            editors = "\n".join(f"  - {editor.mention}" for editor in playlist.editors)
            text += f"editors:\n" \
                    f"{editors}"
        else:
            text += "No editors"

        await ctx.send(embed=Embed(title=playlist.name, description=text, colour=Colour.blue()))

    @playlist_editor.command("add")
    async def playlist_editor_add(self, ctx: Context, playlist: str, user: User):
        """Give someone the permission to edit your playlist."""
        playlist = self.find_playlist(playlist)
        ensure_user_is_author(playlist, user)

        if playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} is already an editor of **{playlist.name}**")

        playlist.add_editor(user)
        await ctx.send(f"Added {user.mention} as an editor for **{playlist.name}**")

    @playlist_editor.command("remove", aliases=["rm"])
    async def playlist_editor_remove(self, ctx: Context, playlist: str, user: User):
        """Remove an editor from your playlist."""
        playlist = self.find_playlist(playlist)
        ensure_user_is_author(playlist, user)

        if not playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} isn't an editor of **{playlist.name}**")

        playlist.remove_editor(user)
        await ctx.send(f"Removed {user.mention} as an editor for **{playlist.name}**")

    @playlist.command("show", aliases=["showall", "all"])
    async def playlist_show(self, ctx: Context):
        """Show all the playlists"""
        if not self.playlist_manager:
            raise commands.CommandError("No playlists!")

        template = Embed(title="Playlists", colour=Colour.blue())
        paginator = EmbedPaginator(template=template, fields_per_page=5)

        for playlist in self.playlist_manager:
            description = playlist.description or "No description"
            paginator.add_field(playlist.name, f"by **{playlist.author.name}**\n"
                                               f"{len(playlist)} entries ({utils.format_time(playlist.duration)} long)\n"
                                               f"\n"
                                               f"{description}")

        # TODO use special viewer with play (and other) features
        viewer = EmbedViewer(ctx.channel, ctx.author, embeds=paginator)
        await viewer.display()

    @playlist.command("import", aliases=["imp"])
    async def playlist_import(self, ctx: Context):
        """Import a playlist from a GPL file."""
        if not ctx.message.attachments:
            raise commands.CommandError("Nothing attached...")

        embed = Embed(colour=Colour.green())
        embed.set_author(name="Loaded Playlist")

        attachment = ctx.message.attachments[0]

        playlist_data = BytesIO()
        await attachment.save(playlist_data)
        playlist = self.playlist_manager.import_from_gpl(playlist_data.read().decode("utf-8"))

        if playlist:
            embed.add_field(name=playlist.name, value=f"by {playlist.author.name}\n{len(playlist)} entries")
        else:
            raise commands.CommandError("Couldn't load playlist")

        await ctx.send(embed=embed)

    @playlist.command("export")
    async def playlist_export(self, ctx: Context, playlist: str):
        """Export a playlist"""
        playlist = self.find_playlist(playlist)

        serialised = json.dumps(playlist.to_gpl(), indent=None, separators=(",", ":"))
        data = BytesIO(serialised.encode("utf-8"))
        data.seek(0)
        file = File(data, filename=f"{playlist.name}.gpl")
        await ctx.send("Here you go", file=file)

    @commands.command("addtoplaylist", aliases=["quickadd", "pladd", "pl+"])
    async def playlist_quickadd(self, ctx: Context, playlist: str):
        """Add the current entry to a playlist."""
        playlist = self.find_playlist(playlist)
        ensure_user_can_edit_playlist(playlist, ctx.author)

        player = await self.player_cog.get_player(ctx)
        entry = player.current_entry
        if not entry:
            raise commands.CommandError("There's nothing playing right now")

        if entry in playlist:
            if not await PromptYesNo(ctx.channel, text=f"{entry.title} is already in this playlist, are you sure you want to add it again?"):
                return

        playlist.add(entry)

        await ctx.send(f"Added **{entry.title}** to **{playlist.name}**")

    @commands.command("removefromplaylist", aliases=["quickremove", "quickrm", "plremove", "plrm", "pl-"])
    async def playlist_quickremove(self, ctx: Context, playlist: str):
        """Remove the current entry from a playlist."""
        playlist = self.find_playlist(playlist)
        ensure_user_can_edit_playlist(playlist, ctx.author)

        player = await self.player_cog.get_player(ctx)
        entry = player.current_entry
        if not entry:
            raise commands.CommandError("There's nothing playing right now")

        if entry not in playlist:
            raise commands.CommandError(f"{entry.title} isn't in this playlist!")

        playlist.remove(entry)

        await ctx.send(f"Removed **{entry.title}** from **{playlist.name}**")


def setup(bot: Giesela):
    bot.add_cog(Playlist(bot))
