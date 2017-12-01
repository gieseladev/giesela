import traceback
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from textwrap import indent

import aiohttp
import discord

from giesela import exceptions
from giesela.settings import Settings
from giesela.utils import (Response, block_user, command_info, escape_dis,
                           owner_only)


class AdminCommands:

    async def cmd_blacklist(self, message, user_mentions, option, something):
        """
        ///|Usage
        {command_prefix}blacklist [ + | - | add | remove ] @UserName [@UserName2 ...]
        ///|Explanation
        Add or remove users to the blacklist.
        """

        if not user_mentions:
            raise exceptions.CommandError("No users listed.", expire_in=20)

        if option not in ["+", "-", "add", "remove"]:
            raise exceptions.CommandError(
                "Invalid option \" % s\" specified, use +, -, add, or remove" %
                option)

        for user in user_mentions.copy():
            if user.id == self.config.owner_id:
                print(
                    "[Commands:Blacklist] The owner cannot be blacklisted.")
                user_mentions.remove(user)

        old_len = len(self.blacklist)

        if option in ["+", "add"]:
            self.blacklist.update(user.id for user in user_mentions)

            write_file(self.config.blacklist_file, self.blacklist)

            return Response(
                "%s users have been added to the blacklist" %
                (len(self.blacklist) - old_len),
                reply=True)

        else:
            if self.blacklist.isdisjoint(user.id for user in user_mentions):
                return Response(
                    "none of those users are in the blacklist.",
                    reply=True)

            else:
                self.blacklist.difference_update(user.id
                                                 for user in user_mentions)
                write_file(self.config.blacklist_file, self.blacklist)

                return Response(
                    "%s users have been removed from the blacklist" %
                    (old_len - len(self.blacklist)),
                    reply=True)

    async def cmd_id(self, author, user_mentions):
        """
        ///|Usage
        {command_prefix}id [@user]
        ///|Explanation
        Tells the user their id or the id of another user.
        """
        if not user_mentions:
            return Response(
                "your id is `%s`" % author.id, reply=True)
        else:
            usr = user_mentions[0]
            return Response(
                "%s's id is `%s`" % (usr.name, usr.id),
                reply=True)

    @owner_only
    async def cmd_joinserver(self, message, server_link=None):
        """
        Usage:
            {command_prefix}joinserver invite_link

        Asks the bot to join a server.  Note: Bot accounts cannot use invite links.
        """

        if self.user.bot:
            url = await self.generate_invite_link()
            return Response(
                "Bot accounts can't use invite links!  Click here to invite me: \n{}".
                format(url),
                reply=True,
                delete_after=30)

        try:
            if server_link:
                await self.accept_invite(server_link)
                return Response(":+1:")

        except:
            raise exceptions.CommandError(
                "Invalid URL provided:\n{}\n".format(server_link))

    async def cmd_listids(self, server, author, leftover_args, cat="all"):
        """
        Usage:
            {command_prefix}listids [categories]

        Lists the ids for various things.  Categories are:
           all, users, roles, channels
        """

        cats = ["channels", "roles", "users"]

        if cat not in cats and cat != "all":
            return Response(
                "Valid categories: " + " ".join(["`%s`" % c for c in cats]),
                reply=True,
                delete_after=25)

        if cat == "all":
            requested_cats = cats
        else:
            requested_cats = [cat] + [c.strip(",") for c in leftover_args]

        data = ["Your ID: %s" % author.id]

        for cur_cat in requested_cats:
            rawudata = None

            if cur_cat == "users":
                data.append("\nUser IDs:")
                rawudata = [
                    "%s #%s: %s" % (m.name, m.discriminator, m.id)
                    for m in server.members
                ]

            elif cur_cat == "roles":
                data.append("\nRole IDs:")
                rawudata = ["%s: %s" % (r.name, r.id) for r in server.roles]

            elif cur_cat == "channels":
                data.append("\nText Channel IDs:")
                tchans = [
                    c for c in server.channels
                    if c.type == discord.ChannelType.text
                ]
                rawudata = ["%s: %s" % (c.name, c.id) for c in tchans]

                rawudata.append("\nVoice Channel IDs:")
                vchans = [
                    c for c in server.channels
                    if c.type == discord.ChannelType.voice
                ]
                rawudata.extend("%s: %s" % (c.name, c.id) for c in vchans)

            if rawudata:
                data.extend(rawudata)

        with BytesIO() as sdata:
            sdata.writelines(d.encode("utf8") + b"\n" for d in data)
            sdata.seek(0)

            await self.send_file(
                author,
                sdata,
                filename="%s-ids-%s.txt" % (server.name.replace(" ", "_"),
                                            cat))

        return Response(":mailbox_with_mail:")

    @owner_only
    async def cmd_setname(self, leftover_args, name):
        """
        Usage:
            {command_prefix}setname name

        Changes the bot's username.
        Note: This operation is limited by discord to twice per hour.
        """

        name = " ".join([name, *leftover_args])

        try:
            await self.edit_profile(username=name)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response(":ok_hand:")

    @owner_only
    async def cmd_setnick(self, server, channel, leftover_args, nick):
        """
        Usage:
            {command_prefix}setnick nick

        Changes the bot's nickname.
        """

        if not channel.permissions_for(server.me).change_nickname:
            raise exceptions.CommandError(
                "Unable to change nickname: no permission.")

        nick = " ".join([nick, *leftover_args])

        try:
            await self.change_nickname(server.me, nick)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response(":ok_hand:")

    @owner_only
    async def cmd_setavatar(self, message, url=None):
        """
        Usage:
            {command_prefix}setavatar [url]

        Changes the bot's avatar.
        Attaching a file and leaving the url parameter blank also works.
        """

        if message.attachments:
            thing = message.attachments[0]["url"]
        else:
            thing = url.strip("<>")

        try:
            with aiohttp.Timeout(10):
                async with self.aiosession.get(thing) as res:
                    await self.edit_profile(avatar=await res.read())

        except Exception as e:
            raise exceptions.CommandError(
                "Unable to change avatar: %s" % e, expire_in=20)

        return Response(":ok_hand:")

    async def cmd_clean(self, message, channel, server, author, search_range=50):
        """
        Usage:
            {command_prefix}clean [range]

        Removes up to [range] messages the bot has posted in chat. Default: 50, Max: 1000
        """

        try:
            search_range = min(int(search_range) + 1, 1000)
        except:
            return Response(
                "enter a number.  NUMBER.  That means digits.  `15`.  Etc.",
                reply=True)

        await self.safe_delete_message(message, quiet=True)

        def is_possible_command_invoke(entry):
            valid_call = any(
                entry.content.startswith(prefix)
                for prefix in [self.config.command_prefix])  # can be expanded
            return valid_call and not entry.content[1:2].isspace()

        delete_invokes = True
        delete_all = channel.permissions_for(
            author).manage_messages or self.config.owner_id == author.id

        def check(message):
            if is_possible_command_invoke(message) and delete_invokes:
                return delete_all or message.author == author
            return message.author == self.user

        if self.user.bot:
            if channel.permissions_for(server.me).manage_messages:
                deleted = await self.purge_from(
                    channel, check=check, limit=search_range, before=message)
                return Response(
                    "Cleaned up {} message{}.".format(
                        len(deleted), "s" * bool(deleted)))

        deleted = 0
        async for entry in self.logs_from(
                channel, search_range, before=message):
            if entry == self.server_specific_data[channel.server][
                    "last_np_msg"]:
                continue

            if entry.author == self.user:
                await self.safe_delete_message(entry)
                deleted += 1
                await asyncio.sleep(0.21)

            if is_possible_command_invoke(entry) and delete_invokes:
                if delete_all or entry.author == author:
                    try:
                        await self.delete_message(entry)
                        await asyncio.sleep(0.21)
                        deleted += 1

                    except discord.Forbidden:
                        delete_invokes = False
                    except discord.HTTPException:
                        pass

        return Response(
            "Cleaned up {} message{}.".format(deleted, "s" * bool(deleted)))

    async def cmd_say(self, channel, message, leftover_args):
        """
        Usage:
            {command_prefix}say <message>
        Make the bot say something
        """

        await self.safe_delete_message(message)
        await self.safe_send_message(channel, " ".join(leftover_args))
        print(message.author.name + " made me say: \"" +
              " ".join(leftover_args) + "\"")

    async def cmd_broadcast(self, server, message, leftover_args):
        """
        Usage:
            {command_prefix}broadcast message

        Broadcast a message to every user of the server
        """

        targetMembers = []
        msg = ""

        if len(message.mentions) > 0:
            print("Found mentions!")
            msg = " ".join(leftover_args[len(message.mentions):])
            for target in message.mentions:
                print("User " + str(target) + " added to recipients")
                targetMembers.append(target)

        for role in server.roles:
            if role.name == leftover_args[0] or role.id == leftover_args[0]:
                print("Found " + role.name +
                      " and will send the message to them")
                msg = " ".join(leftover_args[1:])

                for member in server.members:
                    for mRole in member.roles:
                        if member not in targetMembers and (
                                mRole.name == leftover_args[0] or
                                mRole.id == leftover_args[0]):
                            print("User " + str(member) +
                                  " added to recipients")
                            targetMembers.append(member)
                            break
                break

        if len(targetMembers) < 1:
            print(
                "Didn't find a recipient. Will send the message to everyone")
            targetMembers = server.members
            msg = " ".join(leftover_args)

        for m in targetMembers:
            if m.bot:
                continue

            print("Sent \"" + msg + "\" to " + str(m))
            await self.safe_send_message(m, msg)

    @owner_only
    @command_info("3.1.6", 1498672140, {
        "3.6.4": (1498146841, "Can now specify the required arguments in order to block a command"),
        "3.9.8": (1499976133, "Saving the blocked commands")
    })
    async def cmd_blockcommand(self, command, leftover_args):
        """
        ///|Usage
        `{command_prefix}blockcommand <command> [args] <"reason">`
        ///|Explanation
        Block a command
        """
        if command.lower() in self.blocked_commands:
            self.blocked_commands.pop(command.lower())
            Settings["blocked_commands"] = self.blocked_commands
            return Response("Block lifted")
        else:
            if len(leftover_args) < 1:
                return Response("Reason plz")

            args = []

            for i, el in enumerate(leftover_args):
                if not el.startswith("\""):
                    args.append(el)
                else:
                    reason = " ".join(leftover_args[i:]).strip("\"")
                    break

            if not reason:
                return Response("Put your reason in quotes, idiot!")

            self.blocked_commands[command.lower()] = (args, reason)
            Settings["blocked_commands"] = self.blocked_commands
            return Response("Blocked command `{} {}`".format(command, " ".join(args)))

    @command_info("2.0.2", 1484676180, {
        "3.8.3": (1499184914, "Can now use multiline statements without having to use tricks like /n/"),
        "3.8.5": (1499279145, "Better code display"),
        "3.9.6": (1499889309, "Escaping the result and adding the shortcut entry for player.current_entry"),
        "4.3.4": (1501246003, "Don't block user anymore. That's stupid"),
        "4.4.7": (1501683507, "Not showing empty result message"),
        "4.4.8": (1501684956, "including the console log"),
        "4.5.2": (1501965475, "only showing console log when it contains something")
    })
    async def cmd_execute(self, channel, author, server, raw_content, player=None):
        statement = raw_content.strip()
        beautiful_statement = "```python\n{}\n```".format(statement)

        statement = "async def func():\n{}".format(indent(statement, "\t"))
        await self.safe_send_message(channel, "**RUNNING CODE**\n{}".format(beautiful_statement))

        env = {}
        env.update(globals())
        env.update(locals())
        env.update(entry=player.current_entry)

        console = StringIO()

        try:
            exec(statement, env)
        except SyntaxError as e:
            return Response(
                "**While compiling the statement the following error occured**\n{}\n{}".
                format(traceback.format_exc(), str(e)))

        func = env["func"]

        try:
            with redirect_stdout(console):
                ret = await func()
        except Exception as e:
            return Response(
                "**While executing the statement the following error occured**\n{}\n{}".
                format(traceback.format_exc(), str(e)))

        res = escape_dis(str(ret))
        if ret is not None and res:
            result = "**RESULT**\n{}".format(res)
        else:
            result = ""

        log = console.getvalue().strip()

        if log:
            result += "\n**Console**\n```\n{}\n```".format(log)

        result = result.strip()
        if result:
            return Response(result)

    @owner_only
    async def cmd_shutdown(self, channel):
        await self.safe_send_message(channel, ":wave:")
        raise exceptions.TerminateSignal

    @command_info("1.0.0", 1477180800, {
        "4.3.7": (1501264004, "Fixed command")
    })
    async def cmd_disconnect(self, server):
        """
        Usage:
            {command_prefix}disconnect

        Make the bot leave his current voice channel.
        """
        if server.id in self.players:
            self.players.pop(server.id).kill()
        await server.voice_client.disconnect()
        return Response(":hear_no_evil:")

    async def cmd_restart(self, channel):
        await self.safe_send_message(channel, ":wave:")
        raise exceptions.RestartSignal
