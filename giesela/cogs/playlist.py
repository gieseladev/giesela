import json
from io import BytesIO

from discord import Colour, Embed, File
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, PlaylistManager, utils
from giesela.lib.ui import EmbedPaginator, EmbedViewer

LOAD_ORDER = 1


class Playlist:
    bot: Giesela
    playlist_manager: PlaylistManager

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.playlist_manager = PlaylistManager.load(self.bot, self.bot.config.playlists_file)

    @commands.group(invoke_without_command=True, aliases=["pl"])
    async def playlist(self, ctx: Context):
        """Playlist stuff"""

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
        embed.set_author(name="Loaded the following playlists")

        for attachment in ctx.message.attachments:
            playlist_data = BytesIO()
            await attachment.save(playlist_data)
            playlist = self.playlist_manager.import_from_gpl(playlist_data.read().decode("utf-8"))
            if playlist:
                embed.add_field(name=playlist.name, value=f"by {playlist.author.name}\n{len(playlist)} entries")
        if not embed.fields:
            raise commands.CommandError("Couldn't load any playlists")

        await ctx.send(embed=embed)

    @playlist.command("export")
    async def playlist_export(self, ctx: Context, playlist: str):
        """Export a playlist"""
        _playlist = self.playlist_manager.find_playlist(playlist)
        if not _playlist:
            raise commands.CommandError(f"No playlist found for \"{playlist}\"")

        serialised = json.dumps(_playlist.to_gpl(), indent=None, separators=(",", ":"))
        data = BytesIO(serialised.encode("utf-8"))
        data.seek(0)
        file = File(data, filename=f"{_playlist.name}.gpl")
        await ctx.send("Here you go", file=file)


def setup(bot: Giesela):
    bot.add_cog(Playlist(bot))
