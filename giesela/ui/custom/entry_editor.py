import functools
from typing import Dict, List, Optional

import aiohttp
from discord import Colour, Embed, TextChannel, User
from discord.embeds import EmptyEmbed
from discord.ext import commands
from discord.ext.commands import Context

from giesela import BaseEntry, GieselaEntry, utils
from ..help import AutoHelpEmbed
from ..interactive import InteractableEmbed, MessageableEmbed, emoji_handler
from ..prompts import PromptYesNo


class EditableEntryData:
    song_title: str
    artist: Optional[str]
    artist_image: Optional[str]
    cover: Optional[str]
    album: Optional[str]

    _attrs = ("song_title", "artist", "artist_image", "cover", "album")
    _dirty = List[str]

    def __init__(self, song_title: str, artist: str = None, artist_image: str = None, cover: str = None, album: str = None):
        self._song_title = song_title
        self._artist = artist
        self._artist_image = artist_image
        self._cover = cover
        self._album = album

        self._dirty = []

    def __getattr__(self, item: str) -> str:
        if item in self._attrs:
            return getattr(self, f"_{item}")
        raise AttributeError

    def __setattr__(self, name: str, value: str):
        if name in self._attrs:
            self._dirty.append(name)

        super().__setattr__(name, value)

    @property
    def is_complete(self) -> bool:
        func = functools.partial(getattr, self)
        # noinspection PyTypeChecker
        return all(map(func, self._attrs))

    @property
    def is_dirty(self) -> bool:
        return bool(self._dirty)

    @property
    def missing_attrs(self) -> List[str]:
        return [attr for attr in self._attrs if not getattr(self, attr)]

    @classmethod
    def from_entry(cls, entry: BaseEntry) -> "EditableEntryData":
        if isinstance(entry, GieselaEntry):
            return cls(entry.song_title, entry.artist, entry.artist_image, entry.cover, entry.album)

        editor = cls(entry.title)
        info = utils.split_song_name(entry)
        editor.song_title = info.name
        editor.artist = info.artist
        return editor

    def reset_attr(self, attr: str):
        if attr in self._dirty:
            delattr(self, attr)
            self._dirty.remove(attr)

    def get_embed(self) -> Embed:
        embed = Embed()
        embed.add_field(name="Title", value=self.song_title)
        embed.set_author(name=self.artist or "Unknown Artist", icon_url=self.artist_image or EmptyEmbed)
        embed.add_field(name="Album", value=self.album or "Unknown Album")
        if self.cover:
            embed.set_thumbnail(url=self.cover)

        if self.is_complete:
            footer_text = "This entry is complete"
            embed.colour = Colour.green()
        else:
            missing = ", ".join(attr.replace("_", " ").title() for attr in self.missing_attrs)
            footer_text = f"The following things are missing: {missing}"
        embed.set_footer(text=footer_text)

        return embed

    def get_changes(self) -> Dict[str, str]:
        return {dirty_attr: getattr(self, dirty_attr) for dirty_attr in self._dirty}


class EntryEditor(AutoHelpEmbed, MessageableEmbed, InteractableEmbed):
    _entry: BaseEntry
    entry: EditableEntryData

    aiosession: aiohttp.ClientSession

    def __init__(self, channel: TextChannel, user: User = None, **kwargs):
        self._entry = kwargs.pop("entry")
        super().__init__(channel, user, **kwargs)

        self.entry = EditableEntryData.from_entry(self._entry)
        self.aiosession = getattr(self.bot, "aiosession", False) or aiohttp.ClientSession()

    @property
    def original_entry(self) -> BaseEntry:
        return self._entry

    @property
    def changed_entry(self) -> Optional[GieselaEntry]:
        if self.entry.is_complete:
            return GieselaEntry.upgrade(self._entry, **self.entry.get_changes())

    @property
    def help_title(self) -> str:
        return "Entry Editor Help"

    async def display(self) -> Optional[GieselaEntry]:
        await self.update()
        result = await self.wait_for_listener()
        await self.delete()
        return result

    async def update(self):
        embed = self.entry.get_embed()
        embed.title = "open url"
        embed.url = self._entry.url
        if self.error:
            embed.colour = Colour.red()
            embed.add_field(name="Error", value=f"**{self.error}**", inline=False)
            self.error = None

        await self.edit(embed)

    async def on_command_error(self, ctx: Context, exception: Exception):
        await super().on_command_error(ctx, exception)
        await self.update()

    async def search_for_image(self, query: str) -> str:
        image = await utils.search_image(self.aiosession, query, min_squareness=.8)
        if not image:
            raise commands.CommandError("Couldn't find an image")
        return image

    @emoji_handler("💾", pos=999)
    async def save_changes(self, _, user: User) -> Optional[GieselaEntry]:
        """Apply changes and close"""
        if self.entry.is_dirty and not self.entry.is_complete:
            prompt = PromptYesNo(self.channel, user=user,
                                 text="This entry isn't complete yet, all changes will be discarded. Are you sure you want to quit?")
            if not await prompt:
                return

        self.stop_listener()
        return self.changed_entry

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Close without applying changes"""
        self.stop_listener()
        return None

    @commands.command("title", aliases=["name"])
    async def set_title(self, _, *title: str):
        """Set the title"""
        title = " ".join(title)
        self.entry.song_title = title
        await self.update()

    @commands.group("artist", invoke_without_command=True)
    async def set_artist(self, _, *name: str):
        """Set the artist name"""
        name = " ".join(name)
        self.entry.artist = name
        await self.update()

    @set_artist.group("image", invoke_without_command=True)
    async def set_artist_image(self, _, image: str):
        """Set the artist image"""
        if not await utils.content_is_image(self.aiosession, image):
            raise commands.CommandError("This doesn't look like an image, sorry!")

        self.entry.artist_image = image
        await self.update()

    @set_artist_image.command("auto", aliases=["search"])
    async def set_artist_image_auto(self, _, query: str = None):
        """Search for an artist image"""
        if not query:
            if self.entry.artist:
                query = self.entry.artist
            else:
                raise commands.CommandError("Please set the name of the artist first!")
        self.entry.artist_image = await self.search_for_image(query)
        await self.update()

    @commands.group("cover", invoke_without_command=True, aliases=["image"])
    async def set_cover(self, _, cover: str):
        """Set the cover"""
        if not await utils.content_is_image(self.aiosession, cover):
            raise commands.CommandError("This doesn't look like an image, sorry!")

        self.entry.cover = cover
        await self.update()

    @set_cover.command("auto", aliases=["search"])
    async def set_cover_auto(self, _, query: str = None):
        """Search for a cover"""
        if not query:
            if self.entry.artist:
                query = f"{self.entry.song_title} - {self.entry.artist}"
            else:
                query = self.entry.song_title
        self.entry.cover = await self.search_for_image(query)
        await self.update()

    @commands.command("album")
    async def set_album(self, _, *album: str):
        """Set the album"""
        album = " ".join(album)
        self.entry.album = album
        await self.update()

    @commands.command("auto")
    async def auto_set(self, ctx: Context, *field: str):
        """Set an image automatically"""
        field = " ".join(field)

        ctx.args.clear()
        ctx.kwargs.clear()
        if field == "cover":
            await self.set_cover_auto.invoke(ctx)
        elif field in ("artist image", "artist img"):
            await self.set_artist_image_auto.invoke(ctx)
        else:
            raise commands.CommandError("Can only automatically set image fields")
