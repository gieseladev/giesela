import random
import time
from datetime import datetime

from discord.ext import commands
from discord.ext.commands import Context

from giesela import Extractor, Giesela, utils
from giesela.ui import VerticalTextViewer, prefab, text as text_utils
from giesela.ui.custom import EntrySearchUI
from .player import Player

LOAD_ORDER = 1


class QueueBase:
    bot: Giesela

    get_player: Player.get_player
    extractor: Extractor

    def __init__(self, bot: Giesela):
        self.bot = bot

        self.get_player = self.bot.get_player
        self.extractor = self.bot.extractor


def pad_index(index: int, padding: int) -> str:
    padded_index = text_utils.keep_whitespace(f"{index}.".ljust(padding))
    return text_utils.wrap(padded_index, "`")


class EnqueueCog(QueueBase):
    async def _play_cmd(self, ctx: Context, target: str, placement: int = None):
        player = await self.get_player(ctx)

        async with ctx.typing():
            result = await self.extractor.get(target)

        if not result:
            raise commands.CommandError(f"Couldn't find anything for {target}")

        if isinstance(result, list):
            player.queue.add_entries(result, requester=ctx.author, placement=placement)
            await ctx.send(f"Added {len(result)} entries to the queue")
        else:
            player.queue.add_entry(result, requester=ctx.author, placement=placement)
            await ctx.send(f"Added **{result}** to the queue")

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
            results = await self.extractor.search_entries(query)
        searcher = EntrySearchUI(ctx.channel, player=player, results=results, user=ctx.author, bot=self.bot)

        entry = await searcher.choose()
        if entry:
            player.queue.add_entry(entry, ctx.author)
            await ctx.send(f"Enqueued **{entry.title}**")
        else:
            await ctx.message.delete()


class ManipulateCog(QueueBase):

    @commands.group(invoke_without_command=True, aliases=["rm"])
    async def remove(self, ctx: Context, index: int):
        """Remove an entry from the queue."""
        player = await self.get_player(ctx)

        index -= 1

        if not 0 <= index < len(player.queue.entries):
            raise commands.CommandError("This index cannot be found in the queue")

        entry = player.queue.remove(index)
        await ctx.send(f"Removed **{entry.entry}** from the queue")

    @remove.command("last")
    async def remove_last(self, ctx: Context):
        """Remove the last entry"""
        player = await self.get_player(ctx)
        if not player.queue.entries:
            raise commands.CommandError("No entries in the queue")

        index = len(player.queue) - 1
        entry = player.queue.remove(index)
        await ctx.send(f"Removed **{entry.entry}** from the queue")

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

            entry = player.queue.history[index].entry

        elif player.current_entry:
            entry = player.current_entry.entry

        else:
            raise commands.CommandError("Nothing to replay")

        if player.queue.replay(ctx.author, index):
            await ctx.send(f"Replaying **{entry}**")
        else:
            raise commands.CommandError(f"Couldn't replay {entry}!")

    @commands.command()
    async def shuffle(self, ctx: Context):
        """Shuffle the queue"""
        player = await self.get_player(ctx)
        player.queue.shuffle()
        await ctx.send("Shuffled the queue")

    @commands.command()
    async def clear(self, ctx: Context):
        """Clear the queue"""
        player = await self.get_player(ctx)
        player.queue.clear()
        # TODO show prompt!
        await ctx.send("Cleared the queue")

    @commands.group()
    async def skip(self, ctx: Context):
        """Skip the current chapter/entry"""
        player = await self.get_player(ctx)

        if player.is_stopped:
            raise commands.CommandError("Can't skip! The player is not playing!")

        await player.skip()

    @skip.command("all")
    async def skip_all(self, ctx: Context):
        """Skip current entry"""
        player = await self.get_player(ctx)

        if player.is_stopped:
            raise commands.CommandError("Can't skip! The player is not playing!")

        await player.skip(respect_chapters=False)

    @commands.command()
    async def promote(self, ctx: Context, position: int = None):
        """Move an entry to the front

        If not position specified, promote the last song.
        """
        player = await self.get_player(ctx)

        if len(player.queue.entries) < 2:
            raise commands.CommandError("Can't promote! Please add at least 2 songs to the queue!")

        if position is not None:
            position -= 1
            if position == 0:
                raise commands.CommandError("Doesn't really make sense to promote an entry which is already at the front of the queue, eh?")
            elif not 0 <= position < len(player.queue):
                raise commands.CommandError("Index out of range")
            queue_entry = player.queue.move(position)
        else:
            queue_entry = player.queue.move(len(player.queue) - 1)

        await ctx.send(f"Promoted **{queue_entry.entry}**")

    @commands.command()
    async def move(self, ctx: Context, from_pos: int, to_pos: int):
        """Move an entry"""
        player = await self.get_player(ctx)

        from_index = from_pos - 1
        to_index = to_pos - 1

        queue_length = len(player.queue)

        if not 0 <= from_index < queue_length:
            raise commands.CommandError(f"`from_pos` must be between 1 and {queue_length}")

        if not 0 <= to_index < queue_length:
            raise commands.CommandError(f"`to_pos` must be between 1 and {queue_length}")

        entry = player.queue.move(from_index, to_index)
        await ctx.send(f"Moved **{entry.entry}** from position `{from_pos}` to `{to_pos}`.")


class DisplayCog(QueueBase):

    async def _show_queue_entry_info(self, ctx: Context, index: int):
        player = await self.get_player(ctx)
        index -= 1

        if not 0 <= index < len(player.queue):
            raise commands.CommandError(f"Index {index + 1} not in queue")

        queue_entry = player.queue.entries[index]

        em = prefab.get_entry_embed(queue_entry)

        em.timestamp = datetime.utcfromtimestamp(queue_entry.request_timestamp)

        em.add_field(name="Requested by", value=queue_entry.requester.mention)

        waiting_for = utils.format_time(time.time() - queue_entry.request_timestamp)
        em.add_field(name="Waiting For", value=waiting_for)

        time_until = utils.format_time(player.queue.time_until(index))
        em.add_field(name="Playing in", value=time_until)

        # TODO make interactive with buttons like PROMOTE/REMOVE
        # TODO history_entry_info?!?

        await ctx.send(embed=em)

    @commands.command()
    async def queue(self, ctx: Context, index: int = None):
        """Show the queue"""
        if index is not None:
            await self._show_queue_entry_info(ctx, index)
            return

        player = await self.get_player(ctx)

        lines = []
        index_padding = len(str(len(player.queue.entries))) + 1

        for ind, entry in enumerate(player.queue.entries, 1):
            index = pad_index(ind, index_padding)
            basic_entry = entry.entry

            line = f"{index} **{text_utils.shorten(basic_entry, 50)}**"
            lines.append(line)

        if not lines:
            raise commands.CommandError("No entries in the queue")

        total_duration = utils.format_time(player.queue.total_duration(), True, 5, 2)

        frame = {
            "title": "Queue",
            "author": {
                "name": "{progress_bar}"
            },
            "footer": {
                "text": f"Total duration: {total_duration}"

            }
        }

        # TODO use custom viewers for these which have some fancy buttons
        viewer = VerticalTextViewer(ctx.channel, bot=self.bot, user=ctx.author, content=lines, embed_frame=frame)
        await viewer.display()
        await ctx.message.delete()

    @commands.command()
    async def history(self, ctx: Context):
        """Show the past entries"""
        player = await self.get_player(ctx)
        lines = []

        index_padding = len(str(len(player.queue.history))) + 1

        for ind, entry in enumerate(player.queue.history, 1):
            basic_entry = entry.entry
            time_passed = utils.format_time(entry.time_passed, max_specifications=1)

            index = pad_index(ind, index_padding)

            line = f"{index} **{text_utils.shorten(basic_entry, 50)}** | {time_passed} ago"
            lines.append(line)

        if not lines:
            raise commands.CommandError("No history")

        frame = {
            "title": "History",
            "author": {
                "name": "{progress_bar}"
            }
        }

        viewer = VerticalTextViewer(ctx.channel, bot=self.bot, user=ctx.author, content=lines, embed_frame=frame)
        await viewer.display()
        await ctx.message.delete()


class Queue(EnqueueCog, ManipulateCog, DisplayCog):
    pass


def setup(bot: Giesela):
    bot.add_cog(Queue(bot))
