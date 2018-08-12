import asyncio
import random
import time
from random import shuffle
from typing import Dict, Optional

from discord import Embed, Message
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Downloader, Giesela, MusicPlayer, RadioSongExtractor, RadioStations, TimestampEntry, WebieselaServer, get_all_stations, \
    get_random_station
from giesela.lib.api import spotify
from giesela.lib.ui import ItemPicker, LoadingBar, VerticalTextViewer
from giesela.lib.ui.custom import NowPlayingEmbed
from giesela.utils import (create_bar, format_time, html2md, nice_cut)
from .player import Player

LOAD_ORDER = 1


class QueueBase:
    bot: Giesela

    player_cog: Optional[Player]

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.cogs["Player"]

    @property
    def downloader(self) -> Downloader:
        return self.player_cog.downloader

    async def get_player(self, *args, **kwargs) -> Optional[MusicPlayer]:
        return await self.player_cog.get_player(*args, **kwargs)


async def _play_url(ctx: Context, player: MusicPlayer, url: str, placement: int = None):
    query = url.strip("<>")

    try:
        async with ctx.typing():
            entry = await player.queue.get_entry_from_query(query, author=ctx.author, channel=ctx.channel)
    except BaseException as e:
        raise commands.CommandError("There was a tiny problem with your request:\n```\n{}\n```".format(e))

    if not entry:
        await ctx.send("Couldn't find anything for me to add")
        return

    if isinstance(entry, list):
        print("[PLAY] This is a playlist!")
        # playlist handling
        entries_added = 0
        entries_not_added = 0

        entry_generator = player.queue.get_entries_from_urls_gen(*entry, author=ctx.author, channel=ctx.channel)

        total_entries = len(entry)
        progress_message = await ctx.send("Parsing {} entries\n{} [0%]".format(total_entries, create_bar(0, length=20)))
        times = []
        abs_start = time.time()
        start_time = abs_start

        progress_message_future = None

        async for ind, entry in entry_generator:
            if entry:
                player.queue._add_entry(entry, placement)
                entries_added += 1
            else:
                entries_not_added += 1

            times.append(time.time() - start_time)
            start_time = time.time()

            if not progress_message_future or progress_message_future.done():
                avg_time = sum(times) / float(len(times))
                entries_left = total_entries - ind - 1
                expected_time = format_time(
                    avg_time * entries_left,
                    max_specifications=1,
                    unit_length=1
                )
                completion_ratio = (ind + 1) / total_entries

                progress_message_future = asyncio.ensure_future(
                    progress_message.edit(content="Parsing {} entr{} at {} entries/min\n{} [{}%]\n{} remaining".format(
                        entries_left,
                        "y" if entries_left == 1 else "ies",
                        round(60 / avg_time, 1),
                        create_bar(completion_ratio, length=20),
                        round(100 * completion_ratio),
                        expected_time
                    ))
                )

        delta_time = time.time() - abs_start

        progress_message_future.cancel()
        await progress_message.delete()
        await ctx.send("Added {} entries to the queue\nSkipped {} entries\nIt took {} to add all entries".format(
            entries_added,
            entries_not_added,
            format_time(delta_time, unit_length=1)
        ))
    else:
        player.queue._add_entry(entry, placement)
        await ctx.send("Enqueued **{}**".format(entry.title))


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
            await player.queue.add_stream_entry(song_url, channel=ctx.channel, author=ctx.author)
        await ctx.send(":+1:")

    @commands.group(inovke_without_command=True)
    async def radio(self, ctx: Context, station: str = None):
        """Play a radio station.

        You can leave the parameters blank in order to get a tour around all the channels,
        you can specify the station you want to listen to or you can let the bot choose for you by entering \"random\"
        """
        player = await self.get_player(ctx)

        if station:
            station_info = RadioStations.get_station(station.lower())
            if station_info:
                await player.queue.add_radio_entry(station_info, channel=ctx.channel, author=ctx.author, now=True)
                await ctx.send(f"Your favourite:\n**{station_info.name}**")
                return

        # help the user find the right station

        possible_stations = get_all_stations()
        shuffle(possible_stations)

        embeds = []

        for station in possible_stations:
            em = Embed(colour=0xb3f75d)
            em.set_author(name=station.name, url=station.website)
            em.set_thumbnail(url=station.cover)

            if station.has_current_song_info:
                data = await RadioSongExtractor.async_get_current_song(self.bot.loop, station)
                em.add_field(name="Currently playing", value="{artist} - {title}".format(**data))

            embeds.append(em)

        item_picker = ItemPicker(ctx.channel, ctx.author, embeds=embeds)
        result = await item_picker.choose()

        if result is None:
            await ctx.send("Okay then")
        else:
            station = possible_stations[result]
            await player.queue.add_radio_entry(station, channel=ctx.channel, author=ctx.author)
            await ctx.send(f"There you go fam!\n**{station.name}**")

    @radio.command("random")
    async def radio_random(self, ctx: Context):
        """Play a random radio station."""
        player = await self.get_player(ctx)
        station_info = get_random_station()
        await player.queue.add_radio_entry(station_info, channel=ctx.channel, author=ctx.author, now=True)
        await ctx.send(f"I choose\n**{station_info.name}**")

    @commands.command()
    async def play(self, ctx: Context, url: str, placement: str = None):
        """Adds the song to the queue.

        If no link is provided, the first
        result from a youtube search is added to the queue.
        """
        player = await self.get_player(ctx)

        if placement:
            placement = placement.lower()
            if placement in ["next", "now", "first"]:
                placement = 0
            elif placement in ["anytime", "anywhere", "random"]:
                placement = "random"
            elif placement.isnumeric():
                placement = int(placement) - 1
            else:
                raise commands.CommandError("Invalid placement. Did you forget to put quotes around your query?")

        await _play_url(ctx, player, url, placement)

    @commands.command()
    async def search(self, ctx: Context, *query: str):
        """Searches for a video and adds the one you choose."""
        player = await self.get_player(ctx)

        if not query:
            raise commands.CommandError("Please specify a search query.")

        try:
            number = int(query[0])
            if number > 20:
                raise commands.CommandError("You musn't search for more than 20 videos")

            query = " ".join(query[1:])

            if not query:
                raise commands.CommandError("You have to specify the query too.")
        except ValueError:
            number = 5
            query = " ".join(query)

        search_query = "ytsearch{}:{}".format(number, query)

        search_msg = await ctx.send("Searching for videos...")
        try:
            async with ctx.typing():
                info = await self.downloader.extract_info(
                    player.queue.loop,
                    search_query,
                    download=False,
                    process=True
                )
        except Exception as e:
            await search_msg.edit(content=str(e))
            return
        else:
            await search_msg.delete()

        if not info:
            await ctx.send("No videos found.")
            return

        result_string = "**Result {0}/{1}**\n{2}"
        interface_string = "**Commands:**\n" \
                           "`play` play this result\n" \
                           "`addtoplaylist <playlist name>` add this result to a playlist\n" \
                           "\n" \
                           "`n` next result\n" \
                           "`p` previous result\n" \
                           "`exit` abort and exit"

        current_result_index = 0
        total_results = len(info["entries"])

        def msg_check(msg: Message) -> bool:
            if msg.author == ctx.author and msg.channel == ctx.channel:
                return msg.content.strip().lower().split()[0] in ("play", "n", "p", "exit")
            return False

        async def delete_msgs():
            nonlocal result_message, interface_message, response_message
            await asyncio.wait([result_message.delete(), interface_message.delete(), response_message.delete()])

        while True:
            current_result = info["entries"][current_result_index]

            result_message = await ctx.send(result_string.format(current_result_index + 1, total_results, current_result["webpage_url"]))
            interface_message = await ctx.send(interface_string)

            response_message = await self.bot.wait_for("message", check=msg_check, timeout=100)

            if not response_message:
                await delete_msgs()
                await ctx.send("Aborting search. [Timeout]")
                return

            content = response_message.content.strip()
            command, *args = content.lower().split()

            if command == "exit":
                await delete_msgs()
                await ctx.send("Okay then. Search again soon")
                return
            elif command in "np":
                # feels hacky but is actully genius
                current_result_index += {"n": 1, "p": -1}[command]
                current_result_index %= total_results
            elif command == "play":
                await _play_url(ctx, player, current_result["webpage_url"])
                await delete_msgs()
                await ctx.send("Alright, coming right up!")
                return

            await delete_msgs()

    # @commands.command()
    # async def suggest(self, player, channel, author):
    #     """
    #     ///|Usage
    #     `{command_prefix}suggest`
    #     ///|Explanation
    #     Find similar videos to the current one
    #     """
    #
    #     if not player.current_entry:
    #         return Response("Can't give you any suggestions when there's nothing playing.")
    #
    #     if not isinstance(player.current_entry, YoutubeEntry):
    #         return Response("Can't provide any suggestions for this entry type")
    #
    #     vid_id = player.current_entry.video_id
    #
    #     videos = get_related_videos(vid_id)
    #
    #     if not videos:
    #         return Response("Couldn't find anything.")
    #
    #     result_string = "**Result {0}/{1}**\n{2}"
    #     interface_string = "**Commands:**\n`play` play this result\n\n`n` next result\n`p` previous result\n`exit` abort and exit"
    #
    #     current_result_index = 0
    #     total_results = len(videos)
    #
    #     while True:
    #         current_result = videos[current_result_index]
    #
    #         result_message = await self.safe_send_message(channel,
    #                                                       result_string.format(current_result_index + 1, total_results, current_result["url"]))
    #         interface_message = await self.safe_send_message(channel, interface_string)
    #         response_message = await self.wait_for_message(100, author=author, channel=channel,
    #                                                        check=lambda msg: msg.content.strip().lower().split()[0] in ("play", "n", "p", "exit"))
    #
    #         if not response_message:
    #             await self.safe_delete_message(result_message)
    #             await self.safe_delete_message(interface_message)
    #             await self.safe_delete_message(response_message)
    #             return Response("Aborting. [Timeout]")
    #
    #         content = response_message.content.strip()
    #         command, *args = content.lower().split()
    #
    #         if command == "exit":
    #             await self.safe_delete_message(result_message)
    #             await self.safe_delete_message(interface_message)
    #             await self.safe_delete_message(response_message)
    #             return Response("Okay then. Suggest again soon *(Sorry, I couldn't resist)*")
    #         elif command in "np":
    #             # feels hacky but is actully genius
    #             current_result_index += {"n": 1, "p": -1}[command]
    #             current_result_index %= total_results
    #         elif command == "play":
    #             await self.send_typing(channel)
    #             await self.play(player, channel, author, [], current_result["url"])
    #             await self.safe_delete_message(result_message)
    #             await self.safe_delete_message(interface_message)
    #             await self.safe_delete_message(response_message)
    #
    #         await self.safe_delete_message(result_message)
    #         await self.safe_delete_message(interface_message)
    #         await self.safe_delete_message(response_message)

    @commands.command()
    async def spotify(self, ctx: Context, url: str):
        """Load a playlist or track from Spotify!"""
        player = await self.get_player(ctx)
        await ctx.message.delete()
        model = spotify.model_from_url(url)

        if isinstance(model, spotify.SpotifyTrack):
            track = model

            em = Embed(title=track.name, description=track.album.name, colour=random.randint(0, 0xFFFFFF))
            em.set_thumbnail(url=track.cover_url)
            em.set_author(name=track.artist_string, icon_url=track.artists[0].image)
            em.set_footer(text=format_time(track.duration))

            await ctx.send(embed=em)

            entry = await model.get_spotify_entry(player.queue, author=ctx.author, channel=ctx.channel)
            player.queue._add_entry(entry)

        elif isinstance(model, spotify.SpotifyPlaylist):
            playlist = model

            em = Embed(title=playlist.name, description=html2md(playlist.description), colour=random.randint(0, 0xFFFFFF), url=playlist.href)
            em.set_thumbnail(url=playlist.cover)
            em.set_author(name=playlist.author)
            em.set_footer(text="{} tracks".format(len(playlist.tracks)))

            interface_msg = await ctx.send("**Loading playlist**", embed=em)

            total_tracks = len(playlist.tracks)
            entries_added = 0
            entries_not_added = 0

            loading_bar = LoadingBar(ctx.channel, header="Loading Playlist", total_items=total_tracks, item_name_plural="tracks")

            async for ind, entry in playlist.get_spotify_entries_generator(player.queue, channel=ctx.channel, author=ctx.author):
                if entry:
                    player.queue._add_entry(entry)
                    entries_added += 1
                else:
                    entries_not_added += 1

                await loading_bar.set_progress((ind + 1) / total_tracks)

            await loading_bar.done()

            em.set_footer(text="{} tracks loaded | {} failed".format(entries_added, entries_not_added))
            await interface_msg.edit(content="**Loaded playlist**", embed=em)

        else:
            await ctx.send("Couldn't find anything")


class ManipulateCog(QueueBase):

    @commands.command()
    async def remove(self, ctx: Context, index: int):
        """Remove an entry from the queue."""
        player = await self.get_player(ctx)

        if not player.queue.entries:
            raise commands.CommandError("There are no entries in the queue!")

        index -= 1

        if not 0 <= index < len(player.queue.entries):
            raise commands.CommandError("This index cannot be found in the queue")

        title = player.queue.entries[index].title
        del player.queue.entries[index]
        WebieselaServer.send_player_information(ctx.guild.id)
        await ctx.send(f"Removed **{title}** from the queue")

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
                if not 0 <= index < len(player.queue.history):
                    raise commands.CommandError("Can't find that index")
            elif index in ("previous", "last"):
                if player.queue.history:
                    index = 0
                else:
                    raise commands.CommandError("No history to replay!")
            entry = player.queue.history[index]
        else:
            index = None
            entry = player.current_entry

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

        if skip != "all" and isinstance(player.current_entry, TimestampEntry):
            await player.seek(player.current_entry.current_sub_entry["end"])
        else:
            player.skip()

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

    @commands.command()
    async def queue(self, ctx: Context):
        """Display the queue."""
        player = await self.get_player(ctx)

        lines = []

        if player.current_entry and isinstance(player.current_entry, TimestampEntry):
            sub_queue = player.current_entry.sub_queue
            sub_queue = [sub_entry for sub_entry in sub_queue if sub_entry["start"] >= player.progress]
            for item in sub_queue:
                lines.append(
                    "            ►`{}.` **{}**".format(
                        item["index"] + 1,
                        nice_cut(item["name"], 35)
                    )
                )

        for i, item in enumerate(player.queue.entries, 1):
            origin_text = ""
            if "playlist" in item.meta:
                origin_text = "from playlist **{}**".format(
                    item.meta["playlist"]["name"]
                )
            elif "author" in item.meta:
                origin_text = "by **{}**".format(
                    item.meta["author"].name
                )

            lines.append("`{}.` **{}** {}".format(
                i, nice_cut(item.title, 40), origin_text))

        if not lines:
            raise commands.CommandError("No entries in the queue")

        total_time = sum([entry.end_seconds for entry in player.queue.entries])
        if player.current_entry:
            total_time += player.current_entry.end_seconds - player.progress

        frame = {
            "title": "Queue",
            "author": {
                "name": "{progress_bar}"
            },
            "footer": {
                "text": f"Total duration: {format_time(total_time, True, 5, 2)}"

            }
        }

        viewer = VerticalTextViewer(ctx.channel, ctx.author, content=lines, embed_frame=frame)
        await viewer.display()

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


class Queue(EnqueueCog, ManipulateCog, DisplayCog):
    pass


def setup(bot: Giesela):
    bot.add_cog(Queue(bot))