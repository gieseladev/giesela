import re
import time
from random import choice, shuffle
from textwrap import indent

from discord import Embed

import asyncio

from ..entry import SpotifyEntry, TimestampEntry, YoutubeEntry
from ..saved_playlists import Playlists
from ..spotify import SpotifyTrack
from ..utils import (Response, asyncio, block_user, command_info, create_bar,
                     format_time, is_image, nice_cut, owner_only,
                     parse_timestamp, timestamp_to_queue, to_timestamp,
                     wrap_string)


class PlaylistCommands:

    @block_user
    @command_info("1.9.5", 1479599760, {
        "3.4.6": (1497617827, "when Giesela can't add the entry to the playlist she tries to figure out **why** it didn't work"),
        "3.4.7": (1497619770, "Fixed an annoying bug in which the builder wouldn't show any entries if the amount of entries was a multiple of 20"),
        "3.5.1": (1497706811, "Giesela finally keeps track whether a certain entry comes from a playlist or not"),
        "3.5.8": (1497827857, "Default sort mode when loading playlists is now random and removing an entry in the playlist builder no longer messes with the current page."),
        "3.6.1": (1497969463, "when saving a playlist, list all changes"),
        "3.6.8": (1498162378, "checking whether start and end indices are numbers"),
        "3.6.9": (1498163686, "Special handling for sorting in playlist builder"),
        "3.7.0": (1498233256, "Changelog bug fixes"),
        "3.8.5": (1499279145, "Added \"rebuild\" extra command to clean and fix a playlist"),
        "3.8.7": (1499290119, "Due to a mistake \"rebuild\" always led to the deletion of the first entry."),
        "3.8.9": (1499525669, "Part of the `Giesenesis` rewrite"),
        "3.9.3": (1499712451, "Fixed a bug in the playlist builder search command."),
        "4.0.0": (1499978910, "Forgot to implement progress message properly and as a result it could bug out and spam itself."),
        "4.0.6": (1500536082, "Added description and cover options for a playlist"),
        "4.0.8": (1500723220, "Can now manipulate playlist entries")
    })
    async def cmd_playlist(self, channel, author, server, player, leftover_args):
        """
        ///|Load
        `{command_prefix}playlist load <savename> [add | replace] [none | random] [startindex] [endindex (inclusive)]`\n\nTrust me, it's more complicated than it looks
        ///(NL)|List all playlists
        `{command_prefix}playlist showall [alphabetical | author | entries | playtime | random | replays]`
        ///(NL)|Build a new playlist
        `{command_prefix}playlist builder <savename>`
        ///(NL)|Save the current queue
        `{command_prefix}playlist save <savename>`
        ///(NL)|Clone
        `{command_prefix}playlist clone <fromname> <savename> [startindex | endindex (inclusive)]`
        ///(NL)|Delete a playlist
        `{command_prefix}playlist delete <savename>`
        ///(NL)|Information
        `{command_prefix}playlist <savename>`
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else ""
        savename = re.sub("\W", "", leftover_args[1].lower()) if len(
            leftover_args) > 1 else ""
        load_mode = leftover_args[2].lower() if len(
            leftover_args) > 2 else "add"
        additional_args = leftover_args[2:] if len(leftover_args) > 2 else []

        forbidden_savenames = [
            "showall", "savename", "save", "load", "delete", "builder",
            "extras", "add", "remove", "save", "exit", "clone", "rename",
            "extras", "alphabetical", "author", "entries", "playtime", "random"
        ]

        if argument == "save":
            if savename in self.playlists.saved_playlists:
                return Response(
                    "Can't save the queue, there's already a playlist with this name.")
            if len(savename) < 3:
                return Response(
                    "Can't save the queue, the name must be longer than 3 characters")
            if savename in forbidden_savenames:
                return Response(
                    "Can't save the queue, this name is forbidden!")
            if len(player.playlist.entries) < 1:
                return Response(
                    "Can't save the queue, there are no entries in the queue!")

            if self.playlists.set_playlist(
                [player.current_entry] + list(player.playlist.entries),
                    savename, author.id):
                return Response("Saved the current queue...")

            return Response(
                "Uhm, something went wrong I guess :D")

        elif argument == "load":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't load this playlist, there's no playlist with this name.")

            playlist = self.playlists.get_playlist(
                savename, player.playlist, channel=channel)
            clone_entries = playlist["entries"]
            broken_entries = playlist["broken_entries"]

            if not clone_entries:
                if broken_entries:
                    return Response("Can't play `{0}`, there are **{1}** broken entr{2} in this playlist.\nOpen the playlist builder to fix {3} (`{4}playlist builder {0}`)".format(
                        savename.title(),
                        len(broken_entries),
                        "y" if len(broken_entries) == 1 else "ies",
                        "it" if len(broken_entries) == 1 else "them",
                        self.config.command_prefix
                    ))
                else:
                    return Response("There's nothing in `{}` to play".format(savename.title()))

            if load_mode == "replace":
                player.playlist.clear()
                if player.current_entry is not None:
                    player.skip()

            try:
                from_index = int(
                    additional_args[2]) - 1 if len(additional_args) > 2 else 0
                if from_index >= len(clone_entries) or from_index < 0:
                    return Response("Can't load the playlist starting from entry {}. This value is out of bounds.".format(from_index))
            except ValueError:
                return Response("Start index must be a number")

            try:
                to_index = int(additional_args[3]) if len(
                    additional_args) > 3 else len(clone_entries)
                if to_index > len(clone_entries) or to_index < 0:
                    return Response("Can't load the playlist from the {}. to the {}. entry. These values are out of bounds.".format(from_index, to_index))
            except ValueError:
                return Response("End index must be a number")

            if to_index - from_index <= 0:
                return Response("No songs to play. RIP.")

            clone_entries = clone_entries[from_index:to_index]

            sort_modes = {
                "alphabetical": (lambda entry: entry.title, False),
                "random": None,
                "length": (lambda entry: entry.duration, True)
            }

            sort_mode = additional_args[1].lower(
            ) if len(additional_args) > 1 and additional_args[1].lower(
            ) in sort_modes.keys() else "random"

            if sort_mode == "random":
                shuffle(clone_entries)
            elif sort_mode != "none":
                clone_entries = sorted(
                    clone_entries,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])

            player.playlist.add_entries(clone_entries)
            self.playlists.bump_replay_count(savename)

            if not broken_entries:
                return Response("Loaded `{}`".format(savename.title()))
            else:
                text = "Loaded {0} entr{1} from `{2}`. **{3}** entr{4} couldn't be loaded.\nOpen the playlist builder to repair {5}. (`{6}playlist builder {2}`)"
                return Response(text.format(
                    len(clone_entries),
                    "y" if len(clone_entries) == 1 else "ies",
                    savename.title(),
                    len(broken_entries),
                    "y" if len(broken_entries) == 1 else "ies",
                    "it" if len(broken_entries) == 1 else "them",
                    self.config.command_prefix
                ))

        elif argument == "delete":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't delete this playlist, there's no playlist with this name.",
                    delete_after=20)

            self.playlists.remove_playlist(savename)
            return Response(
                "*{}* has been deleted".format(savename))

        elif argument == "clone":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't clone this playlist, there's no playlist with this name.")
            clone_playlist = self.playlists.get_playlist(
                savename, player.playlist)
            clone_entries = clone_playlist["entries"]
            extend_existing = False

            if additional_args is None:
                return Response(
                    "Please provide a name to save the playlist to")

            if additional_args[0].lower() in self.playlists.saved_playlists:
                extend_existing = True
            if len(additional_args[0]) < 3:
                return Response(
                    "This is not a valid playlist name, the name must be longer than 3 characters")
            if additional_args[0].lower() in forbidden_savenames:
                return Response(
                    "This is not a valid playlist name, this name is forbidden!")

            from_index = int(additional_args[1]) - \
                1 if len(additional_args) > 1 else 0
            if from_index >= len(clone_entries) or from_index < 0:
                return Response(
                    "Can't clone the playlist starting from entry {}. This entry is out of bounds.".
                    format(from_index))

            to_index = int(additional_args[
                2]) if len(additional_args) > 2 else len(clone_entries)
            if to_index > len(clone_entries) or to_index < 0:
                return Response(
                    "Can't clone the playlist from the {}. to the {}. entry. These values are out of bounds.".
                    format(from_index, to_index))

            if to_index - from_index <= 0:
                return Response(
                    "That's not enough entries to create a new playlist.")

            clone_entries = clone_entries[from_index:to_index]
            if extend_existing:
                self.playlists.edit_playlist(
                    additional_args[0].lower(),
                    player.playlist,
                    new_entries=clone_entries)
            else:
                self.playlists.set_playlist(
                    clone_entries, additional_args[0].lower(), author.id)

            return Response(
                "**{}** {}has been cloned to **{}**".format(
                    savename, "(from the {}. to the {}. index) ".format(
                        str(from_index + 1), str(to_index + 1)) if
                    from_index is not 0 or to_index is not len(clone_entries)
                    else "", additional_args[0].lower()))

        elif argument == "showall":
            if len(self.playlists.saved_playlists) < 1:
                return Response(
                    "There are no saved playlists.\n**You** could add one though. Type `{}help playlist` to see how!".format(
                        self.config.command_prefix))

            response_text = "**Found the following playlists:**\n\n"
            iteration = 1

            sort_modes = {
                "alphabetical": (lambda playlist: playlist, False),
                "entries": (
                    lambda playlist: len(self.playlists.get_playlist(
                        playlist, player.playlist)["entries"]),
                    True
                ),
                "author": (
                    lambda playlist: self.get_global_user(
                        self.playlists.get_playlist(playlist, player.playlist)["author"]).name,
                    False
                ),
                "random": None,
                "playtime": (
                    lambda playlist: sum([x.duration for x in self.playlists.get_playlist(
                        playlist, player.playlist)["entries"]]),
                    True
                ),
                "replays": (
                    lambda playlist: self.playlists.get_playlist(
                        playlist, player.playlist)["replay_count"],
                    True
                )
            }

            sort_mode = leftover_args[1].lower(
            ) if len(leftover_args) > 1 and leftover_args[1].lower(
            ) in sort_modes.keys() else "random"

            if sort_mode == "random":
                sorted_saved_playlists = self.playlists.saved_playlists
                shuffle(sorted_saved_playlists)
            else:
                sorted_saved_playlists = sorted(
                    self.playlists.saved_playlists,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])

            for pl in sorted_saved_playlists:
                infos = self.playlists.get_playlist(pl, player.playlist)
                response_text += "**{}.** **\"{}\"** by {}\n```\n  {} entr{} ({} broken)\n  played {} time{}\n  {}```\n\n".format(
                    iteration,
                    pl.replace("_", " ").title(),
                    self.get_global_user(infos["author"]).mention,
                    len(infos["entries"]),
                    "ies" if len(infos["entries"]) is not 1 else "y",
                    len(infos["broken_entries"]),
                    infos["replay_count"], "s"
                    if int(infos["replay_count"]) != 1 else "",
                    format_time(
                        sum([x.duration for x in infos["entries"]]),
                        round_seconds=True,
                        max_specifications=2))
                iteration += 1

            # self.log (response_text)
            return Response(response_text)

        elif argument == "builder":
            if len(savename) < 3:
                return Response(
                    "Can't build on this playlist, the name must be longer than 3 characters",
                    delete_after=20)
            if savename in forbidden_savenames:
                return Response(
                    "Can't build on this playlist, this name is forbidden!",
                    delete_after=20)

            print("Starting the playlist builder")
            response = await self.playlist_builder(channel, author, server,
                                                   player, savename)
            return response

        elif argument in self.playlists.saved_playlists:
            infos = self.playlists.get_playlist(argument.lower(),
                                                player.playlist)
            entries = infos["entries"]

            desc_text = "```\n{}\n```\n{} entr{} ({} broken)\n{} long".format(
                infos["description"] or "This playlist doesn't have a description",
                len(infos["entries"]),
                "ies" if infos["entries"] is not 1 else "y",
                len(infos["broken_entries"]),
                format_time(
                    sum([x.duration for x in entries]),
                    combine_with_and=True,
                    replace_one=True,
                    max_specifications=2
                )
            )
            em = Embed(
                title=argument.replace("_", " ").title(),
                description=desc_text
            )
            pl_author = self.get_global_user(infos["author"])
            em.set_author(
                name=pl_author.display_name, icon_url=pl_author.avatar_url)

            if infos["cover_url"]:
                em.set_thumbnail(url=infos["cover_url"])

            entries_to_display = entries.copy()
            shuffle(entries_to_display)
            entries_to_display = entries_to_display[:15]
            vals = []
            for entry in entries_to_display:
                vals.append("{} `{}`".format(
                    nice_cut(entry.title, 50),
                    to_timestamp(entry.end_seconds)
                ))

            val = "\n".join(vals)

            em.add_field(
                name="Some of the entries:",
                value=val,
                inline=False
            )

            if len(entries) > 15:
                em.add_field(
                    name="**... and {} more**".format(len(entries) - 15),
                    value="To view them, open the playlist builder")

            em.set_footer(
                text="To edit this playlist type \"{}playlist builder {}\"".
                format(self.config.command_prefix, argument))

            await self.send_message(channel, embed=em)

            return

        return await self.cmd_help(channel, ["playlist"])

    async def playlist_builder(self, channel, author, server, player, _savename):
        if _savename not in self.playlists.saved_playlists:
            self.playlists.set_playlist([], _savename, author.id)

        def check(m):
            return (m.content.split()[0].lower() in ["add", "remove", "rename", "exit", "p", "n", "save", "extras", "search", "edit"])

        async def _get_entries_from_urls(urls, message):
            entries = []
            removed_entries = []

            entry_generator = player.playlist.get_entries_from_urls_gen(
                *urls)

            total_entries = len(urls)
            progress_message = await self.safe_send_message(channel, "{}\n{} [0%]".format(message.format(entries_left=total_entries), create_bar(0, length=20)))
            times = []
            start_time = time.time()

            progress_message_future = None

            async for ind, entry in entry_generator:
                if entry:
                    entries.append(entry)
                else:
                    removed_entries.append(ind)

                times.append(time.time() - start_time)
                start_time = time.time()

                if not progress_message_future or progress_message_future.done():
                    entries_left = total_entries - ind - 1
                    avg_time = sum(times) / float(len(times))
                    expected_time = avg_time * entries_left

                    if progress_message_future:
                        progress_message = progress_message_future.result()

                    progress_message_future = asyncio.ensure_future(self.safe_edit_message(
                        progress_message,
                        "{}\n{} [{}%]\n{} remaining".format(
                            message.format(entries_left=entries_left),
                            create_bar((ind + 1) / total_entries, length=20),
                            round(100 * (ind + 1) / total_entries),
                            format_time(
                                expected_time,
                                max_specifications=1,
                                combine_with_and=True,
                                unit_length=1
                            )
                        ),
                        keep_at_bottom=True
                    ))

            await progress_message_future
            await self.safe_delete_message(progress_message)
            return entries, removed_entries

        abort = False
        save = False
        entries_page = 0
        pl_changes = {
            "remove_entries": [],  # used for changelog
            "added_entries": [],  # changelog
            "order": None,  # changelog
            "new_name": None,
            "new_desc": None,
            "new_cover": None
        }
        savename = _savename
        user_savename = savename

        interface_string = "**{}** by **{}** ({} song{} with a total length of {})\n\n{}\n\n**You can use the following commands:**\n`add <query>`: Add a video to the playlist (this command works like the normal `{}play` command)\n`remove <index> [index 2] [index 3] [index 4]`: Remove a song from the playlist by it's index\n`edit <index>`: edit an entry\n`rename <newname>`: rename the current playlist\n`search <query>`: search for an entry\n`extras`: see the special functions\n\n`p`: previous page\n`n`: next page\n`save`: save and close the builder\n`exit`: leave the builder without saving"

        extras_string = "**{}** by **{}** ({} song{} with a total length of {})\n\n**Extra functions:**\n`sort <alphabetical | length | random>`: sort the playlist (default is alphabetical)\n`removeduplicates`: remove all duplicates from the playlist\n`description <text>`: describe this playlist\n`cover <url>`: set the cover for this playlist\n`rebuild`: clean the playlist by removing broken videos\n\n`abort`: return to main screen"

        playlist = self.playlists.get_playlist(_savename, player.playlist)
        interface_message = None

        if playlist["broken_entries"]:
            broken_entries = playlist["broken_entries"]
            if len(broken_entries) > 1:
                m = "There are {entries_left} broken/outdated entries in this playlist. I'm going to fix them, please stand by."
                new_entries, hopeless_entries = await _get_entries_from_urls([entry["url"] for entry in broken_entries], m)
                playlist["entries"].extend(new_entries)
                if hopeless_entries:
                    await self.safe_send_message(channel, "I couldn't save the following entries\n{}".format(
                        "\n".join(
                            "**" + broken_entries[entry_index]["title"] + "**" for entry_index in hopeless_entries
                        )
                    ))

            else:
                broken_entry = broken_entries[0]
                info = await self.safe_send_message(channel, "**{}** is broken, please wait while I fix it for ya.".format(broken_entry["title"]))
                new_entry = await player.playlist.get_entry(broken_entry["url"])
                if not new_entry:
                    await self.safe_send_message(channel, "Couldn't safe **{}**".format(broken_entry["title"]))
                else:
                    playlist["entries"].append(new_entry)
                    await self.safe_delete_message(info)

        while (not abort) and (not save):
            entries = playlist["entries"]
            entries_text = ""

            items_per_page = 20
            iterations, overflow = divmod(len(entries), items_per_page)

            if iterations > 0 and overflow == 0:
                iterations -= 1
                overflow += items_per_page

            start = (entries_page * items_per_page)
            end = (start + (overflow if entries_page >= iterations else
                            items_per_page)) if len(entries) > 0 else 0

            for i in range(start, end):
                entries_text += str(i + 1) + ". " + entries[i].title + "\n"
            entries_text += "\nPage {} of {}".format(entries_page + 1,
                                                     iterations + 1)

            msg_content = interface_string.format(
                user_savename.replace("_", " ").title(),
                self.get_global_user(playlist["author"]).mention,
                len(playlist["entries"]),
                "s" if len(playlist["entries"]) is not 1 else "",
                format_time(sum([x.duration for x in entries])),
                entries_text,
                self.config.command_prefix
            )

            if interface_message:
                interface_message = await self.safe_edit_message(interface_message, msg_content, keep_at_bottom=True)
            else:
                interface_message = await self.safe_send_message(
                    channel,
                    msg_content
                )
            response_message = await self.wait_for_message(
                author=author, channel=channel, check=check)

            if not response_message:
                await self.safe_delete_message(interface_message)
                abort = True
                break

            elif response_message.content.lower().startswith(self.config.command_prefix) or response_message.content.lower().startswith('exit'):
                abort = True

            elif response_message.content.lower().startswith("save"):
                save = True

            split_message = response_message.content.split()
            arguments = split_message[1:] if len(split_message) > 1 else None

            if split_message[0].lower() == "add":
                if arguments is not None:
                    msg = await self.safe_send_message(channel, "I'm working on it.")
                    query = " ".join(arguments)
                    try:
                        start_time = datetime.now()
                        entry = await player.playlist.get_entry_from_query(query)
                        if isinstance(entry, list):
                            entries, _ = await _get_entries_from_urls(entry, "Parsing {entries_left} entries")
                        else:
                            entries = [entry, ]
                        if (datetime.now() - start_time).total_seconds() > 40:
                            await self.safe_send_message(author, "Wow, that took quite a while.\nI'm done now though so come check it out!")

                        pl_changes["added_entries"].extend(
                            entries)  # just for the changelog
                        playlist["entries"].extend(entries)
                        it, ov = divmod(
                            len(playlist["entries"]), items_per_page)
                        entries_page = it - 1 if ov == 0 else it
                    except Exception as e:
                        await self.safe_send_message(
                            channel,
                            "**Something went terribly wrong there:**\n```\n{}\n```".format(
                                e)
                        )
                    await self.safe_delete_message(msg)

            elif split_message[0].lower() == "remove":
                if arguments is not None:
                    indices = []
                    for arg in arguments:
                        try:
                            index = int(arg) - 1
                        except:
                            index = -1

                        if index >= 0 and index < len(playlist["entries"]):
                            indices.append(index)

                    pl_changes["remove_entries"].extend(
                        [(ind, playlist["entries"][ind]) for ind in indices])  # for the changelog
                    playlist["entries"] = [
                        playlist["entries"][x]
                        for x in range(len(playlist["entries"]))
                        if x not in indices
                    ]
            elif split_message[0].lower() == "edit":
                if arguments is not None and arguments[0].isnumeric():
                    index = int(arguments[0]) - 1

                    if 0 > index >= len(playlist["entries"]):
                        continue

                    entry = playlist["entries"].pop(index)

                    print("starting entry editor")
                    new_entry = await self.entry_manipulator(player, channel, author, entry) or entry

                    playlist["entries"].insert(index, new_entry)

            elif split_message[0].lower() == "rename":
                if arguments is not None and len(
                        arguments[0]
                ) >= 3 and arguments[0] not in self.playlists.saved_playlists:
                    pl_changes["new_name"] = re.sub("\W", "",
                                                    arguments[0].lower())
                    user_savename = pl_changes["new_name"]

            elif split_message[0].lower() == "search":
                if not arguments:
                    msg = await self.safe_send_message(channel, "Please provide a query to search for!")
                    asyncio.sleep(3)
                    await self.safe_delete_message(msg)
                    continue

                query = " ".join(arguments)
                results = self.playlists.search_entries_in_playlist(
                    player.playlist, playlist, query, certainty_threshold=.55)

                if not results:
                    msg = await self.safe_send_message(channel, "**Didn't find anything**")
                    asyncio.sleep(4)
                    await self.safe_delete_message(msg)
                    continue

                lines = []
                for certainty, entry in results[:5]:
                    entry_index = entries.index(entry)
                    lines.append(
                        "`{}.` **{}**".format(entry_index, entry.title))

                msg = "**Found the following entries:**\n" + \
                    "\n".join(lines) + \
                    "\n*Send any message to close this message*"
                msg = await self.safe_send_message(channel, msg)

                resp = await self.wait_for_message(timeout=60, author=author, channel=channel)
                if resp:
                    await self.safe_delete_message(resp)
                await self.safe_delete_message(msg)

                continue

            elif split_message[0].lower() == "extras":

                def extras_check(m):
                    return (m.content.split()[0].lower() in [
                        "abort", "sort", "removeduplicates", "rebuild", "cover", "description"
                    ])

                extras_message = await self.safe_send_message(
                    channel,
                    extras_string.format(
                        user_savename.replace("_", " ").title(),
                        self.get_global_user(playlist["author"]).mention,
                        len(playlist["entries"]), "s"
                        if len(playlist["entries"]) is not 1 else "",
                        format_time(sum([x.duration for x in entries]))))
                resp = await self.wait_for_message(
                    author=author, channel=channel, check=extras_check)

                if not resp.content.lower().startswith(self.config.command_prefix) and not resp.content.lower().startswith("abort"):
                    _cmd = resp.content.split()
                    cmd = _cmd[0].lower()
                    args = _cmd[1:] if len(_cmd) > 1 else None

                    if cmd == "sort":
                        sort_method = args[0].lower() if args is not None and args[0].lower() in [
                            "alphabetical", "length", "random"] else "alphabetical"

                        if sort_method == "alphabetical":
                            playlist["entries"] = sorted(
                                entries, key=lambda entry: entry.title)
                        elif sort_method == "length":
                            playlist["entries"] = sorted(
                                entries, key=lambda entry: entry.duration)
                        elif sort_method == "random":
                            new_ordered = entries
                            shuffle(new_ordered)
                            playlist["entries"] = new_ordered

                        # bodge for changelog
                        pl_changes["order"] = sort_method

                    elif cmd == "removeduplicates":
                        urls = []
                        new_list = []
                        for entry in entries:
                            if entry.url not in urls:
                                urls.append(entry.url)
                                new_list.append(entry)

                        playlist["entries"] = new_list

                    elif cmd == "rebuild":
                        entry_urls = [entry.url for entry in entries]
                        rebuild_safe_entries, rebuild_removed_entries = await _get_entries_from_urls(entry_urls, "Rebuilding the playlist. This might take a while, please hold on.")

                        pl_changes["remove_entries"].extend(
                            [(ind, playlist["entries"][ind]) for ind in rebuild_removed_entries])  # for the changelog
                        playlist["entries"] = rebuild_safe_entries
                        it, ov = divmod(
                            len(playlist["entries"]), items_per_page)
                        entries_page = it - 1 if ov == 0 else it

                    elif cmd == "description":
                        desc = resp.content[len(cmd):].strip()
                        if desc:
                            pl_changes["new_desc"] = desc
                        else:
                            msg = await self.safe_send_message(channel, "**Please provide a description**")
                            asyncio.sleep(4)
                            await self.safe_delete_message(msg)
                            continue
                    elif cmd == "cover":
                        if not args:
                            msg = await self.safe_send_message(channel, "**Please provide an url**")
                            asyncio.sleep(4)
                            await self.safe_delete_message(msg)
                            continue
                        url = args[0].strip()
                        if is_image(url):
                            pl_changes["new_cover"] = url
                        else:
                            msg = await self.safe_send_message(channel, "**This isn't an image**")
                            asyncio.sleep(4)
                            await self.safe_delete_message(msg)
                            continue

                await self.safe_delete_message(extras_message)
                await self.safe_delete_message(resp)
                await self.safe_delete_message(response_message)
                continue

            elif split_message[0].lower() == "p":
                entries_page = (entries_page - 1) % (iterations + 1)

            elif split_message[0].lower() == "n":
                entries_page = (entries_page + 1) % (iterations + 1)

            await self.safe_delete_message(response_message)

        await self.safe_delete_message(interface_message)

        if abort:
            return Response("Closed **{}** without saving".format(savename))
            print("Closed the playlist builder")

        if save:
            if pl_changes["added_entries"] or pl_changes["remove_entries"] or pl_changes["new_name"] or pl_changes["order"] or pl_changes["new_desc"] or pl_changes["new_cover"]:
                c_log = "**CHANGES**\n\n"
                if pl_changes["added_entries"]:
                    new_entries_string = "\n".join(["    `{}.` {}".format(ind, nice_cut(
                        entry.title, 40)) for ind, entry in enumerate(pl_changes["added_entries"], 1)])
                    c_log += "**New entries**\n{}\n".format(new_entries_string)
                if pl_changes["remove_entries"]:
                    removed_entries_string = "\n".join(
                        ["    `{}.` {}".format(ind + 1, nice_cut(entry.title, 40)) for ind, entry in pl_changes["remove_entries"]])
                    c_log += "**Removed entries**\n{}\n".format(
                        removed_entries_string)
                if pl_changes["order"]:
                    c_log += "**Changed order**\n    To `{}`".format(
                        pl_changes["order"])
                if pl_changes["new_name"]:
                    c_log += "**Renamed playlist**\n    From `{}` to `{}`".format(
                        savename.title(), pl_changes["new_name"].title())
                if pl_changes["new_desc"]:
                    c_log += "**Changed description**\n    To `{}`".format(
                        pl_changes["new_description"])
                if pl_changes["new_cover"]:
                    c_log += "**Changed cover**\n    To `{}`".format(
                        pl_changes["new_cover"])
            else:
                c_log = "No changes were made"

            self.playlists.edit_playlist(
                savename,
                player.playlist,
                all_entries=playlist["entries"],
                new_name=pl_changes["new_name"],
                new_description=pl_changes["new_desc"],
                new_cover=pl_changes["new_cover"]
            )
            print("Closed the playlist builder and saved the playlist")

            return Response("Successfully saved **{}**\n\n{}".format(
                user_savename.replace("_", " ").title(), c_log))

    async def entry_manipulator(self, player, channel, author, entry):
        def get_entry_type(fields):
            keys = fields.keys()

            if "sub_queue" in keys:
                return set(), TimestampEntry

            missing_for_spotify = {
                "album", "artist", "artist_image_url", "cover_url"} - keys
            if not missing_for_spotify:
                return set(), SpotifyEntry

            return missing_for_spotify, YoutubeEntry

        def build_new_entry(fields):
            _, entry_type = get_entry_type(fields)

            args = {
                "title": fields["title"],
                "queue": player.playlist,
                "video_id": fields["_video_id"],
                "url": fields["_url"],
                "duration": fields["_duration"],
                "thumbnail": fields["thumbnail"],
                "description": fields["_description"]
            }

            if entry_type is SpotifyEntry:
                title = fields["title"]
                duration = fields["duration"]
                album = fields["album"]
                artist = fields["artist"]
                artist_image = fields["artist_image_url"]
                cover = fields["cover_url"]

                args["spotify_data"] = SpotifyTrack.custom_track(
                    title, duration, album, artist, artist_image, cover)
            elif entry_type is TimestampEntry:
                args["sub_queue"] = timestamp_to_queue(fields["sub_queue"])

            return entry_type(**args)

        entry_fields = {
            "__title": entry._title,
            "_video_id": entry.video_id,
            "_url": entry.url,
            "_description": entry.description,
            "_duration": entry.duration,
            "title": entry.title,
            "thumbnail": entry.thumbnail,
        }
        if isinstance(entry, SpotifyEntry):
            entry_fields.update({
                "title": entry.song_name,
                "artist": entry.artist,
                "artist_image_url": choice(entry.artists).image,
                "album": entry.album.name,
                "cover_url": entry.cover
            })
        elif isinstance(entry, TimestampEntry):
            entry_fields.update({
                "title": entry.whole_title,
                "sub_queue": {entry["start"]: entry["name"] for entry in entry.sub_queue}
            })

        commands = "\n".join([
            "`set <property> <query>` set a <property> (i.e. the cover) to <query>",
            "`remove <property>` remove a <property> from an entry",
            "`timestamp <remove | set> <timestamp> <title>` manipulate a timestamp",
            "`exit` abort",
            "`save` apply changes"
        ])
        error_format = "**Error**\n{error_message}\n\n"
        information_format = ""
        interface_format = "**ENTRY EDITOR**\n\n{error}---\n{fields}\n---\n{timestamps}\n{information}\n\n**Commands**\n" + commands

        error = None

        _interface_message = None

        async def send_interface_message():
            nonlocal _interface_message
            nonlocal error

            error_text = ""
            if error:
                error_text = error_format.format(error_message=error)
                error = None

            sub_queue = entry_fields.get("sub_queue", None)
            if sub_queue:
                lines = ["", "**timestamps**:"]
                sub_queue_items = sorted(
                    list(sub_queue.items()), key=lambda el: el[0])
                for ind, (start, title) in enumerate(sub_queue_items):
                    next_start = sub_queue_items[
                        ind + 1][0] if ind + 1 < len(sub_queue_items) else entry.duration
                    duration = next_start - start

                    lines.append(
                        "   `{}.` **{}** ({})".format(to_timestamp(start),
                                                      title, to_timestamp(duration))
                    )

                timestamps = "\n".join(lines) + 2 * "\n"
            else:
                timestamps = ""

            fields_text = "\n".join([
                "**title**: " +
                wrap_string(entry_fields.get("title", "Unknown"), "`"),
                "**album**: " +
                wrap_string(entry_fields.get("album", "Unknown"), "`"),
                "**artist**: " +
                wrap_string(entry_fields.get("artist", "Unknown"), "`"),
                "**artist image**: " +
                wrap_string(entry_fields.get("artist_image_url", "None"), "`"),
                "**cover**: " +
                wrap_string(entry_fields.get("cover_url", "None"), "`"),
                "**thumbnail**: " +
                wrap_string(entry_fields.get("thumbnail", "None"), "`")
            ])

            missing, current_type = get_entry_type(entry_fields)
            if current_type is TimestampEntry:
                info_text = "This is a TimestampEntry. Remove the sub queue to get a normal entry."
            elif current_type is SpotifyEntry:
                info_text = "This is a SpotifyEntry. That's as good as it gets"
            else:
                missing = list(missing)
                beautified_parameter = {
                    "artist": "the **artist**",
                    "album": "an **album**",
                    "artist_image_url": "a **picture of the artist**",
                    "cover_url": "a **cover**"
                }

                properties_needed = ""
                if len(missing) > 1:
                    properties_needed = ", ".join(beautified_parameter.get(m, m)
                                                  for m in missing[:-1]) + " and "

                properties_needed += beautified_parameter[missing[-1]]

                info_text = "This is currently a normal entry. Provide {} in order to get to a SpotifyEntry".format(
                    properties_needed)

            msg_text = interface_format.format(
                fields=fields_text, information=info_text, error=error_text, timestamps=timestamps)

            if not _interface_message:
                _interface_message = await self.safe_send_message(channel, msg_text)
            else:
                _interface_message = await self.safe_edit_message(
                    _interface_message,
                    msg_text,
                    keep_at_bottom=True,
                    send_if_fail=True
                )

        while True:
            await send_interface_message()
            response = await self.wait_for_message(timeout=None, author=author, channel=channel, check=lambda msg: msg.content.lower().strip().startswith(("set", "remove", "timestamp", "exit", "abort", "save")))

            command, _, _rest = response.content.strip().partition(" ")
            command = command.lower()

            targets = {
                "title": "title",
                "artist image": "artist_image_url",
                "artist": "artist",
                "album": "album",
                "cover": "cover_url",
                "thumbnail": "thumbnail",
                "timestamps": "sub_queue"
            }

            responsible_text, property_target = (
                [(k, t) for k, t in targets.items() if _rest.lower().startswith(k)] or (("", None),))[0]
            rest = _rest[len(responsible_text):]

            if command == "set":
                if property_target:
                    if rest:
                        if property_target == "sub_queue":
                            error = "You can't set timestamps like this"
                        else:
                            if property_target not in ("cover_url", "thumbnail", "artist_image_url") or is_image(rest):
                                entry_fields[property_target] = rest
                            else:
                                error = "That's not an image!"
                    else:
                        error = "Please also provide some text"
                else:
                    error = "Please provide a property"
            elif command == "remove":
                if property_target:
                    entry_fields.pop(property_target, None)
                else:
                    error = "Please provide a property"
            elif command == "timestamp":
                parts = _rest.split()
                if len(parts) >= 2:
                    control, selector, *title = parts
                    control = control.lower().strip()
                    selector = parse_timestamp(selector)

                    if selector is not None:
                        if control == "remove":
                            item = entry_fields[
                                "sub_queue"].pop(selector, None)
                            if not item:
                                error = "Couldn't find that sub-entry"
                        elif control == "set":
                            if title:
                                title = " ".join(title)
                                entry_fields["sub_queue"][selector] = title
                            else:
                                error = "Provide a title, please!"
                    else:
                        error = "Don't know what your <timestamp>'s supposed to mean'"
                else:
                    error = "Be sure to specify what you want to do and the <timestamp>"
            elif command == "save":
                await self.safe_delete_message(response)
                await self.safe_delete_message(_interface_message)

                return build_new_entry(entry_fields)
            elif command in ("exit", "abort"):
                await self.safe_delete_message(response)
                await self.safe_delete_message(_interface_message)

                return None

            await self.safe_delete_message(response)

    @command_info("2.9.2", 1479945600, {
        "3.3.6": (1497387101, "added the missing \"s\", should be working again"),
        "3.4.4": (1497611753, "Changed command name from \"addplayingtoplaylist\" to \"addtoplaylist\", thanks Paulo"),
        "3.5.5": (1497792167, "Now displaying what entry has been added to the playlist"),
        "3.5.8": (1497826743, "Even more information displaying"),
        "3.6.1": (1497972538, "now accepts a query parameter which adds a song to the playlist like the `play` command does so for the queue"),
        "3.8.9": (1499516220, "Part of the `Giesenesis` rewrite")
    })
    async def cmd_addtoplaylist(self, channel, author, player, playlistname, query=None):
        """
        ///|Usage
        `{command_prefix}addtoplaylist <playlistname> [link | name]`
        ///|Explanation
        Add the current entry to a playlist.
        If you either provide a link or a name, that song is added to the queue.
        """

        if playlistname is None:
            return Response(
                "Please specify the playlist's name!")

        playlistname = playlistname.lower()

        await self.send_typing(channel)

        if query:
            add_entry = await player.playlist.get_entry_from_query(query, channel=channel, author=author)
        else:
            if not player.current_entry:
                return Response(
                    "There's nothing playing right now so I can't add it to your playlist..."
                )

            add_entry = player.current_entry
            if isinstance(add_entry, TimestampEntry):
                current_timestamp = add_entry.current_sub_entry["name"]
                # this looks ugly but eh, it works
                try:
                    add_entry = await player.playlist.get_entry_from_query(current_timestamp, channel=channel, author=author)
                except:
                    pass  # just go ahead and add the whole thing, what do I care :3

        if playlistname not in self.playlists.saved_playlists:
            if len(playlistname) < 3:
                return Response(
                    "Your name is too short. Please choose one with at least three letters."
                )
            self.playlists.set_playlist([add_entry], playlistname, author.id)
            return Response("Created a new playlist `{}` and added **{}**.".format(playlistname.title(),
                                                                                   add_entry.title))

        res = self.playlists.in_playlist(
            player.playlist, playlistname, add_entry)
        if res:
            notification = await self.safe_send_message(
                channel,
                "There's already an entry similar to this one in `{}`\n**{}**\n\nDo you still want to add **{}**? `yes`/`no`".format(
                    playlistname.title(),
                    res.title,
                    add_entry.title
                )
            )
            response = await self.wait_for_message(timeout=60, channel=channel, author=author, check=lambda msg: msg.content.lower().strip() in ["y", "yes", "no", "n"])
            await self.safe_delete_message(notification)
            if response:
                await self.safe_delete_message(response)

            if not (response and response.content.lower().strip().startswith("y")):
                return Response("Didn't add **{}** to `{}`".format(add_entry.title, playlistname.title()))

        self.playlists.edit_playlist(
            playlistname, player.playlist, new_entries=[add_entry])
        return Response("Added **{}** to playlist `{}`.".format(add_entry.title, playlistname.title()))

    @command_info("2.9.2", 1479945600, {
        "3.3.6": (1497387101, "added the missing \"s\", should be working again"),
        "3.4.4": (1497611753, "Changed command name from \"removeplayingfromplaylist\" to \"removefromplaylist\", thanks Paulo"),
        "3.5.8": (1497826917, "Now displaying the names of the song and the playlist"),
        "3.6.5": (1498152365, "Don't require a playlistname argument anymore but take it from the entry itself"),
        "3.8.9": (1499516220, "Part of the `Giesenesis` rewrite")
    })
    async def cmd_removefromplaylist(self, channel, author, player, playlistname=None):
        """
        ///|Usage
        `{command_prefix}removefromplaylist [playlistname]`
        ///|Explanation
        Remove the current entry from its playlist or from the specified playlist.
        """

        if not player.current_entry:
            return Response("There's nothing playing right now so I can hardly remove it from your playlist...")

        if not playlistname:
            if "playlist" in player.current_entry.meta:
                self.playlists.edit_playlist(
                    playlist_name, player.playlist, remove_entries=[player.current_entry, ])
                return Response("Removed **{}** from playlist `{}`".format(player.current_entry.title, playlist_name.title()))
            else:
                return Response("Please specify the playlist's name!")

        playlistname = playlistname.lower()

        remove_entry = player.current_entry
        if isinstance(remove_entry, TimestampEntry):
            current_timestamp = remove_entry.current_sub_entry["name"]
            remove_entry = await player.playlist.get_entry_from_query(current_timestamp, channel=channel, author=author)

        if playlistname not in self.playlists.saved_playlists:
            return Response("There's no playlist `{}`.".format(playlistname.title()))

        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[remove_entry])
        return Response("Removed **{}** from playlist `{}`.".format(remove_entry.title, playlistname))
