import asyncio
import operator
import random
import rapidjson
import textwrap
from io import BytesIO
from typing import Dict, Optional

from discord import Attachment, Colour, Embed, File, User
from discord.ext import commands
from discord.ext.commands import BadArgument, Context, Converter, view as string_view

from giesela import GPL_VERSION, Giesela, LoadedPlaylistEntry, Playlist, PlaylistManager, utils
from giesela.lib import help_formatter
from giesela.playlist import compat as pl_compat
from giesela.ui import EmbedPaginator, EmbedViewer, ItemPicker, PromptYesNo, VerticalTextViewer
from giesela.ui.custom import PlaylistBuilder, PlaylistRecoveryUI, PlaylistViewer
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


def add_playlist_footer(embed: Embed, playlist: Playlist) -> Embed:
    if playlist.cover:
        embed.set_footer(text=playlist.name, icon_url=playlist.cover)
    else:
        embed.set_footer(text=playlist.name)
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


def unquote_word(text: str) -> str:
    _view = string_view.StringView(text)
    try:
        return string_view.quoted_word(_view)
    except BadArgument:
        return text


class UnquotedStr(str, Converter):
    async def convert(self, ctx: Context, argument: str) -> str:
        return unquote_word(argument)


class PlaylistCog:
    playlist_manager: PlaylistManager

    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.playlist_manager = PlaylistManager.load(self.bot, self.bot.config.playlists_file)

        self.player_cog = bot.cogs["Player"]
        self.extractor = self.player_cog.extractor

    def find_playlist(self, playlist: str) -> Playlist:
        _playlist = self.playlist_manager.find_playlist(playlist)
        if not _playlist:
            raise commands.CommandError(f"Couldn't find playlist \"{playlist}\"")
        return _playlist

    async def play_playlist(self, ctx: Context, playlist: Playlist):
        player = await self.player_cog.get_player(ctx)
        await playlist.play(player.queue, requester=ctx.author)
        await ctx.send("Loaded playlist", embed=playlist_embed(playlist))

    async def _playlist_builder(self, ctx: Context, playlist: Playlist):
        builder = PlaylistBuilder(ctx.channel, ctx.author, bot=self.bot, playlist=playlist)
        changelog = await builder.display()
        if changelog:
            frame = Embed(title=f"Saved changes to {playlist.name}", colour=Colour.green())
            viewer = VerticalTextViewer(ctx.channel, content=changelog, embed_frame=frame)
            await viewer.display()
        else:
            await ctx.message.delete()

    async def import_playlist(self, data, author: User = None) -> Optional[Embed]:
        playlist = self.playlist_manager.import_from_gpl(data, author=author)

        if not playlist:
            return

        return playlist_embed(playlist)

    async def on_shutdown(self):
        self.playlist_manager.close()

    @commands.group(invoke_without_command=True, aliases=["pl"])
    async def playlist(self, ctx: Context, *, playlist: UnquotedStr = None):
        """Playlist stuff"""
        if playlist:
            playlist = self.find_playlist(playlist)
        else:
            await help_formatter.send_help_for(ctx, self.playlist)
            return

        viewer = PlaylistViewer(ctx.channel, user=ctx.author, bot=self.bot, playlist=playlist)
        await viewer.display()
        await ctx.message.delete()

    @playlist.group("play", invoke_without_command=True, aliases=["load", "start", "listen"])
    async def playlist_play(self, ctx: Context, *, playlist: UnquotedStr):
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

    @playlist.command("create", aliases=["new"])
    async def playlist_create(self, ctx: Context, *, name: UnquotedStr):
        """Create a new playlist"""
        if not name:
            raise commands.CommandError("Your name is stupid, choose another one!")

        similar_playlist = self.playlist_manager.find_playlist(name, threshold=.6)
        if similar_playlist:
            prompt = PromptYesNo(ctx.channel, user=ctx.author, text=f"There's already a playlist with a similar name (\"{similar_playlist.name}\"). "
                                                                    f"Do you really want to create the playlist \"{name}\"")
            if not await prompt:
                return
        playlist = Playlist(name=name, author_id=ctx.author.id)
        playlist.manager = self.playlist_manager

        await self._playlist_builder(ctx, playlist)

    @playlist.command("builder", aliases=["build", "edit", "manipulate"])
    async def playlist_builder(self, ctx: Context, *, playlist: UnquotedStr):
        """Edit a playlist"""
        playlist = self.find_playlist(playlist)
        await ensure_user_can_edit_playlist(playlist, ctx)
        await self._playlist_builder(ctx, playlist)

    @playlist.command("rename", aliases=["newname", "rn"])
    async def playlist_rename(self, ctx: Context, playlist: str, *, name: UnquotedStr):
        """Rename a playlist"""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "rename it")
        old_name = playlist.name
        playlist.rename(name)
        await ctx.send(f"**{old_name}** is now **{playlist.name}**")

    @playlist.command("description", aliases=["describe", "desc"])
    async def playlist_description(self, ctx: Context, playlist: str, *, description: UnquotedStr):
        """Describe your playlist to make it better"""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "change its description")
        playlist.set_description(description)
        em = Embed(title=f"New description of {playlist.name}:", description=description)
        await ctx.send(embed=em)

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
    async def playlist_cover_auto(self, ctx: Context, *, playlist: UnquotedStr):
        """Automatically generate a cover

        If you're too lazy to make one yourself, why not let Giesela do it?
        """
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "change its cover")

        _error: Exception = None
        covers: Dict[int, str] = {}
        cover_generator: asyncio.Task = asyncio.ensure_future(playlist.generate_cover())

        async def get_cover_page(page_index: int) -> Embed:
            nonlocal cover_generator

            relative_index = max(page_index - (min(covers) if covers else 0), 0) + 1
            total_covers = max(len(covers), relative_index)

            em = Embed(description="How about this one?", colour=Colour.orange())
            em.set_footer(text=f"Showing cover {relative_index}/{total_covers}")

            _cover = covers.get(page_index)
            if not _cover:
                em.description = "Still Generating..."
                em.colour = Colour.blue()
                await picker.edit(em)
                _cover = await cover_generator
                if not _cover:
                    em.description = "Couldn't generate cover"
                    em.colour = Colour.red()
                    return em
                cover_generator = asyncio.ensure_future(playlist.generate_cover())

                covers[page_index] = _cover
                return await get_cover_page(page_index)

            em.set_image(url=_cover)
            return em

        picker = ItemPicker(ctx.channel, ctx.author, embed_callback=get_cover_page)

        try:
            index = await picker.choose()
        except ValueError:
            raise commands.CommandError("Couldn't generate a cover...")

        if not index:
            await ctx.message.delete()
            return

        cover = covers[index]
        await playlist.set_cover(cover, no_upload=True)

        embed = Embed(description=f"This is the new face of **{playlist.name}**", colour=Colour.green())
        embed.set_image(url=playlist.cover)
        await ctx.send(embed=embed)

    @playlist.command("delete", aliases=["rm", "remove"])
    async def playlist_delete(self, ctx: Context, *, playlist: UnquotedStr):
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

        em = Embed(title=f"Transferred to {user.mention}")
        add_playlist_footer(em, playlist)
        await ctx.send(embed=em)

    @playlist.group("editor", invoke_without_command=True, aliases=["editors"])
    async def playlist_editor(self, ctx: Context, *, playlist: UnquotedStr):
        """Manage editors of a playlist."""
        playlist = self.find_playlist(playlist)

        em = Embed(title="Editors", colour=Colour.blue())
        em.set_author(name=playlist.author.display_name, icon_url=playlist.author.avatar_url)

        add_playlist_footer(em, playlist)

        if playlist.editors:
            editors_text = "\n".join(f"  - {editor.mention}" for editor in playlist.editors)
            em.description = editors_text
        else:
            em.title = "There are no editors"

        await ctx.send(embed=em)

    @playlist_editor.command("add")
    async def playlist_editor_add(self, ctx: Context, playlist: str, user: User):
        """Give someone the permission to edit your playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "add editors")

        if playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} is already an editor of **{playlist.name}**")

        playlist.add_editor(user)

        em = Embed(title=f"Added {user.display_name} as an editor")
        add_playlist_footer(em, playlist)
        await ctx.send(embed=em)

    @playlist_editor.command("remove", aliases=["rm"])
    async def playlist_editor_remove(self, ctx: Context, playlist: str, user: User):
        """Remove an editor from your playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_is_author(playlist, ctx, "remove editors")

        if not playlist.is_editor(user):
            raise commands.CommandError(f"{user.mention} isn't an editor of **{playlist.name}**")

        playlist.remove_editor(user)
        em = Embed(title=f"Removed {user.display_name} as an editor")
        add_playlist_footer(em, playlist)
        await ctx.send(embed=em)

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
                                               f"{len(playlist)} entries ({utils.format_time(playlist.total_duration)} long)\n"
                                               f"\n"
                                               f"{description}")

        # MAYBE use special viewer with play (and other) features
        viewer = EmbedViewer(ctx.channel, ctx.author, embeds=paginator)
        await viewer.display()
        await ctx.message.delete()

    @playlist.group("import", invoke_without_command=True, aliases=["imp"])
    async def playlist_import(self, ctx: Context, author: User = None):
        """Import a playlist from a GPL file."""
        if not ctx.message.attachments:
            raise commands.CommandError("Please attach a GPL file!")

        playlist_data = await save_attachment(ctx.message.attachments[0])
        try:
            embed = await self.import_playlist(playlist_data.read().decode("utf-8"), author or ctx.author)
        except KeyError:
            raise commands.CommandError("This playlist already exists. You need to delete it first before you can import it")

        if embed:
            await ctx.send("Imported playlist:", embed=embed)
        else:
            raise commands.CommandError("Couldn't load playlist\n"
                                        "If this is a playlist from an older version, please try `playlist import recover`.")

    @playlist_import.command("broken", aliases=["recover", "old"])
    async def playlist_import_broken(self, ctx: Context):
        """Import a broken playlist"""
        if not ctx.message.attachments:
            raise commands.CommandError("Please attach a GPL file!")

        data = await save_attachment(ctx.message.attachments[0])
        _gpl_data = data.read().decode("utf-8")
        try:
            gpl_data = rapidjson.loads(_gpl_data)
        except ValueError:
            raise commands.CommandError("This file is invalid. This \"playlist\" cannot be imported!")

        recovery = pl_compat.get_recovery_plan(self.playlist_manager, gpl_data)

        if not recovery:
            raise commands.CommandError("Giesela can't recover this playlist")

        recovery_ui = PlaylistRecoveryUI(ctx.channel, ctx.author, bot=ctx.bot, extractor=self.extractor, recovery=recovery)
        result = await recovery_ui.display()

        if not result:
            await ctx.message.delete()
            return

        playlist = recovery_ui.build_playlist()

        if not playlist:
            raise commands.CommandError("Couldn't recover playlist")

        try:
            self.playlist_manager.add_playlist(playlist)
        except KeyError:
            raise commands.CommandError("This playlist already exists")

        embed = playlist_embed(playlist)
        await ctx.send("Imported playlist:", embed=embed)

    @playlist.command("export")
    async def playlist_export(self, ctx: Context, *, playlist: UnquotedStr):
        """Export a playlist"""
        playlist = self.find_playlist(playlist)

        serialised = rapidjson.dumps(playlist.to_gpl())
        data = BytesIO(serialised.encode("utf-8"))
        data.seek(0)
        file = File(data, filename=f"{playlist.name.lower()}.gpl{GPL_VERSION}")
        await ctx.send("Here you go", file=file)

    @playlist.command("search", aliases=["contains", "has", "find"])
    async def playlist_search(self, ctx: Context, playlist: str, *, query: str):
        """Check whether a playlist contains an entry"""
        playlist = self.find_playlist(playlist)
        entries = list(playlist.search_all_entries(query, threshold=.5))
        if not entries:
            raise commands.CommandError(f"Couldn't find \"{query}\"")
        entries.sort(key=operator.itemgetter(1), reverse=True)
        entries = next(zip(*entries[:10]))
        indices = list(map(playlist.index_of, entries))
        pad_length = len(str(max(indices)))

        lines = []
        for i, entry in enumerate(entries):
            index = str(indices[i] + 1).rjust(pad_length, "0")
            title = textwrap.shorten(entry.title, 50)
            line = f"• `{index}.` {title}"
            lines.append(line)

        em = Embed(title=f"Found the following entries", description="\n".join(lines), colour=Colour.blue())
        add_playlist_footer(em, playlist)
        await ctx.send(embed=em)

    @commands.command("addtoplaylist", aliases=["quickadd", "pladd", "pl+"])
    async def playlist_quickadd(self, ctx: Context, *, playlist: UnquotedStr):
        """Add the current entry to a playlist."""
        playlist = self.find_playlist(playlist)
        await ensure_user_can_edit_playlist(playlist, ctx)

        player = await self.player_cog.get_player(ctx)
        player_entry = player.current_entry
        if not player_entry:
            raise commands.CommandError("There's nothing playing right now")

        entry = player_entry.entry

        similar_pl_entry = playlist.search_entry(str(entry))
        if similar_pl_entry:
            prompt = PromptYesNo(ctx.channel, user=ctx.author,
                                 text=f"\"{entry}\" might already be in this playlist (\"{similar_pl_entry.entry}\"), "
                                      f"are you sure you want to add it again?")
            if not await prompt:
                await ctx.message.delete()
                return

        playlist_entry = playlist.add_entry(entry, ctx.author)
        if not player_entry.has_wrapper(LoadedPlaylistEntry):
            player_entry.lowest_wrapper.add_wrapper(LoadedPlaylistEntry.create(playlist_entry))

        em = Embed(title=f"Added **{entry}**", colour=Colour.green())
        add_playlist_footer(em, playlist)

        await ctx.send(embed=em)

    @commands.command("removefromplaylist", aliases=["quickremove", "quickrm", "plremove", "plrm", "pl-"])
    async def playlist_quickremove(self, ctx: Context, *, playlist: UnquotedStr = None):
        """Remove the current entry from a playlist."""
        player = await self.player_cog.get_player(ctx)
        player_entry = player.current_entry
        if not player_entry:
            raise commands.CommandError("There's nothing playing right now")

        entry = player_entry.entry

        if playlist:
            playlist = self.find_playlist(playlist)
            playlist_entry = playlist.search_entry(entry.track, threshold=1)
            if not playlist_entry:
                raise commands.CommandError(f"Couldn't find {entry} in {playlist.name}")
        else:
            playlist = player_entry.get("playlist", None)
            if not playlist:
                raise commands.CommandError("This entry isn't part of a playlist."
                                            "You cannot remove it unless you specify the name!")
            playlist_entry = player_entry.get("playlist_entry")

        await ensure_user_can_edit_playlist(playlist, ctx)

        playlist.remove(playlist_entry)
        player_entry.remove_wrapper(LoadedPlaylistEntry)

        em = Embed(title=f"Removed **{entry}**", colour=Colour.green())
        add_playlist_footer(em, playlist)

        await ctx.send(embed=em)


def setup(bot: Giesela):
    PlaylistCog.__name__ = "Playlist"
    bot.add_cog(PlaylistCog(bot))
