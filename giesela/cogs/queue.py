import random
import time
from typing import Dict

from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, GieselaPlayer
from giesela.ui import VerticalTextViewer
from giesela.ui.custom import EntrySearchUI, NowPlayingEmbed
from giesela.utils import (format_time, nice_cut)
from .player import Player

LOAD_ORDER = 1


class QueueBase:
    bot: Giesela

    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.cogs["Player"]
        self.get_player = self.player_cog.get_player


async def _play_cmd(ctx: Context, player: GieselaPlayer, target: str, placement: int = None):
    entry = await player.extractor.get_entry(target)
    print(entry)
    player.queue.add_entry(entry, ctx.author, placement=placement)


class EnqueueCog(QueueBase):

    @commands.command()
    async def stream(self, ctx: Context, url: str):
        """Enqueue a media stream.

        This could mean an actual stream like Twitch, Youtube Gaming or even a radio stream, or simply streaming
        media without predownloading it.
        """
        player = await self.get_player(ctx)
        song_url = url.strip("<>")

        async with ctx.typing():
            entry = await player.downloader.get_stream_entry(song_url, author=ctx.author)
            player.queue.add_entry(entry)
        await ctx.send(":+1:")

    async def _play_cmd(self, ctx: Context, url: str, placement: int = None):
        player = await self.get_player(ctx)

        await _play_cmd(ctx, player, url, placement)

    @commands.group(invoke_without_command=True, aliases=["p", "enqueue"])
    async def play(self, ctx: Context, *, url: str):
        """Add an entry to the queue

        If no link is provided, the first
        result from a youtube search is added to the queue.
        """
        await self._play_cmd(ctx, url)

    @play.command("next")
    async def play_next(self, ctx: Context, *, url: str):
        """Add an entry to the front of the queue"""
        await self._play_cmd(ctx, url, placement=0)

    @play.command("random", aliases=["soon", "anytime"])
    async def play_random(self, ctx: Context, *, url: str):
        """Add an entry at a random position"""
        player = await self.get_player(ctx)

        placement = random.randrange(0, len(player.queue))
        await self._play_cmd(ctx, url, placement=placement)

    @commands.command()
    async def search(self, ctx: Context, *, query: str):
        """Searches for a video and adds the one you choose."""
        player = await self.get_player(ctx)

        async with ctx.typing():
            results = await player.downloader.get_entries_from_query(query, author=ctx.author)
        searcher = EntrySearchUI(ctx.channel, player, results, user=ctx.author, bot=self.bot)

        entry = await searcher.choose()
        if entry:
            player.queue.add_entry(entry)
            await ctx.send(f"Enqueued **{entry.title}**")
        else:
            await ctx.message.delete()


class ManipulateCog(QueueBase):

    # @commands.command()
    # async def remove(self, ctx: Context, index: int):
    #     """Remove an entry from the queue."""
    #     player = await self.get_player(ctx)
    #
    #     if not player.queue.entries:
    #         raise commands.CommandError("There are no entries in the queue!")
    #
    #     index -= 1
    #
    #     if not 0 <= index < len(player.queue.entries):
    #         raise commands.CommandError("This index cannot be found in the queue")
    #
    #     title = player.queue.entries[index].title
    #     del player.queue.entries[index]
    #     WebieselaServer.send_player_information(ctx.guild.id)
    #     await ctx.send(f"Removed **{title}** from the queue")

    @commands.command()
    async def replay(self, ctx: Context, index: str = None):
        """Replay an entry.

        If there's nothing playing, or the "last" keyword is given, replay the last song.
        Otherwise replay the nth entry in the history.
        """
        player = await self.get_player(ctx)

        if index:
            if index.isnumeric():
                index = int(index) - 1
            elif index in ("previous", "last"):
                index = 0
            else:
                raise commands.CommandError("No idea what you're trying to replay")

        if index is not None or not player.current_entry:
            index = index or 0
            if not player.queue.history:
                raise commands.CommandError("No history to replay!")
            elif not 0 <= index < len(player.queue.history):
                raise commands.CommandError("Can't find that index")
            entry = player.queue.history[index]
        elif player.current_entry:
            entry = player.current_entry
        else:
            raise commands.CommandError("Nothing to replay")

        if player.queue.replay(index):
            await ctx.send(f"Replaying **{entry.title}**")
        else:
            raise commands.CommandError(f"Couldn't replay {entry.title}!")

    @commands.command()
    async def shuffle(self, ctx: Context):
        """Shuffle the queue."""
        player = await self.get_player(ctx)
        player.queue.shuffle()
        await ctx.send(":ok_hand:")

    @commands.command()
    async def clear(self, ctx: Context):
        """Clear the queue."""
        player = await self.get_player(ctx)
        player.queue.clear()
        await ctx.send(":put_litter_in_its_place:")

    @commands.command()
    async def skip(self, ctx: Context, skip: str = None):
        """Skip the current song.

        When given the keyword "all", skips all timestamped-entries in the current timestamp-entry.
        """
        player = await self.get_player(ctx)

        if player.is_stopped:
            raise commands.CommandError("Can't skip! The player is not playing!")

        skip_to_next = skip == "all"
        await player.skip()

    @commands.command()
    async def promote(self, ctx: Context, position: int = None):
        """Promote an entry.

        If you don-t specify a position, it promotes the last song.
        """
        player = await self.get_player(ctx)

        if len(player.queue.entries) < 2:
            raise commands.CommandError("Can't promote! Please add at least 2 songs to the queue!")

        if position is not None:
            position -= 1
            if not 0 < position < len(player.queue.entries):
                raise commands.CommandError("Index out of range")
            entry = player.queue.promote_position(position)
        else:
            entry = player.queue.promote_last()

        await ctx.send(f"Promoted **{entry.title}** to the :top: of the queue.")

    @commands.command()
    async def move(self, ctx: Context, from_pos: int, to_pos: int):
        """Move an entry."""
        player = await self.get_player(ctx)

        from_index = from_pos - 1
        to_index = to_pos - 1

        queue_length = len(player.queue.entries)

        if not 0 <= from_index < queue_length:
            raise commands.CommandError("`from_pos` must be between 1 and {}".format(queue_length))

        if not 0 <= to_index < queue_length:
            raise commands.CommandError("`to_pos` must be between 1 and {}".format(queue_length))

        entry = player.queue.move(from_index, to_index)
        await ctx.send(f"Moved **{entry.title}** from position `{from_pos}` to `{to_pos}`.")


class DisplayCog(QueueBase):
    np_messages: Dict[int, NowPlayingEmbed]

    def __init__(self, bot: Giesela):
        super().__init__(bot)

        self.np_messages = {}

    @commands.command()
    async def np(self, ctx: Context):
        """Show the current entry."""
        np_embed = self.np_messages.get(ctx.guild.id)
        if np_embed:
            await np_embed.delete()

        player = await self.get_player(ctx)
        np_embed = NowPlayingEmbed(ctx.channel, player)
        self.np_messages[ctx.guild.id] = np_embed

        await np_embed.start()

    # @commands.command()
    # async def queue(self, ctx: Context):
    #     """Display the queue."""
    #     player = await self.get_player(ctx)
    #
    #     lines = []
    #
    #     if player.current_entry and isinstance(player.current_entry, TimestampEntry):
    #         sub_queue = player.current_entry.sub_queue
    #         sub_queue = [sub_entry for sub_entry in sub_queue if sub_entry["start"] >= player.progress]
    #         for item in sub_queue:
    #             lines.append(
    #                 "            ►`{}.` **{}**".format(
    #                     item["index"] + 1,
    #                     nice_cut(item["name"], 35)
    #                 )
    #             )
    #
    #     for i, item in enumerate(player.queue.entries, 1):
    #         origin_text = ""
    #         if "playlist" in item.meta:
    #             origin_text = "from playlist **{}**".format(item.meta["playlist"].name)
    #         elif "author" in item.meta:
    #             origin_text = "by **{}**".format(item.meta["author"].name)
    #
    #         lines.append("`{}.` **{}** {}".format(i, nice_cut(item.title, 40), origin_text))
    #
    #     if not lines:
    #         raise commands.CommandError("No entries in the queue")
    #
    #     total_time = sum([entry.duration for entry in player.queue.entries])
    #     if player.current_entry:
    #         total_time += player.current_entry.duration - player.progress
    #
    #     frame = {
    #         "title": "Queue",
    #         "author": {
    #             "name": "{progress_bar}"
    #         },
    #         "footer": {
    #             "text": f"Total duration: {format_time(total_time, True, 5, 2)}"
    #
    #         }
    #     }
    #
    #     viewer = VerticalTextViewer(ctx.channel, ctx.author, content=lines, embed_frame=frame)
    #     await viewer.display()
    #     await ctx.message.delete()

    @commands.command()
    async def history(self, ctx: Context):
        """Show the past entries"""
        player = await self.get_player(ctx)
        lines = []

        for ind, entry in enumerate(player.queue.history, 1):
            finish_time = entry.meta.get("finish_time")
            seconds_passed = time.time() - finish_time
            lines.append(
                "`{}.` **{}** {} ago".format(
                    ind,
                    nice_cut(entry.title, 40),
                    format_time(seconds_passed, max_specifications=2)
                )
            )

        if not lines:
            raise commands.CommandError("No history")

        frame = {
            "title": "History",
            "author": {
                "name": "{progress_bar}"
            }
        }

        viewer = VerticalTextViewer(ctx.channel, ctx.author, content=lines, embed_frame=frame)
        await viewer.display()
        await ctx.message.delete()


class Queue(EnqueueCog, ManipulateCog, DisplayCog):
    pass


def setup(bot: Giesela):
    bot.add_cog(Queue(bot))
