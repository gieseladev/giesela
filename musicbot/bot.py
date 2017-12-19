import asyncio
import inspect
import logging
import os
import re
import shutil
import sys
import traceback
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from random import choice
from textwrap import indent, wrap

import aiohttp
import discord
from discord import Client
from discord.enums import ChannelType
from discord.utils import find

from musicbot import downloader, exceptions, localization
from musicbot.commands.admin_commands import AdminCommands
from musicbot.commands.fun_commands import FunCommands
from musicbot.commands.info_commands import InfoCommands
from musicbot.commands.misc_commands import MiscCommands
from musicbot.commands.player_commands import PlayerCommands
from musicbot.commands.playlist_commands import PlaylistCommands
from musicbot.commands.queue_commands import QueueCommands
from musicbot.commands.tool_commands import ToolCommands
from musicbot.config import Config, ConfigDefaults
from musicbot.constants import VERSION as BOTVERSION
from musicbot.constants import (ABS_AUDIO_CACHE_PATH, AUDIO_CACHE_PATH,
                                DISCORD_MSG_CHAR_LIMIT)
from musicbot.entry import RadioSongEntry, TimestampEntry, YoutubeEntry
from musicbot.games.game_cah import GameCAH
from musicbot.lib.ui import ui_utils
from musicbot.opus_loader import load_opus_lib
from musicbot.player import MusicPlayer
from musicbot.random_sets import RandomSets
from musicbot.reporting import raven_client
from musicbot.saved_playlists import Playlists
from musicbot.settings import Settings
from musicbot.utils import (Response, get_related_videos, load_file, ordinal,
                            paginate)
from musicbot.web_author import WebAuthor
from musicbot.web_socket_server import GieselaServer

load_opus_lib()

log = logging.getLogger("Giesela")

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.WARNING)
stream_handler.setFormatter(logging.Formatter("{time} - <name> [{levelname}] {message}", style="{"))

file_handler = logging.FileHandler("logs.txt")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("{asctime} - <{name}> [{levelname}] {message}", style="{"))

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[stream_handler, file_handler]
)


class MusicBot(Client, AdminCommands, FunCommands, InfoCommands,  MiscCommands, PlayerCommands, PlaylistCommands, QueueCommands, ToolCommands):

    def __init__(self):
        WebAuthor.bot = self

        self.players = {}
        self.locks = defaultdict(asyncio.Lock)
        self.voice_client_connect_lock = asyncio.Lock()

        self.config = Config(ConfigDefaults.options_file)
        self.playlists = Playlists(ConfigDefaults.playlists_file)
        self.random_sets = RandomSets(ConfigDefaults.random_sets)
        self.online_loggers = {}
        self.cah = GameCAH(self)

        self.blacklist = set(load_file(self.config.blacklist_file))
        self.autoplaylist = load_file(self.config.auto_playlist_file)
        self.downloader = downloader.Downloader(download_folder=AUDIO_CACHE_PATH)

        self.exit_signal = None
        self.init_ok = False
        self.cached_client_id = None
        self.chatters = {}
        self.blocked_commands = Settings.get_setting("blocked_commands", default={})
        self.users_in_menu = set()

        if not self.autoplaylist:
            print("Warning: Autoplaylist is empty, disabling.")
            self.config.auto_playlist = False

        self.use_autoplaylist = self.config.auto_playlist

        ssd_defaults = {"last_np_msg": None, "auto_paused": False}
        self.server_specific_data = defaultdict(lambda: dict(ssd_defaults))

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += " Giesela/%s" % BOTVERSION

        self.load_online_loggers()

    def find_home_channel(self, server, most_members=True):
        channels_by_member = sorted([channel for channel in server.channels if len(channel.voice_members) > 0], key=lambda channel: len(channel.voice_members), reverse=True)

        if most_members and channels_by_member:
            channel = channels_by_member[0]
        else:
            channel = find(
                lambda c: c.type == ChannelType.voice and any(x in c.name.lower().split()
                                                              for x in ["giesela", "musicbot", "bot", "music", "reign"]),
                server.channels
            )
        if channel is None:
            channel = choice(
                list(filter(lambda c: c.type == ChannelType.voice, server.channels)))

        return channel

    def _delete_old_audiocache(self, path=ABS_AUDIO_CACHE_PATH):
        try:
            shutil.rmtree(path)
            return True
        except:
            try:
                os.rename(path, path + "__")
            except:
                return False
            try:
                shutil.rmtree(path)
            except:
                os.rename(path + "__", path)
                return False

        return True

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def generate_invite_link(self, *, permissions=None, server=None):
        if not self.cached_client_id:
            appinfo = await self.application_info()
            self.cached_client_id = appinfo.id

        return discord.utils.oauth_url(
            self.cached_client_id, permissions=permissions, server=server)

    def get_global_user(self, user_id):
        for server in self.servers:
            mem = server.get_member(user_id)
            if mem:
                return mem

        return None

    async def get_player(self, server, channel=None):
        if isinstance(server, str):
            server = self.get_server(server)

        with (await self.voice_client_connect_lock):
            # if there's already a player for this server
            if server.id in self.players:
                # but it's not in the right channel
                if channel and self.players[server.id].voice_client.channel != channel:
                    # move that stuff
                    await self.players[server.id].voice_client.move_to(channel)
            else:
                voice_client = None

                # gotta be sure to get one
                while not voice_client:
                    # create a new voice client in the selected channel (if given) or go to the home channel
                    with suppress(discord.errors.ConnectionClosed):
                        voice_client = await self.join_voice_channel(channel or self.find_home_channel(server))

                player = MusicPlayer(self, voice_client) \
                    .on("play", self.on_player_play) \
                    .on("resume", self.on_player_resume) \
                    .on("pause", self.on_player_pause) \
                    .on("stop", self.on_player_stop) \
                    .on("finished-playing", self.on_player_finished_playing) \
                    .on("entry-added", self.on_player_entry_added)

                print("[PLAYER] Created a new player")

                self.players[server.id] = player

        return self.players[server.id]

    async def on_player_play(self, player, entry):
        GieselaServer.send_player_information(
            player.voice_client.server.id)
        await self.update_now_playing(entry)

        channel = entry.meta.get("channel", None)

        if channel:
            last_np_msg = self.server_specific_data[channel.server][
                "last_np_msg"]
            if last_np_msg and last_np_msg.channel == channel:

                # if the last np message isn't the last message in the channel;
                # delete it
                async for lmsg in self.logs_from(channel, limit=1):
                    if lmsg != last_np_msg and last_np_msg:
                        await self.safe_delete_message(last_np_msg)
                        self.server_specific_data[channel.server][
                            "last_np_msg"] = None
                    break  # This is probably redundant

            if isinstance(entry, TimestampEntry):
                sub_entry = entry.current_sub_entry
                sub_title = sub_entry["name"]
                sub_index = sub_entry["index"] + 1
                newmsg = localization.format(player.voice_client.server, "player.now_playing.timestamp_entry",
                                             sub_entry=sub_title,
                                             index=sub_index,
                                             ordinal=ordinal(sub_index),
                                             title=entry.whole_title
                                             )
            elif isinstance(entry, RadioSongEntry):
                newmsg = localization.format(player.voice_client.server, "player.now_playing.generic", title="{} - {}".format(entry.artist, entry.title))
            else:
                newmsg = localization.format(player.voice_client.server, "player.now_playing.generic", title=entry.title)

            if self.server_specific_data[channel.server]["last_np_msg"]:
                self.server_specific_data[channel.server][
                    "last_np_msg"] = await self.safe_edit_message(
                        last_np_msg, newmsg, send_if_fail=True)
            else:
                self.server_specific_data[channel.server][
                    "last_np_msg"] = await self.safe_send_message(
                        channel, newmsg)

    async def on_player_resume(self, player, entry, **_):
        await self.update_now_playing(entry)
        GieselaServer.send_small_update(
            player.voice_client.server.id, state=player.state.value, state_name=str(player.state), progress=player.progress)

    async def on_player_pause(self, player, entry, **_):
        await self.update_now_playing(entry, True)
        GieselaServer.send_small_update(
            player.voice_client.server.id, state=player.state.value, state_name=str(player.state), progress=player.progress)

    async def on_player_stop(self, player, **_):
        await self.update_now_playing()
        # GieselaServer.send_player_information(
        #     player.voice_client.server.id)

    async def on_player_finished_playing(self, player, **_):
        if not player.queue.entries and not player.current_entry:
            GieselaServer.send_player_information(
                player.voice_client.server.id)

        if not player.queue.entries and not player.current_entry and self.use_autoplaylist:
            while True:
                if player.queue.history and isinstance(player.queue.history[0], YoutubeEntry):
                    print("[Autoplay] following suggested for last history entry")
                    song_url = choice(get_related_videos(player.queue.history[0].video_id))["url"]
                elif self.autoplaylist:
                    print("[Autoplay] choosing an url from the autoplaylist")
                    song_url = choice(self.autoplaylist)
                else:
                    print("[Autoplay] Can't continue")
                    break

                try:
                    await player.queue.add_entry(song_url)
                except exceptions.ExtractionError as e:
                    print("Error adding song from autoplaylist:", e)
                    continue

                break

    async def on_player_entry_added(self, queue, entry, **_):
        pass

    async def update_now_playing(self, entry=None, is_paused=False):
        game = None

        if self.user.bot:
            activeplayers = sum(1 for p in self.players.values()
                                if p.is_playing)
            if activeplayers > 1:
                game = discord.Game(type=0, name="Music")
                entry = None

            elif activeplayers == 1:
                player = discord.utils.get(self.players.values(), is_playing=True)
                entry = player.current_entry

            elif activeplayers == 0:
                game = discord.Game(type=0, name=self.config.idle_game)
                entry = None

        if entry:
            prefix = "\u275A\u275A" if is_paused else ""

            name = entry.title

            name = u"{} {}".format(prefix, name)[:128]
            game = discord.Game(type=0, name=name)

        await self.change_presence(game=game)

    async def safe_send_message(self, dest, content=None, *, max_letters=DISCORD_MSG_CHAR_LIMIT, split_message=True, tts=False, expire_in=0, also_delete=None, quiet=False, embed=None):
        msg = None
        try:
            if split_message and content and len(content) > max_letters:
                print("Message too long, splitting it up")
                msgs = paginate(content, length=DISCORD_MSG_CHAR_LIMIT)

                for msg in msgs:
                    nmsg = await self.send_message(dest, msg, tts=tts)

                    if nmsg and expire_in:
                        asyncio.ensure_future(self._wait_delete_msg(nmsg, expire_in))

                    if also_delete and isinstance(also_delete, discord.Message):
                        asyncio.ensure_future(self._wait_delete_msg(also_delete, expire_in))
            else:
                msg = await self.send_message(dest, content, tts=tts, embed=embed)

                if msg and expire_in:
                    asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

                if also_delete and isinstance(also_delete, discord.Message):
                    asyncio.ensure_future(self._wait_delete_msg(also_delete, expire_in))

        except discord.Forbidden:
            if not quiet:
                print("Warning: Cannot send message to %s, no permission" %
                      dest.name)

        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot send message to %s, invalid channel?"
                      % dest.name)

        return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await self.delete_message(message)

        except discord.Forbidden:
            if not quiet:
                print("Warning: Cannot delete message \"%s\", no permission"
                      % message.clean_content)

        except discord.NotFound:
            if not quiet:
                print(
                    "Warning: Cannot delete message \"%s\", message not found"
                    % message.clean_content)
        except:
            if not quiet:
                raise

    async def safe_edit_message(self, message, new=None, *, send_if_fail=False, quiet=False, keep_at_bottom=False, embed=None):
        if keep_at_bottom:
            async for lmsg in self.logs_from(message.channel, limit=5):
                if lmsg.id == message.id:
                    break
            else:
                await self.safe_delete_message(message)
                return await self.safe_send_message(message.channel, new, embed=embed)

        try:
            return await self.edit_message(message, new, embed=embed)

        except discord.NotFound:
            if not quiet:
                print(
                    "Warning: Cannot edit message \"%s\", message not found" %
                    message.clean_content)
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                return await self.safe_send_message(message.channel, new, embed=embed)

    async def edit_profile(self, **fields):
        if self.user.bot:
            return await super().edit_profile(**fields)
        else:
            return await super().edit_profile(self.config._password, **fields)

    def _cleanup(self):
        try:
            self.loop.run_until_complete(self.logout())
        except:  # Can be ignored
            pass

        pending = asyncio.Task.all_tasks()
        gathered = asyncio.gather(*pending)

        try:
            gathered.cancel()
            self.loop.run_until_complete(gathered)
            gathered.exception()
        except:  # Can be ignored
            pass

    def run(self):
        try:
            self.loop.run_until_complete(self.start(*self.config.auth))

        except discord.errors.LoginFailure:
            # Add if token, else
            raise exceptions.HelpfulError(
                "Bot cannot login, bad credentials.",
                "Fix your Email or Password or Token in the options file.  "
                "Remember that each field should be on their own line.")

        finally:
            try:
                self._cleanup()
            except Exception as e:
                print("Error in cleanup:", e)

            self.loop.close()
            if self.exit_signal:
                raise self.exit_signal

    async def on_error(self, event, *args, **kwargs):
        ex_type, ex, stack = sys.exc_info()

        if ex_type == exceptions.HelpfulError:
            print("Exception in " + str(event))
            print(ex.message)

            await asyncio.sleep(2)  # don't ask
            await self.logout()

        elif issubclass(ex_type, exceptions.Signal):
            self.exit_signal = ex_type
            await self.logout()

        else:
            traceback.print_exc()

    async def on_ready(self):
        print("\rConnected!  Giesela v%s\n" % BOTVERSION)

        if self.config.owner_id == self.user.id:
            raise exceptions.HelpfulError(
                "Your OwnerID is incorrect or you've used the wrong credentials.",
                "The bot needs its own account to function.  "
                "The OwnerID is the id of the owner, not the bot.  "
                "Figure out which one is which and use the correct information."
            )

        self.init_ok = True

        print("Bot:   %s/%s#%s" % (self.user.id, self.user.name,
                                   self.user.discriminator))

        if not self.servers:
            print("Giesela is not on any servers.")
            if self.user.bot:
                print(
                    "\nTo make Giesela join a server, paste this link in your browser."
                )
                print("    " + await self.generate_invite_link())

        config_string = "\nConfig:\n"

        all_options = self.config.get_all_options()
        for option in all_options:
            opt, val = option

            opt_string = "  {}: ".format(opt)

            lines = wrap(str(val), 100 - len(opt_string))
            if len(lines) > 1:
                val_string = "{}\n{}\n".format(
                    lines[0],
                    indent("\n".join(lines[1:]), len(opt_string) * " ")
                )
            else:
                val_string = lines[0]

            config_string += opt_string + val_string + "\n"

        print(config_string)

        if not self.config.save_videos and os.path.isdir(ABS_AUDIO_CACHE_PATH):
            if self._delete_old_audiocache():
                print("Deleting old audio cache")
            else:
                print("Could not delete old audio cache, moving on.")

        print("Ready to go!")

        if self.config.open_websocket:
            GieselaServer.run(self)

    async def on_message(self, message):
        await self.wait_until_ready()

        message_content = message.content.strip()

        nine_gag_match = re.match(
            r".+?[http|https]:\/\/(?:m\.)?9gag.com\/gag\/(\w+)(?:\?.+)",
            message_content)
        if nine_gag_match:
            post_id = nine_gag_match.group(1)
            await self.cmd_9gag(message.channel, message.author, post_id)
            await self.safe_delete_message(message)
            return

        if message.author.id in self.users_in_menu:
            print("{} is currently in a menu. Ignoring \"{}\"".format(
                message.author, message_content))
            return

        if not message_content.startswith(self.config.command_prefix) and message.channel.id not in self.config.owned_channels:
            return

        # don't react to own messages or messages from bots
        if message.author == self.user or message.author.bot:
            return

        raw_command, *args = message_content.split()
        command = raw_command.lstrip(
            self.config.command_prefix).lower().strip()

        handler = getattr(self, "cmd_%s" % command, None)
        if not handler:
            if self.config.delete_unrelated_in_owned and message.channel.id in self.config.owned_channels:
                await self.safe_delete_message(message)
                print("Removed message because it's unrelated")

            return

        if command in self.blocked_commands:
            required_args, reason = self.blocked_commands[command]
            if all(arg in args for arg in required_args):
                await self.send_message(message.channel, reason)
                return

        if message.channel.is_private:
            if not (message.author.id == self.config.owner_id and command ==
                    "joinserver") and not command in self.config.private_chat_commands:
                await self.send_message(
                    message.channel,
                    localization.get(message.author, "errors.private_chat")
                )
                return

        if message.author.id in self.blacklist and message.author.id != self.config.owner_id:
            print("[User blacklisted] {0.id}/{0.name} ({1})".format(
                message.author, message_content))
            return

        else:
            print("[Command] {0.id}/{0.name} ({1})".format(
                message.author, message_content))

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()
        # because I'm using len(), I already take care of the extra whitespace
        raw_content = message_content[len(raw_command):]

        try:
            handler_kwargs = {}
            if params.pop("message", None):
                handler_kwargs["message"] = message

            if params.pop("raw_content", None):
                handler_kwargs["raw_content"] = raw_content

            if params.pop("channel", None):
                handler_kwargs["channel"] = message.channel

            if params.pop("author", None):
                handler_kwargs["author"] = message.author

            if params.pop("server", None):
                handler_kwargs["server"] = message.server

            if params.pop("player", None):
                handler_kwargs["player"] = await self.get_player(message.server)

            if params.pop("user_mentions", None):
                handler_kwargs["user_mentions"] = list(
                    map(message.server.get_member, message.raw_mentions))

            if params.pop("channel_mentions", None):
                handler_kwargs["channel_mentions"] = list(
                    map(message.server.get_channel,
                        message.raw_channel_mentions))

            if params.pop("voice_channel", None):
                handler_kwargs[
                    "voice_channel"] = message.server.me.voice_channel

            if params.pop("leftover_args", None):
                handler_kwargs["leftover_args"] = args

            args_expected = []
            for key, param in list(params.items()):
                doc_key = "[%s=%s]" % (
                    key, param.default
                ) if param.default is not inspect.Parameter.empty else key
                args_expected.append(doc_key)

                if not args and param.default is not inspect.Parameter.empty:
                    params.pop(key)
                    continue

                if args:
                    arg_value = args.pop(0)
                    handler_kwargs[key] = arg_value
                    params.pop(key)

            if params:
                return await self.cmd_help(message.channel, [command])

            try:
                response = await handler(**handler_kwargs)
            except exceptions.ShowHelp:
                return await self.cmd_help(message.channel, [command])

            if response and isinstance(response, Response):
                content = response.content
                if content and response.reply:
                    content = "%s, %s" % (message.author.mention, content)

                sentmsg = await self.safe_send_message(
                    message.channel,
                    content,
                    expire_in=response.delete_after
                    if self.config.delete_messages else 0,
                    also_delete=message
                    if self.config.delete_invoking else None,
                    embed=response.embed
                )

        except (exceptions.CommandError, exceptions.HelpfulError, exceptions.ExtractionError) as e:
            print("{0.__class__}: {0.message}".format(e))

            expirein = e.expire_in if self.config.delete_messages else None
            alsodelete = message if self.config.delete_invoking else None

            await self.safe_send_message(
                message.channel,
                "```\n%s\n```" % e.message,
                expire_in=expirein,
                also_delete=alsodelete)

        except exceptions.Signal:
            raise

        except Exception:
            raven_client.captureException()

            traceback.print_exc()
            if self.config.debug_mode:
                await self.safe_send_message(
                    message.channel, "```\n%s\n```" % traceback.format_exc())

    async def on_reaction_add(self, reaction, user):
        await ui_utils.handle_reaction(reaction, user)

    async def on_reaction_remove(self, reaction, user):
        await ui_utils.handle_reaction(reaction, user)

    async def on_server_update(self, before: discord.Server, after: discord.Server):
        if before.region != after.region:
            print("[Servers] \"%s\" changed regions: %s -> %s" %
                  (after.name, before.region, after.region))

    async def on_server_join(self, server):
        for channel in server.channels:
            if channel.type is not ChannelType.text:
                continue

            msg = await self.safe_send_message(
                channel,
                "Hello there,\nMy name is {}!\n\n*Type {}help to find out more.*".
                format(self.user.mention, self.config.command_prefix))
            if msg is not None:
                return

    async def on_member_update(self, before, after):
        await self.on_any_update(before, after)
        if before.server.id in self.online_loggers:
            self.online_loggers[before.server.id].update_stats(
                after.id, after.status == discord.Status.online, after.game)

    async def on_voice_state_update(self, before, after):
        await self.on_any_update(before, after)

        if not self.config.auto_pause:
            return

        user_left_voice_channel = False

        if before.voice.voice_channel and not after.voice.voice_channel:
            user_left_voice_channel = True

        if after.server.me != after and after.bot:
            return

        if before.voice.voice_channel != after.voice.voice_channel:
            my_channel = after.server.me.voice.voice_channel
            if not my_channel:
                return

            # I was alone but a non-bot joined
            if sum(1 for vm in my_channel.voice_members if not vm.bot) == 1 and not user_left_voice_channel:
                player = await self.get_player(after.server)
                if player.is_paused:
                    print("[AUTOPAUSE] Resuming")
                    player.resume()

            # I am now alone
            if sum(1 for vm in my_channel.voice_members if not vm.bot) == 0:
                player = await self.get_player(after.server)
                if player.is_playing:
                    print("[AUTOPAUSE] Pausing")
                    player.pause()

    async def on_any_update(self, before, after):
        if before.server.id in self.online_loggers:
            timestamp = "{0.hour:0>2}:{0.minute:0>2}".format(datetime.now())
            notification = None
            mem_name = "\"{}\"".format(after.display_name) if len(
                after.display_name.split()) > 1 else after.display_name
            if before.status != after.status:
                notification = "`{}` {} {}".format(timestamp, mem_name, {
                    discord.Status.online:
                    "came **online**",
                    discord.Status.offline:
                    "went **offline**",
                    discord.Status.idle:
                    "went **away**",
                    discord.Status.dnd:
                    "doesn't want to be disturbed"
                }[after.status])
            if before.game != after.game:
                text = ""
                if after.game is None:
                    text = "stopped playing **{}**".format(before.game.name)
                else:
                    text = "started playing **{}**".format(after.game.name)
                if notification is None:
                    notification = "`{}` {} {}".format(timestamp, mem_name,
                                                       text)
                else:
                    notification += "\nand {}".format(text)

            if before.voice.voice_channel != after.voice.voice_channel:
                text = ""
                if after.voice.voice_channel is None:
                    text = "quit **{}** (voice channel)".format(
                        before.voice.voice_channel.name)
                else:
                    text = "joined **{}** (voice channel)".format(
                        after.voice.voice_channel.name)
                if notification is None:
                    notification = "`{}` {} {}".format(timestamp, mem_name,
                                                       text)
                else:
                    notification += "\nand {}".format(text)

            if notification is not None:
                for listener in self.online_loggers[
                        before.server.id].listeners:
                    if before.id == listener:
                        continue

                    mem = self.get_global_user(listener)
                    await self.safe_send_message(mem, notification)


if __name__ == "__main__":
    bot = MusicBot()
    bot.run()
