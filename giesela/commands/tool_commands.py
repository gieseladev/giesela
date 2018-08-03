import re
from random import choice

from discord import ChannelType, Embed
from discord.utils import find

from giesela.utils import (Response, block_user, command_info)


class ToolCommands:

    @command_info("2.0.3", 1485516420, {
        "3.7.5": (1481827320, "The command finally works like it should"),
        "3.9.9": (1499977057, "moving Giesela too"),
        "4.1.8": (1500882643, "Updating to new player model")
    })
    async def cmd_moveus(self, server, author, user_mentions, leftover_args):
        """
        ///|Usage
        `{command_prefix}moveus <channel name>`
        ///|Explanation
        Move everyone in your current channel to another one!
        """

        target_channel = None
        target = " ".join(leftover_args)

        if user_mentions:
            target_channel = user_mentions[0].voice.voice_channel

        if not target_channel and target:
            target_channel = find(
                lambda vc: vc.type == ChannelType.voice and target.lower().strip() in vc.name.lower().strip(),
                server.channels
            )

        if target_channel is None:
            return Response("Can't resolve the target channel!")

        author_channel = author.voice.voice_channel
        voice_members = author_channel.voice_members

        move_myself = False
        if server.me in voice_members:
            voice_members.remove(server.me)
            move_myself = True

        for voice_member in voice_members:
            await voice_member.edit(voice_channel=target_channel)

        if move_myself:
            await self.get_player(server, target_channel)

    @command_info("1.0.0", 1477180800, {
        "2.0.2": (1481827560, "Can now use @mentions to \"goto\" a user"),
        "4.1.8": (1500881315, "Merging with old goto command")
    })
    async def cmd_summon(self, server, author, user_mentions, leftover_args):
        """
        Usage:
            {command_prefix}summon [@mention | name]

        Call the bot to the summoner's voice channel.
        """

        target_channel = None
        target = " ".join(leftover_args)

        if user_mentions:
            target_channel = user_mentions[0].voice.voice_channel

        if not target_channel and target:
            target_channel = find(lambda vc: vc.type == ChannelType.voice and target.lower().strip() in vc.name.lower().strip(), server.channels)

        if not target_channel:
            target_channel = author.voice_channel

        if not target_channel:
            return Response("Couldn't find voic channel")

        player = await self.get_player(server, target_channel)

        if player.is_stopped:
            player.play()

    @command_info("2.2.1", 1493757540, {
        "3.7.8": (1499019245, "Fixed quoting by content.")
    })
    async def cmd_quote(self, channel, message, leftover_args):
        """
        ///|Usage
        `{command_prefix}quote [#channel] <message id> [message id...]`
        `{command_prefix}quote [#channel] [@mention] \"<message content>\"`
        ///|Explanation
        Quote a message
        """

        quote_to_channel = channel
        target_author = None

        if message.channel_mentions:
            channel = message.channel_mentions[0]
            leftover_args = leftover_args[1:]

        if message.mentions:
            target_author = message.mentions[0]
            leftover_args = leftover_args[1:]

        if len(leftover_args) < 1:
            return Response("Please specify the message you want to quote")

        message_content = " ".join(leftover_args)
        if (message_content[0] == "\"" and message_content[-1] == "\"") or re.search(r"\D", message_content) is not None:
            message_content = message_content.replace("\"", "")
            async for msg in channel.history(limit=3000):
                if msg.id != message.id and message_content.lower().strip() in msg.content.lower().strip():
                    if target_author is None or target_author.id == msg.author.id:
                        leftover_args = [msg.id, ]
                        break
            else:
                if target_author is not None:
                    return Response("Didn't find a message with that content from {}".format(target_author.mention))
                else:
                    return Response("Didn't find a message with that content")

        await self.safe_delete_message(message)
        for message_id in leftover_args:
            try:
                quote_message = await self.get_message(channel, message_id)
            except:
                return Response("Didn't find a message with the id `{}`".
                                format(message_id))

            author_data = {
                "name": quote_message.author.display_name,
                "icon_url": quote_message.author.avatar_url
            }
            embed_data = {
                "description": quote_message.content,
                "timestamp": quote_message.timestamp,
                "colour": quote_message.author.colour
            }
            em = Embed(**embed_data)
            em.set_author(**author_data)
            await self.send_message(quote_to_channel, embed=em)
        return

    @block_user
    @command_info("2.0.3", 1486054560, {
        "3.7.2": (1498252803, "no arguments provided crash Fixed")
    })
    async def cmd_random(self, channel, author, leftover_args):
        """
        ///|Basic
        `{command_prefix}random <item1>, <item2>, [item3], [item4]`
        ///|Use an existing set
        `{command_prefix}random <setname>`
        ///|List all the existing sets
        `{command_prefix}random list`
        ///|Creation
        `{command_prefix}random create <name>, <option1>, <option2>, [option3], [option4]`
        ///|Editing
        `{command_prefix}random edit <name>, [add | remove | replace], <item> [, item2, item3]`
        ///|Removal
        `{command_prefix}random remove <name>`
        ///|Explanation
        Choose a random item out of a list or use a pre-defined list.
        """

        if not leftover_args:
            return Response("Why u gotta be stupid?")

        items = [x.strip() for x in " ".join(leftover_args).split(",") if x is not ""]

        if len(items) <= 0 or items is None:
            return Response(
                "Is your name \"{0}\" by any chance?\n(This is not how this command works. Use `{1}help random` to find out how not to be a stupid **{0}** anymore)".
                    format(author.name, self.config.command_prefix),
                delete_after=30)

        await self.safe_send_message(channel, "I choose **" + choice(items) + "**")
