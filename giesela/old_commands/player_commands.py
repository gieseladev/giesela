from giesela import exceptions
from giesela.entry import TimestampEntry
from giesela.utils import (Response, block_user, command_info, create_bar,
                           owner_only, parse_timestamp)


class PlayerCommands:

    @command_info("1.0.0", 1477180800, {
        "3.5.2": (1497712233, "Updated documentaion for this command"),
        "3.8.9": (1499461647, "Part of the `Giesenesis` rewrite"),
        "4.9.9": (1508219627, "Pause can unpause as well just because")
    })
    async def cmd_pause(self, player):
        """
        ///|Usage
        `{command_prefix}pause`
        ///|Explanation
        Pause playback of the current song. If the player is paused, it will unpause.
        """

        if player.is_playing:
            player.pause()
        elif player.is_paused:
            player.resume()
        else:
            return Response("Cannot pause what is not playing")

    @command_info("1.0.0", 1477180800, {
        "3.5.2": (1497712233, "Updated documentaion for this command"),
        "3.8.9": (1499461647, "Part of the `Giesenesis` rewrite"),
        "3.0.5": (1500533467, "fixed typo")
    })
    async def cmd_resume(self, player):
        """
        ///|Usage
        `{command_prefix}resume`
        ///|Explanation
        Resumes playback of the current song.
        """

        if player.is_paused:
            player.resume()

        else:
            return Response("Hard to unpause something that's not paused, amirite?")

    @command_info("4.9.9", 1508219263, {
        "4.9.9": (1508224340, "Fixed stop logic to avoid total kill on player")
    })
    async def cmd_stop(self, player):
        """
        ///|Usage
        `{command_prefix}stop`
        ///|Explanation
        Stops the player completely and removes all entries from the queue.
        """

        player.queue.clear()
        player.stop()

    @command_info("1.0.0", 1477180800, {
        "3.5.2": (1497712233, "Updated documentaion for this command"),
        "3.8.8": (1499421755, "improved volume bar"),
        "4.5.0": (1501792292, "Switched to a non-linear volume scale system"),
        "4.5.8": (1502197622, "Muting is a thing now.")
    })
    async def cmd_volume(self, message, player, leftover_args):
        """
        ///|Usage
        `{command_prefix}volume [+ | -][volume]`
        ///|Explanation
        Sets the playback volume. Accepted values are from 1 to 100.
        Putting + or - before the volume will make the volume change relative to the current volume.
        """

        new_volume = "".join(leftover_args)

        if not new_volume:
            return Response("Current volume: {}%\n{}".format(
                int(player.volume * 100), create_bar(player.volume, 20)))

        relative = False
        special_operation = None
        if new_volume[0] in "+-":
            relative = True
        elif new_volume[0] in "*/%":
            special_operation = new_volume[0]
            new_volume = new_volume[1:]
        elif new_volume in ("mute", "muted", "none", "silent"):
            new_volume = 0

        try:
            new_volume = int(new_volume)

        except ValueError:
            raise exceptions.CommandError(
                "{} is not a valid number".format(new_volume))

        if relative:
            vol_change = new_volume
            new_volume += (player.volume * 100)

        if special_operation is not None:
            operations = {
                "*": lambda x, y: x * y,
                "/": lambda x, y: x / y,
                "%": lambda x, y: x % y,
            }
            op = operations[special_operation]
            new_volume = op(player.volume * 100, new_volume)

        old_volume = int(player.volume * 100)

        if 0 <= new_volume <= 100:
            player.volume = new_volume / 100.0

            return Response(
                "updated volume from %d to %d" % (old_volume, new_volume),
                reply=True)

        else:
            if relative:
                raise exceptions.CommandError(
                    "Unreasonable volume change provided: {}{:+} -> {}%.  Provide a change between {} and {:+}.".
                    format(old_volume, vol_change, old_volume + vol_change,
                           1 - old_volume, 100 - old_volume))
            else:
                raise exceptions.CommandError(
                    "Unreasonable volume provided: {}%. Provide a value between 1 and 100.".
                    format(new_volume))

    @command_info("2.0.3", 1487538840, {
        "3.3.7": (1497471402, "changed command from \"skipto\" to \"seek\""),
        "4.7.7": (1504104996, "New seeking system")
    })
    async def cmd_seek(self, player, timestamp):
        """
        ///|Usage
        `{command_prefix}seek <timestamp>`
        ///|Explanation
        Go to the given timestamp formatted (minutes:seconds)
        """

        secs = parse_timestamp(timestamp)
        if secs is None:
            return Response(
                "Please provide a valid timestamp")

        if player.current_entry is None:
            return Response("Nothing playing!")

        if not player.seek(secs):
            return Response(
                "Timestamp exceeds song duration!")

    @command_info("2.2.1", 1493975700, {
        "3.8.9": (1499516220, "Part of the `Giesenesis` rewrite"),
        "4.7.7": (1504104996, "New seeking system")
    })
    async def cmd_fwd(self, player, timestamp):
        """
        ///|Usage
        `{command_prefix}fwd <timestamp>`
        ///|Explanation
        Forward <timestamp> into the current entry
        """

        secs = parse_timestamp(timestamp)
        if secs is None:
            return Response(
                "Please provide a valid timestamp")

        if player.current_entry is None:
            return Response("Nothing playing!")

        if not player.seek(player.progress + secs):
            return Response(
                "Timestamp exceeds song duration!")

    @command_info("2.2.1", 1493975700, {
        "3.4.3": (1497609912, "Can now rewind past the current song"),
        "3.8.9": (1499516220, "Part of the `Giesenesis` rewrite"),
        "4.7.7": (1504104996, "New seeking system")
    })
    async def cmd_rwd(self, player, timestamp=None):
        """
        ///|Usage
        `{command_prefix}rwd [timestamp]`
        ///|Explanation
        Rewind <timestamp> into the current entry or if the current entry is a timestamp-entry, rewind to the previous song
        """

        if player.current_entry is None:
            return Response("Nothing playing!")

        if timestamp is None:
            if isinstance(player.current_entry, TimestampEntry):
                current_song = player.current_entry.current_sub_entry
                ind = current_song["index"]
                progress = current_song["progress"]

                if ind == 0:
                    secs = 0
                else:
                    if progress < 15:
                        secs = player.current_entry.sub_queue[ind - 1]["start"]
                    else:
                        secs = current_song["start"]

            else:
                return Response("Please provide a valid timestamp")
        else:
            secs = player.progress - parse_timestamp(timestamp)

        if not secs:
            if not player.queue.history:
                return Response(
                    "Please provide a valid timestamp (no history to rewind into)")
            else:
                # just replay the last entry
                last_entry = player.queue.history[0]
                player.play_entry(last_entry)
                return

        if secs < 0:
            if not player.queue.history:
                secs = 0
            else:
                last_entry = player.queue.history[0]
                # since secs is negative I can just add it
                if not last_entry.set_start(last_entry.end_seconds + secs):
                    # mostly because I'm lazy
                    return Response(
                        "I won't go further back than one song, that's just mad"
                    )
                player.play_entry(last_entry)
                return

        if not player.seek(secs):
            return Response(
                "Timestamp exceeds song duration!")

    async def cmd_repeat(self, player):
        """
        ///|Usage
        `{command_prefix}repeat`
        ///|Explanation
        Cycles through the repeat options. Default is no repeat, switchable to repeat all or repeat current song.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't change repeat mode! The player is not playing!",
                expire_in=20)

        player.repeat()

        if player.is_repeatNone:
            return Response(":play_pause: Repeat mode: None")
        if player.is_repeatAll:
            return Response(":repeat: Repeat mode: All")
        if player.is_repeatSingle:
            return Response(
                ":repeat_one: Repeat mode: Single")
