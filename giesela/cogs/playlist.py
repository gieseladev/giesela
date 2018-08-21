import json
import random
from io import BytesIO
from typing import Optional

from discord import Attachment, Colour, Embed, File, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, Playlist, PlaylistManager, utils
from giesela.lib.ui import EditableEmbed, EmbedPaginator, EmbedViewer, PromptYesNo
from giesela.lib.ui.custom import PlaylistBuilder, PlaylistViewer
from .info import help_formatter
from .player import Player

LOAD_ORDER = 1


def playlist_embed(playlist: Playlist) -> Embed:
    description = playlist.description or "No description"
    embed = Embed(title=playlist.name, description=description)
    if playlist.cover:
        embed.set_thumbnail(url=playlist.cover)
    embed.set_author(name=playlist.author.display_name, icon_url=playlist.author.avatar_url)
    embed.set_footer(text=f"Playlist with {len(playlist)} entries")
    return embed


async def is_owner(ctx: Context) -> bool:
    return await ctx.bot.is_owner(ctx.author)


async def ensure_user_can_edit_playlist(playlist: Playlist, ctx: Context):
    if not (playlist.can_edit(ctx.author) or await is_owner(ctx)):
        raise commands.CommandError("You're not allowed to edit this playlist!")


async def ensure_user_is_author(playlist: Playlist, ctx: Context, operation="perform this command"):
    if not (playlist.is_author(ctx.author) or await is_owner(ctx)):
        raise commands.CommandError(f"Only the author of this playlist may {operation} ({playlist.author.mention})!")


async def save_attachment(attachment: Attachment) -> BytesIO:
    data = BytesIO()
    await attachment.save(data)
    return data


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
            raise commands.CommandError(f"Couldn't find playlist \"{playlist}\"")
        return _playlist

    async def play_playlist(self, ctx: Context, playlist: Playlist):
        player = await self.player_cog.get_player(ctx)
        await playlist.play(player.queue, channel=ctx.channel, author=ctx.author)
        await ctx.send("Loaded playlist", embed=playlist_embed(playlist))

    async def on_logout(self):
        self.playlist_manager.close()

    @commands.group(invoke_without_command=True, aliases=["pl"])
    async def playlist(self, ctx: Context, playlist: str = None):
        """Playlist stuff"""
        if playlist:
            playlist = self.find_playlist(playlist)
        else:
            await help_formatter.send_help_for(ctx, self.playlist)
            return

        viewer = PlaylistViewer(ctx.channel, user=ctx.author, bot=self.bot, playlist=playlist)
        await viewer.display()
        await ctx.message.delete()

    @playlist.group("play", aliases=["load", "start", "listen"])
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

    @playlist.command("builder", aliases=["build", "edit", "manipulate"])
    async def playlist_builder(self, ctx: Context, playlist: str):
        """Edit a playlist"""
        playlist = self.find_playlist(playlist)
        await ensure_user_can_edit_playlist(playlist, ctx)
        builder = PlaylistBuilder(ctx.channel, ctx.author, bot=self.bot, playlist=playlist)
        changelog = await builder.display()
        if changelog:
            desc = "\n".join(changelog)
            embed = Embed(title=f"Saved changes to {playlist.name}", description=desc, colour=Colour.green())
            await ctx.send(embed=embed)
        else:
            await ctx.message.delete()

    @playlist.command("rename", aliases=["newname", "rn"])
    async def playlist_rename(self, ctx: Context, playlist: str, name: str):
        """Rename a playlist"""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "rename it")
        old_name = playlist.name
        playlist.rename(name)
        await ctx.send(f"**{old_name}** is now **{playlist.name}**")

    @playlist.command("description", aliases=["describe", "desc"])
    async def playlist_description(self, ctx: Context, playlist: str, *description: str):
        """Describe your playlist to make it better"""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "change its description")
        description = " ".join(description)
        playlist.set_description(description)
        await ctx.send(f"Set the description of **{playlist.name}** to:\n"
                       f"```\n"
                       f"{description}```")

    @playlist.group("cover", invoke_without_command=True, aliases=["image", "picture"])
    async def playlist_cover(self, ctx: Context, playlist: str, cover: str):
        """Set the cover of a playlist"""
        if cover in ("auto",):
            await ctx.invoke(self.playlist_cover_auto, playlist)
            return

        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "change its cover")

        if not cover:
            raise commands.CommandError("No cover provided!")

        if await playlist.set_cover(cover):
            embed = Embed(description=f"Changed the cover of **{playlist.name}**")
            embed.set_image(url=playlist.cover)
            await ctx.send(embed=embed)
        else:
            raise commands.CommandError(f"Couldn't change the cover to <{cover}>, are you sure this is a valid url for an image?")

    @playlist_cover.command("auto")
    async def playlist_cover_auto(self, ctx: Context, playlist: str):
        """Automatically generate a cover

        If you're too lazy to make one yourself, why not let Giesela do it?
        """
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "change its cover")
        msg = EditableEmbed(ctx.channel)
        await msg.edit(Embed(description="working...", colour=Colour.blue()))

        if await playlist.set_cover():
            embed = Embed(description=f"This is the new face of **{playlist.name}**", colour=Colour.green())
            embed.set_image(url=playlist.cover)
            await msg.edit(embed=embed)
        else:
            await msg.edit(Embed(description=f"Couldn't generate a cover...", colour=Colour.red()))

    @playlist.command("delete", aliases=["rm", "remove"])
    async def playlist_delete(self, ctx: Context, playlist: str):
        """Delete a playlist"""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "delete it")

        res = await PromptYesNo(ctx.channel, user=ctx.author, text=f"Do you really want to delete **{playlist.name}**?")
        if not res:
            return

        embed = playlist_embed(playlist)
        playlist.delete()
        await ctx.send("Deleted playlist", embed=embed)

    @playlist.command("transfer")
    async def playlist_transfer(self, ctx: Context, playlist: str, user: User):
        """Transfer a playlist to someone else."""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "transfer it")
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
        await ensure_user_is_author(playlist, ctx, "add editors")

        if playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} is already an editor of **{playlist.name}**")

        playlist.add_editor(user)
        await ctx.send(f"Added {user.mention} as an editor for **{playlist.name}**")

    @playlist_editor.command("remove", aliases=["rm"])
    async def playlist_editor_remove(self, ctx: Context, playlist: str, user: User):
        """Remove an editor from your playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "remove editors")

        if not playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} isn't an editor of **{playlist.name}**")

        playlist.remove_editor(user)
        await ctx.send(f"Removed {user.mention} as an editor for **{playlist.name}**")

    @playlist.command("show", aliases=["showall", "all", "list"])
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

        # MAYBE use special viewer with play (and other) features
        viewer = EmbedViewer(ctx.channel, ctx.author, embeds=paginator)
        await viewer.display()
        await ctx.message.delete()

    async def import_playlist(self, data) -> Optional[Embed]:
        playlist = self.playlist_manager.import_from_gpl(data)

        if not playlist:
            return

        embed = Embed(colour=Colour.green())
        embed.set_author(name="Loaded Playlist")
        embed.add_field(name=playlist.name, value=f"by {playlist.author.name}\n{len(playlist)} entries")
        return embed

    @playlist.group("import", invoke_without_command=True, aliases=["imp"])
    async def playlist_import(self, ctx: Context):
        """Import a playlist from a GPL file."""
        if not ctx.message.attachments:
            raise commands.CommandError("Please attach a GPL file!")

        playlist_data = await save_attachment(ctx.message.attachments[0])
        embed = await self.import_playlist(playlist_data.read().decode("utf-8"))

        if embed:
            await ctx.send(embed=embed)
        else:
            raise commands.CommandError("Couldn't load playlist\n"
                                        "If this is a playlist from the ancient times (before version 5.0.0) "
                                        "use the command `playlist import old` which requires you to provide the name of the playlist.")

    @playlist_import.command("old", aliases=["ancient"])
    async def playlist_import_old(self, ctx: Context, name: str, author: User = None):
        """Import an old playlist.

        Old playlists didn't store meta data. In order to import them you need to provide the bare minimum of meta data
        which is the name and the author (which defaults to the person executing the command)
        """
        if not ctx.message.attachments:
            raise commands.CommandError("Please attach a GPL file!")

        author = author or ctx.author

        _entry_data = await save_attachment(ctx.message.attachments[0])
        entry_data = _entry_data.read().decode("utf-8")
        try:
            entries = json.loads(entry_data)
        except json.JSONDecodeError:
            raise commands.CommandError("This file is invalid. This cannot be imported!")

        if isinstance(entries, dict):
            raise commands.CommandError("This isn't an old playlist. Please use the `playlist import` command instead!")
        elif not isinstance(entries, list):
            raise commands.CommandError("What is this garbage? This isn't an old playlist and cannot be imported!")

        playlist_data = {
            "name": name,
            "author_id": author.id,
            "entries": entries
        }

        embed = await self.import_playlist(playlist_data)
        if embed:
            await ctx.send(embed=embed)
        else:
            raise commands.CommandError("Couldn't import playlist. This probably doesn't have anything to do with the playlist being old. "
                                        "It's just broken...")

    @playlist.command("export")
    async def playlist_export(self, ctx: Context, playlist: str):
        """Export a playlist"""
        playlist = self.find_playlist(playlist)

        serialised = json.dumps(playlist.to_gpl(), indent=None, separators=(",", ":"))
        data = BytesIO(serialised.encode("utf-8"))
        data.seek(0)
        file = File(data, filename=f"{playlist.name.lower()}.gpl2")
        await ctx.send("Here you go", file=file)

    @commands.command("addtoplaylist", aliases=["quickadd", "pladd", "pl+"])
    async def playlist_quickadd(self, ctx: Context, playlist: str):
        """Add the current entry to a playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_can_edit_playlist(playlist, ctx)

        player = await self.player_cog.get_player(ctx)
        entry = player.current_entry
        if not entry:
            raise commands.CommandError("There's nothing playing right now")

        if entry in playlist:
            if not await PromptYesNo(ctx.channel, user=ctx.author,
                                     text=f"{entry.title} is already in this playlist, are you sure you want to add it again?"):
                return

        playlist.add(entry)

        await ctx.send(f"Added **{entry.title}** to **{playlist.name}**")

    @commands.command("removefromplaylist", aliases=["quickremove", "quickrm", "plremove", "plrm", "pl-"])
    async def playlist_quickremove(self, ctx: Context, playlist: str):
        """Remove the current entry from a playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_can_edit_playlist(playlist, ctx)

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
