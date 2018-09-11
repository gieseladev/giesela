import asyncio
from typing import List, NamedTuple, Optional, Type

import aiohttp
from discord import Colour, Embed, TextChannel
from discord.ext import commands
from discord.ext.commands import Context

from giesela import BaseEntry, BasicEntry, ChapterEntry, Giesela, PlayableEntry, SpecificChapterData, utils
from .. import text as text_utils
from ..help import AutoHelpEmbed
from ..interactive import InteractableEmbed, MessageableEmbed, VerticalTextViewer, emoji_handler


class EditBase(BaseEntry):
    def __init__(self, base, *, title: str, artist: str = None, artist_image: str = None, album: str = None, cover: str = None, **kwargs):
        self.base = base

        self.title = title
        self.artist = artist
        self.artist_image = artist_image
        self.album = album
        self.cover = cover

    @classmethod
    def from_entry(cls, entry: BaseEntry):
        return cls(entry, **entry.to_dict())

    def determine_type(self):
        return BaseEntry

    def build(self) -> BasicEntry:
        kwargs = self.base.to_dict()
        kwargs.update(self.to_dict())

        cls = self.determine_type()
        return cls.from_dict(kwargs)

    def get_embed(self) -> Embed:
        em = Embed(title=self.title)
        em.set_author(name=self.artist or "Unknown Artist", icon_url=self.artist_image or Embed.Empty)
        if self.cover:
            em.set_thumbnail(url=self.cover)
        if self.album:
            em.add_field(name="Album", value=self.album)
        return em


class EditChapter(SpecificChapterData, EditBase):
    def __init__(self, base: SpecificChapterData, **kwargs):
        self.base = base
        super().__init__(**kwargs)

    def determine_type(self):
        return SpecificChapterData

    def get_embed(self) -> Embed:
        embed = super().get_embed()
        fields = getattr(embed, "_fields", False)
        if fields:
            fields[-1].update(inline=False)

        embed.add_field(name="Start", value=utils.to_timestamp(self.start))
        embed.add_field(name="Duration", value=utils.to_timestamp(self.duration))
        embed.add_field(name="End", value=utils.to_timestamp(self.end))
        return embed


class SurroundingChapter(NamedTuple):
    previous: Optional[SpecificChapterData]
    index: int
    next: Optional[SpecificChapterData]


class EditEntry(EditBase):
    chapters: List[SpecificChapterData]

    def __init__(self, base: PlayableEntry, *, chapters: List[SpecificChapterData] = None, **kwargs):
        super().__init__(base, **kwargs)

        self.chapters = chapters or []

    def get_surrounding_chapters(self, start: float) -> SurroundingChapter:
        i = 0
        prev_chapter = next_chapter = None

        for i, prev_chapter in enumerate(self.chapters, 1):
            if start >= prev_chapter.end:
                if i + 1 < len(self.chapters):
                    next_chapter = self.chapters[i + 1]
                break
        else:
            if self.chapters:
                _chapter = self.chapters[0]
                if start > _chapter.start:
                    prev_chapter = _chapter
                    i = 1
                    next_chapter = self.chapters[1] if len(self.chapters) > 1 else None
                else:
                    i = 0
                    prev_chapter = None
                    next_chapter = _chapter

        return SurroundingChapter(prev_chapter, i, next_chapter)

    def add_chapter(self, chapter: SpecificChapterData) -> int:
        surrounding = self.get_surrounding_chapters(chapter.start)
        index = surrounding.index

        if surrounding.previous:
            for prev_chapter in self.chapters[index - 1:: -1]:
                if chapter.start >= prev_chapter.end:
                    break
                prev_chapter.end = chapter.start

        if surrounding.next:
            for next_chapter in self.chapters[index:]:
                if next_chapter.start >= chapter.end:
                    break
                next_chapter.start = chapter.end

        self.chapters.insert(index, chapter)

        for chapter in reversed(self.chapters):
            if chapter.duration <= 0:
                self.chapters.remove(chapter)

        return min(index, len(self.chapters) - 1)

    @classmethod
    def from_entry(cls, entry: PlayableEntry):
        kwargs = {}

        if isinstance(entry, BaseEntry):
            kwargs.update(entry.to_dict())
        if isinstance(entry, ChapterEntry):
            kwargs["chapters"] = [chapter.copy() for chapter in entry.chapters]

        kwargs.setdefault("title", entry.uri)
        kwargs["url"] = entry.url

        return cls(entry, **kwargs)

    def determine_type(self) -> Type[BasicEntry]:
        if self.chapters:
            return ChapterEntry
        else:
            return BasicEntry

    def to_dict(self):
        data = super().to_dict()
        if self.chapters:
            data["chapters"] = [chapter.to_dict() for chapter in self.chapters]
        return data

    def get_embed(self) -> Embed:
        em = super().get_embed()
        em.url = self.base.url or Embed.Empty
        return em


class _BaseEditor(AutoHelpEmbed, InteractableEmbed, MessageableEmbed):
    bot: Giesela
    aiosession: aiohttp.ClientSession

    def __init__(self, channel: TextChannel, *, editor: EditBase, **kwargs):
        super().__init__(channel, **kwargs)

        self.editor = editor

        self.aiosession = getattr(self.bot, "aiosession", False) or aiohttp.ClientSession()

    @property
    def edited(self):
        return self.editor.build()

    async def display(self):
        await self.update()
        result = await self.wait_for_listener()
        await self.delete()
        return result

    def get_embed(self) -> Embed:
        embed = self.editor.get_embed()
        if self.error:
            embed.colour = Colour.red()
            embed.add_field(name="Error", value=f"**{self.error}**", inline=False)
            self.error = None
        return embed

    async def update(self):
        embed = self.get_embed()
        await self.edit(embed)

    async def on_command_error(self, ctx: Optional[Context], exception: Exception):
        await super().on_command_error(ctx, exception)
        await self.update()

    async def on_emoji_handler_error(self, error: Exception, *_):
        await self.on_command_error(None, error)

    async def search_for_image(self, query: str) -> str:
        api_key = self.bot.config.app.tokens.google_api
        image = await utils.search_image(self.aiosession, api_key, query, min_squareness=.8)
        if not image:
            raise commands.CommandError("Couldn't find an image")
        return image

    async def assert_save_possible(self) -> bool:
        return True

    @emoji_handler("💾", pos=999)
    async def save_changes(self, *_):
        """Apply changes and close"""
        if not await self.assert_save_possible():
            return

        self.stop_listener()
        return self.edited

    @emoji_handler("❎", pos=1000)
    async def abort(self, *_) -> None:
        """Close without applying changes"""
        self.stop_listener()
        return None

    @commands.command("title", aliases=["name"])
    async def set_title(self, _, *title: str):
        """Set the title"""
        title = " ".join(title)
        self.editor.title = title
        await self.update()

    @commands.group("artist", invoke_without_command=True)
    async def set_artist(self, _, *name: str):
        """Set the artist name"""
        name = " ".join(name)
        self.editor.artist = name
        await self.update()

    @set_artist.group("image", invoke_without_command=True)
    async def set_artist_image(self, _, image: str):
        """Set the artist image"""
        if not await utils.content_is_image(self.aiosession, image):
            raise commands.CommandError("This doesn't look like an image, sorry!")

        self.editor.artist_image = image
        await self.update()

    @set_artist_image.command("auto", aliases=["search"])
    async def set_artist_image_auto(self, _, *query: str):
        """Search for an artist image"""
        if query:
            query = " ".join(query)
        else:
            if self.editor.artist:
                query = self.editor.artist
            else:
                raise commands.CommandError("Please set the name of the artist first!")
        self.editor.artist_image = await self.search_for_image(query)
        await self.update()

    @commands.group("cover", invoke_without_command=True, aliases=["image"])
    async def set_cover(self, _, cover: str):
        """Set the cover"""
        if not await utils.content_is_image(self.aiosession, cover):
            raise commands.CommandError("This doesn't look like an image, sorry!")

        self.editor.cover = cover
        await self.update()

    @set_cover.command("auto", aliases=["search"])
    async def set_cover_auto(self, _, *query: str):
        """Search for a cover"""
        if query:
            query = " ".join(query)
        else:
            if self.editor.artist:
                query = f"{self.editor.title} - {self.editor.artist}"
            else:
                query = self.editor.title
        self.editor.cover = await self.search_for_image(query)
        await self.update()

    @commands.command("album")
    async def set_album(self, _, *album: str):
        """Set the album"""
        album = " ".join(album)
        self.editor.album = album
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
        elif field == "images":
            await asyncio.gather(self.set_cover_auto.invoke(ctx),
                                 self.set_artist_image_auto.invoke(ctx))
        else:
            raise commands.CommandError("Can only automatically set image fields")


class ChapterEditor(_BaseEditor):
    editor: EditChapter

    def __init__(self, channel: TextChannel, *, entry_editor: EditEntry, chapter: SpecificChapterData, **kwargs):
        self.entry_editor = entry_editor
        editor = EditChapter.from_entry(chapter)
        super().__init__(channel, editor=editor, **kwargs)

    @classmethod
    def parse_time_value(cls, value: str):
        timestamp = utils.parse_timestamp(value)
        if timestamp is None:
            raise commands.CommandError(f"Couldn't parse timestamp {value}")
        return timestamp

    async def set_timestamp(self, name: str, timestamp: float):
        setattr(self.editor, name, timestamp)
        await self.update()

    @commands.command("start")
    async def set_start(self, _, start: str):
        """Set chapter start"""
        timestamp = self.parse_time_value(start)
        if timestamp >= self.editor.end:
            raise commands.CommandError("start must not be bigger than end")

        if timestamp >= self.entry_editor.base.duration:
            raise commands.CommandError("start must not exceed entry duration")

        await self.set_timestamp("start", timestamp)

    async def _set_end(self, timestamp: float):
        if timestamp <= self.editor.start:
            raise commands.CommandError("duration must not be 0 or less")
        if timestamp > self.entry_editor.base.duration:
            raise commands.CommandError("end must not exceed entry duration")
        await self.set_timestamp("end", timestamp)

    async def assert_save_possible(self):
        if self.editor.duration <= 0:
            raise commands.CommandError("Duration must not be 0 or less!")
        if self.editor.start > self.entry_editor.base.duration:
            raise commands.CommandError("Start must not exceed entry duration")
        if self.editor.end > self.entry_editor.base.duration:
            raise commands.CommandError("End must not exceed entry duration")
        return await super().assert_save_possible()

    @commands.command("duration")
    async def set_duration(self, _, duration: str):
        """Set chapter duration"""
        timestamp = self.parse_time_value(duration)
        await self._set_end(self.editor.start + timestamp)

    @commands.command("end")
    async def set_end(self, _, end: str):
        """Set chapter end"""
        timestamp = self.parse_time_value(end)
        await self._set_end(timestamp)


class EntryEditor(VerticalTextViewer, _BaseEditor):
    editor: EditEntry

    def __init__(self, channel: TextChannel, *, entry: PlayableEntry, **kwargs):
        self._entry = entry
        editor = EditEntry.from_entry(entry)
        super().__init__(channel, editor=editor, **kwargs)

    @property
    def original(self):
        return self._entry

    @property
    def total_lines(self) -> int:
        return len(self.editor.chapters)

    @property
    def embed_frame(self) -> Embed:
        return self.get_embed()

    def get_embed(self) -> Embed:
        embed = super().get_embed()
        if self.editor.chapters:
            field = dict(inline=False, name="Chapters", value="{progress_bar}")
            fields = getattr(embed, "_fields", None)
            if fields is None:
                embed.add_field(**field)
            else:
                fields.insert(0, field)
        return embed

    def get_chapter_editor(self, chapter: SpecificChapterData) -> ChapterEditor:
        return ChapterEditor(channel=self.channel, entry_editor=self.editor, chapter=chapter, user=self.user, bot=self.bot)

    async def get_line(self, line: int) -> str:
        chapter = self.editor.chapters[line]

        index = text_utils.keep_whitespace(f"{line + 1}.".ljust(len(str(self.total_lines))))

        from_ts = utils.to_timestamp(chapter.start) if chapter.start > 0 else "start"
        to_ts = utils.to_timestamp(chapter.end) if chapter.end < self.editor.base.duration else "end"

        return f"`{index}` [`{from_ts}` - `{to_ts}`] {chapter}"

    async def update(self):
        await self.show_window()

    async def edit_chapter(self, chapter: SpecificChapterData) -> bool:
        editor = self.get_chapter_editor(chapter)
        chapter = await editor.display()
        if not chapter:
            return False

        index = self.editor.add_chapter(chapter)
        await self.show_line(index)
        return True

    @commands.group(invoke_without_command=True)
    async def chapter(self, _, chapter: int):
        """Inspect a chapter"""
        chapter -= 1
        if not 0 <= chapter < len(self.editor.chapters):
            raise commands.CommandError("Chapter doesn't exist")

        chapter = self.editor.chapters.pop(chapter)
        if not await self.edit_chapter(chapter):
            self.editor.add_chapter(chapter)

    @chapter.command("add", aliases=["create"])
    async def chapter_add(self, _):
        """Create a new chapter"""

        title = f"Chapter {len(self.editor.chapters) + 1}"
        start = 0
        end = self.editor.base.duration
        if self.editor.chapters:
            last_chapter = self.editor.chapters[-1]
            start = last_chapter.end

        chapter = SpecificChapterData(title=title, start=start, end=end)
        await self.edit_chapter(chapter)

    @chapter.command("remove", aliases=["rm"])
    async def chapter_remove(self, _, chapter: int):
        """Remove a chapter"""
        chapter -= 1
        if not 0 <= chapter < len(self.editor.chapters):
            raise commands.CommandError("Chapter doesn't exist")

        self.editor.chapters.pop(chapter)
        await self.update()
