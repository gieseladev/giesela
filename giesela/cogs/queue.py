import asyncio
import random
import time
from random import shuffle
from typing import Optional

from discord import Embed, Message
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Downloader, Giesela, MusicPlayer, RadioSongExtractor, RadioStations, get_all_stations, get_random_station
from giesela.lib.api import spotify
from giesela.lib.ui import ItemPicker, LoadingBar
from giesela.utils import (create_bar, format_time, html2md)
from .player import Player


class QueueBase:
    bot: Giesela
    player_cog: Player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.get_cog("Player")

    @property
    def downloader(self) -> Downloader:
        return self.player_cog.downloader

    async def get_player(self, *args, **kwargs) -> Optional[MusicPlayer]:
        return await self.player_cog.get_player(*args, **kwargs)


class EnqueueCog(QueueBase):

    @commands.command()
    async def stream(self, ctx: Context, url: str):
        """Enqueue a media stream.

        This could mean an actual stream like Twitch, Youtube Gaming or even a radio stream, or simply streaming
        media without predownloading it.
        """
        player = await self.get_player(ctx.guild)
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
        player = await self.get_player(ctx.guild)

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

        item_picker = ItemPicker(self.bot, ctx.channel, user=ctx.author, items=embeds)
        result = await item_picker.result()

        if result is None:
            await ctx.send("Okay then")
        else:
            station = possible_stations[result]
            await player.queue.add_radio_entry(station, channel=ctx.channel, author=ctx.author)
            await ctx.send(f"There you go fam!\n**{station.name}**")

    @radio.command("random")
    async def radio_random(self, ctx: Context):
        """Play a random radio station"""
        player = await self.get_player(ctx.guild)
        station_info = get_random_station()
        await player.queue.add_radio_entry(station_info, channel=ctx.channel, author=ctx.author, now=True)
        await ctx.send(f"I choose\n**{station_info.name}**")

    async def _play_url(self, ctx: Context, player: MusicPlayer, url: str, placement=None):
        async with ctx.typing():
            query = url.strip("<>")

            try:
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

                        if progress_message_future:
                            progress_message = progress_message_future.result()

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

    @commands.command()
    async def play(self, ctx: Context, url: str, placement: str = None):
        """Adds the song to the queue.

        If no link is provided, the first
        result from a youtube search is added to the queue.
        """
        player = await self.get_player(ctx.guild)

        if placement:
            placement = placement.lower()
            if placement in ["next", "now", "first"]:
                placement = 0
            elif placement in ["anytime", "anywhere", "random"]:
                placement = "random"
            elif placement.isnumeric():
                placement = int(placement) - 1

        await self._play_url(ctx, player, url, placement)

    @commands.command()
    async def search(self, ctx: Context, *query: str):
        """Searches for a video and adds the one you choose."""
        player = await self.get_player(ctx.guild)

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
        async with ctx.typing():
            try:
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
                async with ctx.typing():
                    await self._play_url(ctx, player, current_result["webpage_url"])
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
        player = await self.get_player(ctx.guild)
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

            loading_bar = LoadingBar(self.bot, ctx.channel, header="Loading Playlist", total_items=total_tracks, item_name_plural="tracks")

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


# class ManipulateCommands:
#
#     @commands.command()
#     async def remove(self, server, player, message, channel, author, leftover_args):
#         """
#         ///|Usage
#         `{command_prefix}remove <index | start index | url> [end index]`
#         ///|Explanation
#         Remove an index or a url from the queue.
#         """
#
#         if not leftover_args:
#             leftover_args = ["0"]
#
#         if len(player.queue.entries) < 0:
#             return Response("There are no entries in the queue!")
#
#         if len(leftover_args) >= 2:
#             indices = (
#                 int(leftover_args[0]) - 1,
#                 int(leftover_args[1]) - 1
#             )
#
#             start_index = min(indices)
#             end_index = max(indices)
#
#             if start_index >= len(player.queue.entries) or start_index < 0:
#                 return Response("The start index is out of bounds")
#             if end_index >= len(player.queue.entries) or end_index < 0:
#                 return Response("The end index is out of bounds")
#
#             for i in range(end_index, start_index - 1, -1):
#                 del player.queue.entries[i]
#
#             WebieselaServer.send_player_information_update(server.id)
#             return Response(
#                 "Removed {} entries from the queue".format(
#                     end_index - start_index + 1)
#             )
#
#         try:
#             index = int(leftover_args[0]) - 1
#
#             if index > len(player.queue.entries) - 1 or index < 0:
#                 return Response("This index cannot be found in the queue")
#
#             video = player.queue.entries[index].title
#             del player.queue.entries[index]
#             WebieselaServer.send_player_information_update(server.id)
#             return Response("Removed **{0}** from the queue".format(video))
#
#         except:
#             strindex = leftover_args[0]
#             iteration = 1
#
#             for entry in player.queue.entries:
#                 print(
#                     "Looking at {0}. [{1}]".format(entry.title, entry.url))
#
#                 if entry.title == strindex or entry.url == strindex:
#                     print("Found {0} and will remove it".format(
#                         leftover_args[0]))
#                     await self.remove(player, message, channel, author, [iteration])
#                     WebieselaServer.send_player_information_update(server.id)
#                     return
#                 iteration += 1
#
#         return Response("Didn't find anything that goes by {0}".format(leftover_args[0]))
#
#     @commands.command()
#     async def replay(self, player, choose_last=""):
#         """
#         ///|Usage
#         `{command_prefix}replay [last]`
#         ///|Replay history
#         `{command_prefix}replay <index>`
#         Replay a song from the history
#         ///|Explanation
#         Replay the currently playing song. If there's nothing playing, or the \"last\" keyword is given, replay the last song
#         """
#
#         try:
#             index = int(choose_last) - 1
#             if index >= len(player.queue.history):
#                 return Response("History doesn't go back that far.")
#             if index < 0:
#                 return Response(
#                     "Am I supposed to replay the future or what...?")
#
#             replay_entry = player.queue.history[index]
#             player.queue.replay(index)
#
#             return Response("Replaying **{}**".format(replay_entry.title))
#         except:
#             pass
#
#         replay_entry = player.current_entry
#         if (not player.current_entry) or choose_last.lower() == "last":
#             if not player.queue.history:
#                 return Response(
#                     "Cannot replay the last song as there is no last song")
#
#             replay_entry = player.queue.history[0]
#
#         if not replay_entry:
#             return Response("There's nothing for me to replay")
#
#         player.queue.replay()
#         return Response("Replaying **{}**".format(replay_entry.title))
#
#     @commands.command()
#     async def shuffle(self, channel, player):
#         """
#         ///|Usage
#         `{command_prefix}shuffle`
#         ///|Explanation
#         Shuffles the queue.
#         """
#
#         player.queue.shuffle()
#
#         cards = [":spades:", ":clubs:", ":hearts:", ":diamonds:"]
#         hand = await self.send_message(channel, " ".join(cards))
#
#         for x in range(4):
#             await asyncio.sleep(0.6)
#             shuffle(cards)
#             await self.safe_edit_message(hand, " ".join(cards))
#
#         await self.safe_delete_message(hand, quiet=True)
#         return Response(":ok_hand:")
#
#     @commands.command()
#     async def clear(self, player):
#         """
#         ///|Usage
#         `{command_prefix}clear`
#         ///|Explanation
#         Clears the queue.
#         """
#
#         player.queue.clear()
#         return Response(":put_litter_in_its_place:")
#
#     @commands.command()
#     async def skip(self, player, skip_amount=None):
#         """
#         ///|Usage
#         `{command_prefix}skip [all]`
#         ///|Explanation
#         Skips the current song.
#         When given the keyword "all", skips all timestamped-entries in the current timestamp-entry.
#         """
#
#         if player.is_stopped:
#             return Response("Can't skip! The player is not playing!")
#
#         if not player.current_entry:
#             if player.queue.peek():
#                 if player.queue.peek()._is_downloading:
#                     return Response("The next song ({}) is downloading, please wait.".format(player.queue.peek().title))
#
#                 elif player.queue.peek().is_downloaded:
#                     return Response("Something strange is happening.")
#                 else:
#                     return Response("Something odd is happening.")
#             else:
#                 return Response("Something strange is happening.")
#
#         if isinstance(player.current_entry, TimestampEntry) and (not skip_amount or skip_amount.lower() != "all"):
#             return await self.seek(
#                 player,
#                 str(player.current_entry.current_sub_entry["end"])
#             )
#
#         player.skip()
#
#     @commands.command()
#     async def promote(self, player, position=None):
#         """
#         ///|Usage
#         `{command_prefix}promote [song position]`
#         ///|Explanation
#         Promotes the last song in the queue to the front.
#         If you specify a position, it promotes the song at that position to the front.
#         """
#
#         if player.is_stopped:
#             raise exceptions.CommandError(
#                 "Can't modify the queue! The player is not playing!")
#
#         length = len(player.queue.entries)
#
#         if length < 2:
#             raise exceptions.CommandError(
#                 "Can't promote! Please add at least 2 songs to the queue!")
#
#         if not position:
#             entry = player.queue.promote_last()
#         else:
#             try:
#                 position = int(position) - 1
#             except ValueError:
#                 raise exceptions.CommandError(
#                     "This is not a valid song number! Please choose a song \
#                     number between 2 and %s!" % length)
#
#             if position == 0:
#                 raise exceptions.CommandError(
#                     "This song is already at the top of the queue!")
#             if position < 0 or position >= length:
#                 raise exceptions.CommandError(
#                     "Can't promote a song not in the queue! Please choose a song \
#                     number between 2 and %s!" % length)
#
#             entry = player.queue.promote_position(position)
#
#         reply_text = "Promoted **{}** to the :top: of the queue. Estimated time until playing: {}"
#         btext = entry.title
#
#         try:
#             time_until = await player.queue.estimate_time_until(1, player)
#         except:
#             traceback.print_exc()
#             time_until = ""
#
#         return Response(reply_text.format(btext, time_until))
#
#     @commands.command()
#     async def move(self, player, from_index, to_index):
#         """
#         ///|Usage
#         `{command_prefix}move <from index> <to index>`
#         ///|Explanation
#         Moves an entry from a given position.
#         For example, `{command_prefix}move 22 2` will move entry 22 in the queue to position 2 in the queue.
#         """
#
#         if from_index.isnumeric():
#             from_index = int(from_index) - 1
#         else:
#             return Response("`<from index>` must be a number")
#
#         if to_index.isnumeric():
#             to_index = int(to_index) - 1
#         else:
#             return Response("`<to index>` must be a number")
#
#         queue_length = len(player.queue.entries)
#
#         if not 0 <= from_index < queue_length:
#             return Response("`<from index>` must be between 1 and {}".format(queue_length))
#
#         if not 0 <= to_index < queue_length:
#             return Response("`<to index>` must be between 1 and {}".format(queue_length))
#
#         moved_entry = player.queue.move(from_index, to_index)
#         return Response("Moved **{}** from position `{}` to `{}`.".format(moved_entry.title, from_index + 1, to_index + 1))
#
#     @commands.command()
#     async def explode(self, player, channel, author, leftover_args):
#         """
#         ///|Usage
#         `{command_prefix}explode [playlist link | index]`
#         ///|Explanation
#         Split a timestamp-entry into its sub-entries.
#         """
#
#         await self.send_typing(channel)
#
#         if leftover_args:
#             query = " ".join(leftover_args).strip()
#             if query.isnumeric():
#                 index = int(query) - 1
#                 if 0 <= index < len(player.queue.entries):
#                     entry = player.queue.entries[index]
#                 else:
#                     return Response("Your index is out of bounds")
#             else:
#                 entry = await player.queue.get_entry_from_query(query, channel=channel, author=author)
#         elif player.current_entry:
#             entry = player.current_entry
#         else:
#             return Response("Can't explode what's not there")
#
#         if not isinstance(entry, TimestampEntry):
#             return Response("Can only explode timestamp-entries")
#
#         sub_queue = entry.sub_queue
#
#         progress_message = await self.safe_send_message(channel, "Exploding {} entr{}".format(
#             len(sub_queue),
#             "y" if len(sub_queue) == 1 else "ies"
#         ))
#
#         for ind, sub_entry in enumerate(sub_queue, 1):
#             add_entry = await player.queue.get_entry_from_query(
#                 sub_entry["name"],
#                 author=entry.meta.get("author", author),
#                 channel=entry.meta.get("channel", channel)
#             )
#             player.queue._add_entry(add_entry)
#
#             prg = ind / len(sub_queue)
#
#             progress_message = await self.safe_edit_message(
#                 progress_message,
#                 "Explosion in progress\n{} `{}%`".format(
#                     create_bar(prg, length=20),
#                     round(100 * prg)
#                 ),
#                 keep_at_bottom=True
#             )
#
#         await self.safe_delete_message(progress_message)
#
#         return Response("Exploded **{}** into {} entr{}".format(
#             entry.whole_title,
#             len(sub_queue),
#             "y" if len(sub_queue) == 1 else "ies"
#         ))
#
#
# class DisplayCommands:
#
#     @commands.command()
#     async def np(self, player, channel, server):
#         """
#         ///|Usage
#         {command_prefix}np
#         ///|Explanation
#         Displays the current song in chat.
#         """
#
#         if player.current_entry:
#             if self.guild_specific_data[server]["last_np_msg"]:
#                 await self.safe_delete_message(
#                     self.guild_specific_data[server]["last_np_msg"])
#                 self.guild_specific_data[server]["last_np_msg"] = None
#
#             entry = player.current_entry
#             em = None
#
#             if isinstance(entry, RadioSongEntry):
#                 progress_ratio = entry.song_progress / \
#                                  (entry.song_duration or 1)
#                 desc = "{} `[{}/{}]`".format(
#                     create_bar(progress_ratio, length=20),
#                     to_timestamp(entry.song_progress),
#                     to_timestamp(entry.song_duration)
#                 )
#                 foot = "🔴 Live from {}".format(entry.station_name)
#
#                 em = Embed(
#                     title=entry.title,
#                     description=desc,
#                     url=entry.link,
#                     colour=hex_to_dec("#a23dd1")
#                 )
#
#                 em.set_footer(text=foot)
#                 em.set_thumbnail(url=entry.cover)
#                 em.set_author(
#                     name=entry.artist
#                 )
#             elif isinstance(entry, RadioStationEntry):
#                 desc = "`{}`".format(
#                     to_timestamp(player.progress)
#                 )
#                 foot = "🔴 Live from {}".format(entry.station_name)
#
#                 em = Embed(
#                     title=entry.title,
#                     description=desc,
#                     url=entry.link,
#                     colour=hex_to_dec("#be7621")
#                 )
#
#                 em.set_footer(text=foot)
#                 em.set_thumbnail(url=entry.cover)
#             elif isinstance(entry, StreamEntry):
#                 desc = "🔴 Live [`{}`]".format(to_timestamp(player.progress))
#
#                 em = Embed(
#                     title=entry.title,
#                     description=desc,
#                     colour=hex_to_dec("#a23dd1")
#                 )
#
#             if isinstance(entry, GieselaEntry):
#                 artist_name = entry.artist
#                 artist_avatar = entry.artist_image
#                 progress_ratio = player.progress / entry.end_seconds
#                 desc = "{} `[{}/{}]`".format(
#                     create_bar(progress_ratio, length=20),
#                     to_timestamp(player.progress),
#                     to_timestamp(entry.end_seconds)
#                 )
#
#                 em = Embed(
#                     title=entry.song_title,
#                     description=desc,
#                     url=entry.url,
#                     colour=hex_to_dec("#F9FF6E")
#                 )
#
#                 em.set_thumbnail(url=entry.cover)
#                 em.set_author(
#                     name=artist_name,
#                     icon_url=artist_avatar
#                 )
#                 em.add_field(name="Album", value=entry.album)
#             elif isinstance(entry, TimestampEntry):
#                 sub_entry = entry.current_sub_entry
#                 index = sub_entry["index"] + 1
#                 progress_ratio = sub_entry["progress"] / sub_entry["duration"]
#                 desc = "{} `[{}/{}]`".format(
#                     create_bar(progress_ratio, length=20),
#                     to_timestamp(sub_entry["progress"]),
#                     to_timestamp(sub_entry["duration"])
#                 )
#                 foot = "{}{} sub-entry of \"{}\" [{}/{}]".format(
#                     index,
#                     ordinal(index),
#                     entry.whole_title,
#                     to_timestamp(player.progress),
#                     to_timestamp(entry.end_seconds)
#                 )
#
#                 em = Embed(
#                     title=sub_entry["name"],
#                     description=desc,
#                     url=entry.url,
#                     colour=hex_to_dec("#00FFFF")
#                 )
#
#                 em.set_footer(text=foot)
#                 em.set_thumbnail(url=entry.thumbnail)
#                 if "playlist" in entry.meta:
#                     pl = entry.meta["playlist"]
#                     em.set_author(name=pl["name"], icon_url=pl.get("cover", None) or Embed.Empty)
#                 elif "author" in entry.meta:
#                     author = entry.meta["author"]
#                     em.set_author(
#                         name=author.display_name,
#                         icon_url=author.avatar_url
#                     )
#             elif isinstance(entry, YoutubeEntry):
#                 progress_ratio = player.progress / entry.end_seconds
#                 desc = "{} `[{}/{}]`".format(
#                     create_bar(progress_ratio, length=20),
#                     to_timestamp(player.progress),
#                     to_timestamp(entry.end_seconds)
#                 )
#
#                 em = Embed(
#                     title=entry.title,
#                     description=desc,
#                     url=entry.url,
#                     colour=hex_to_dec("#a9b244")
#                 )
#
#                 em.set_thumbnail(url=entry.thumbnail)
#                 if "playlist" in entry.meta:
#                     pl = entry.meta["playlist"]
#                     em.set_author(name=pl["name"], icon_url=pl.get("cover", None) or Embed.Empty)
#                 elif "author" in entry.meta:
#                     author = entry.meta["author"]
#                     em.set_author(
#                         name=author.display_name,
#                         icon_url=author.avatar_url
#                     )
#
#             if em:
#                 self.guild_specific_data[server]["last_np_msg"] = await self.safe_send_message(channel, embed=em)
#         else:
#             return Response(
#                 "There are no songs queued! Queue something with {}play.".format(self.config.command_prefix))
#
#     @command_info("1.0.0", 1477180800, {
#         "3.5.1": (1497706997, "Queue doesn't show the current entry anymore, always shows the whole queue and a bit of cleanup"),
#         "3.5.5": (1497795534, "Total time takes current entry into account"),
#         "3.5.8": (1497825017, "Doesn't show the whole queue right away anymore, "
#                               "instead the queue command takes a quantity argument which defaults to 15"),
#         "3.8.0": (1499110875, "Displaying real index of sub-entries (timestamp-entry)"),
#         "3.8.9": (1499461647, "Part of the `Giesenesis` rewrite")
#     })
#     async def queue(self, player, num="15"):
#         """
#         ///|Usage
#         {command_prefix}queue [quantity]
#         ///|Explanation
#         Show the first 15 entries of the current song queue.
#         One can specify the amount of entries to be shown.
#         """
#
#         try:
#             quantity = int(num)
#
#             if quantity < 1:
#                 return Response("Please provide a reasonable quantity")
#         except ValueError:
#             if num.lower() == "all":
#                 quantity = len(player.queue.entries)
#             else:
#                 return Response("Quantity must be a number")
#
#         lines = ["**QUEUE**\n"]
#
#         if player.current_entry and isinstance(player.current_entry, TimestampEntry):
#             sub_queue = player.current_entry.sub_queue
#             sub_queue = [sub_entry for sub_entry in sub_queue if sub_entry[
#                 "start"] >= player.progress]
#             for item in sub_queue:
#                 lines.append(
#                     "            ►`{}.` **{}**".format(
#                         item["index"] + 1,
#                         nice_cut(item["name"], 35)
#                     )
#                 )
#
#         entries = list(player.queue.entries)[:quantity]
#         for i, item in enumerate(entries, 1):
#             origin_text = ""
#             if "playlist" in item.meta:
#                 origin_text = "from playlist **{}**".format(
#                     item.meta["playlist"]["name"]
#                 )
#             elif "author" in item.meta:
#                 origin_text = "by **{}**".format(
#                     item.meta["author"].name
#                 )
#
#             lines.append("`{}.` **{}** {}".format(
#                 i, nice_cut(item.title, 40), origin_text))
#
#         if len(lines) < 2:
#             return Response(
#                 "There are no songs queued! Use `{}help` to find out how to queue something.".format(self.config.command_prefix))
#
#         total_time = sum(
#             [entry.end_seconds for entry in player.queue.entries])
#         if player.current_entry:
#             total_time += player.current_entry.end_seconds - player.progress
#
#         lines.append(
#             "\nShowing {} out of {} entr{}".format(
#                 len(entries),
#                 len(player.queue.entries),
#                 "y" if len(player.queue.entries) == 1 else "ies"
#             )
#         )
#         lines.append(
#             "**Total duration:** `{}`".format(
#                 format_time(total_time, True, 5, 2)
#             )
#         )
#
#         return Response("\n".join(lines))
#
#     @command_info("3.3.3", 1497197957, {
#         "3.3.8": (1497474312, "added failsafe for player not currently playing something"),
#         "3.5.8": (1497825334, "Adjusted design to look more like `queue`'s style"),
#         "3.8.9": (1499465102, "Part of the `Giesenesis` rewrite"),
#         "4.0.1": (1500346108, "Quantity parameter. Increased history limit"),
#         "4.1.7": (1500876373, "Displaying the amount of entries displayed in relation to the total entries"),
#         "4.2.9": (1501176845, "Showing the correct amount of entries displayed")
#     })
#     async def history(self, player, num="15"):
#         """
#         ///|Usage
#         {command_prefix}history [quantity]
#         ///|Explanation
#         Show the last [quantity] songs. If [quantity] isn't provided, show up to 15 songs
#         """
#
#         try:
#             quantity = int(num)
#
#             if quantity < 1:
#                 return Response("Please provide a reasonable quantity")
#         except ValueError:
#             if num.lower() == "all":
#                 quantity = len(player.queue.entries)
#             else:
#                 return Response("Quantity must be a number")
#
#         if not player.queue.history:
#             return Response("There **is** no history")
#
#         lines = ["**HISTORY**"]
#
#         entries = player.queue.history[:quantity]
#
#         for ind, entry in enumerate(entries, 1):
#             finish_time = entry.meta.get("finish_time")
#             seconds_passed = time.time() - finish_time
#             lines.append(
#                 "`{}.` **{}** {} ago".format(
#                     ind,
#                     nice_cut(entry.title, 40),
#                     format_time(seconds_passed, max_specifications=2)
#                 )
#             )
#
#         lines.append(
#             "\nShowing {} out of {} entr{}".format(
#                 len(entries),
#                 len(player.queue.history),
#                 "y" if len(player.queue.history) == 1 else "ies"
#             )
#         )
#
#         return Response("\n".join(lines))


class Queue(EnqueueCog):
    pass


def setup(bot: Giesela):
    bot.add_cog(Queue(bot))
