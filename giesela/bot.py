import asyncio
import inspect
import logging
import os
import shutil
import sys
import traceback
from collections import defaultdict
from contextlib import suppress
from random import choice
from textwrap import indent, wrap

import aiohttp
import discord
from discord import Client
from discord.enums import ChannelType
from discord.utils import find

from giesela import downloader, exceptions, localization
from giesela.commands.admin_commands import AdminCommands
from giesela.commands.info_commands import InfoCommands
from giesela.commands.misc_commands import MiscCommands
from giesela.commands.player_commands import PlayerCommands
from giesela.commands.playlist_commands import PlaylistCommands
from giesela.commands.queue_commands import QueueCommands
from giesela.commands.tool_commands import ToolCommands
from giesela.config import Config, ConfigDefaults
from giesela.constants import ABS_AUDIO_CACHE_PATH, AUDIO_CACHE_PATH, DISCORD_MSG_CHAR_LIMIT, VERSION as BOTVERSION
from giesela.entry import RadioSongEntry, TimestampEntry
from giesela.lib.ui import ui_utils
from giesela.opus_loader import load_opus_lib
from giesela.player import MusicPlayer
from giesela.reporting import raven_client
from giesela.saved_playlists import Playlists
from giesela.settings import Settings
from giesela.utils import (Response, ordinal,
                           paginate)
from giesela.web_author import WebAuthor
from giesela.webiesela import WebieselaServer

load_opus_lib()

log = logging.getLogger(__name__)


def _delete_old_audiocache(path=ABS_AUDIO_CACHE_PATH):
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


def find_home_channel(server, most_members=True):
    channels_by_member = sorted([channel for channel in server.channels if len(channel.voice_members) > 0],
                                key=lambda channel: len(channel.voice_members), reverse=True)

    if most_members and channels_by_member:
        channel = channels_by_member[0]
    else:
        channel = find(lambda c: c.type == ChannelType.voice and any(x in c.name.lower().split()
                                                                     for x in ["giesela", "giesela", "bot", "music", "reign"]),
                       server.channels
                       )
    if channel is None:
        channel = choice(list(filter(lambda c: c.type == ChannelType.voice, server.channels)))

    return channel


class Giesela(Client, AdminCommands, InfoCommands, MiscCommands, PlayerCommands, PlaylistCommands, QueueCommands, ToolCommands):

    def __init__(self):
        WebAuthor.bot = self

        self.players = {}
        self.locks = defaultdict(asyncio.Lock)
        self.voice_client_connect_lock = asyncio.Lock()

        self.config = Config(ConfigDefaults.options_file)
        self.playlists = Playlists(ConfigDefaults.playlists_file)

        self.downloader = downloader.Downloader(download_folder=AUDIO_CACHE_PATH)

        self.exit_signal = None
        self.init_ok = False
        self.cached_client_id = None
        self.chatters = {}
        self.blocked_commands = Settings.get_setting("blocked_commands", default={})
        self.users_in_menu = set()

        ssd_defaults = {"last_np_msg": None, "auto_paused": False}
        self.guild_specific_data = defaultdict(lambda: dict(ssd_defaults))

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += " Giesela/" + BOTVERSION

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    def get_global_user(self, user_id):
        for server in self.guilds:
            mem = server.get_member(user_id)
            if mem:
                return mem

        return None

    async def get_player(self, server, channel=None):
        if isinstance(server, int):
            server = self.get_guild(server)

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
                        channel = self.get_channel(channel or find_home_channel(server))
                        voice_client = channel.connect()

                player = MusicPlayer(self, voice_client) \
                    .on("play", self.on_player_play) \
                    .on("resume", self.on_player_resume) \
                    .on("pause", self.on_player_pause) \
                    .on("stop", self.on_player_stop) \
                    .on("finished-playing", self.on_player_finished_playing) \
                    .on("entry-added", self.on_player_entry_added)

                log.info("[PLAYER] Created a new player")

                self.players[server.id] = player

        return self.players[server.id]

    async def on_player_play(self, player, entry):
        WebieselaServer.send_player_information(player.voice_client.guild.id)
        await self.update_now_playing(entry)

        channel = entry.meta.get("channel", None)

        if channel:
            last_np_msg = self.guild_specific_data[channel.guild][
                "last_np_msg"]
            if last_np_msg and last_np_msg.channel == channel:

                # if the last np message isn't the last message in the channel;
                # delete it
                async for lmsg in channel.history(limit=1):
                    if lmsg != last_np_msg and last_np_msg:
                        await self.safe_delete_message(last_np_msg)
                        self.guild_specific_data[channel.guild][
                            "last_np_msg"] = None
                    break  # This is probably redundant

            if isinstance(entry, TimestampEntry):
                sub_entry = entry.current_sub_entry
                sub_title = sub_entry["name"]
                sub_index = sub_entry["index"] + 1
                newmsg = localization.format(player.voice_client.guild, "player.now_playing.timestamp_entry",
                                             sub_entry=sub_title,
                                             index=sub_index,
                                             ordinal=ordinal(sub_index),
                                             title=entry.whole_title
                                             )
            elif isinstance(entry, RadioSongEntry):
                newmsg = localization.format(player.voice_client.guild, "player.now_playing.generic",
                                             title="{} - {}".format(entry.artist, entry.title))
            else:
                newmsg = localization.format(player.voice_client.guild, "player.now_playing.generic", title=entry.title)

            if self.guild_specific_data[channel.guild]["last_np_msg"]:
                self.guild_specific_data[channel.guild][
                    "last_np_msg"] = await self.safe_edit_message(last_np_msg, newmsg, send_if_fail=True)
            else:
                self.guild_specific_data[channel.guild][
                    "last_np_msg"] = await self.safe_send_message(channel, newmsg)

    async def on_player_resume(self, player, entry, **_):
        await self.update_now_playing(entry)
        WebieselaServer.send_small_update(player.voice_client.guild.id, state=player.state.value, state_name=str(player.state),
                                          progress=player.progress)

    async def on_player_pause(self, player, entry, **_):
        await self.update_now_playing(entry, True)
        WebieselaServer.send_small_update(player.voice_client.guild.id, state=player.state.value, state_name=str(player.state),
                                          progress=player.progress)

    async def on_player_stop(self, **_):
        await self.update_now_playing()
        # GieselaServer.send_player_information(#     player.voice_client.guild.id)

    async def on_player_finished_playing(self, player, **_):
        if not player.queue.entries and not player.current_entry:
            WebieselaServer.send_player_information(player.voice_client.guild.id)

    async def on_player_entry_added(self, queue, entry, **_):
        pass

    async def send_typing(self, channel: discord.TextChannel):
        await channel.trigger_typing()

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

        await self.change_presence(activity=game)

    async def safe_send_message(self, dest, content=None, *, max_letters=DISCORD_MSG_CHAR_LIMIT, split_message=True, tts=False, expire_in=0,
                                also_delete=None, quiet=False, embed=None):
        msg = None
        try:
            if split_message and content and len(content) > max_letters:
                log.info("Message too long, splitting it up")
                msgs = paginate(content, length=DISCORD_MSG_CHAR_LIMIT)

                for msg in msgs:
                    nmsg = await dest.send(msg, tts=tts)

                    if nmsg and expire_in:
                        asyncio.ensure_future(self._wait_delete_msg(nmsg, expire_in))

                    if also_delete and isinstance(also_delete, discord.Message):
                        asyncio.ensure_future(self._wait_delete_msg(also_delete, expire_in))
            else:
                msg = await dest.send(content, tts=tts, embed=embed)

                if msg and expire_in:
                    asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

                if also_delete and isinstance(also_delete, discord.Message):
                    asyncio.ensure_future(self._wait_delete_msg(also_delete, expire_in))

        except discord.Forbidden:
            if not quiet:
                log.info("Warning: Cannot send message to %s, no permission" %
                         dest.name)

        except discord.NotFound:
            if not quiet:
                log.info("Warning: Cannot send message to %s, invalid channel?"
                         % dest.name)

        return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await message.delete()

        except discord.Forbidden:
            if not quiet:
                log.info("Warning: Cannot delete message \"%s\", no permission"
                         % message.clean_content)

        except discord.NotFound:
            if not quiet:
                log.info("Warning: Cannot delete message \"%s\", message not found"
                         % message.clean_content)
        except:
            if not quiet:
                raise

    async def safe_edit_message(self, message, new=None, *, send_if_fail=False, quiet=False, keep_at_bottom=False, embed=None):
        if keep_at_bottom:
            async for lmsg in message.channel.history(limit=5):
                if lmsg.id == message.id:
                    break
            else:
                await self.safe_delete_message(message)
                return await self.safe_send_message(message.channel, new, embed=embed)

        try:
            return await message.edit(content=new, embed=embed)

        except discord.NotFound:
            if not quiet:
                log.info("Warning: Cannot edit message \"%s\", message not found" %
                         message.clean_content)
            if send_if_fail:
                if not quiet:
                    log.info("Sending instead")
                return await self.safe_send_message(message.channel, new, embed=embed)

    async def edit_profile(self, **fields):
        return await super().user.edit(**fields)

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
            super().run(self.config._token)
        finally:
            try:
                self._cleanup()
            except Exception as e:
                log.info("Error in cleanup:", e)

            self.loop.close()
            if self.exit_signal:
                raise self.exit_signal

    async def on_error(self, event, *args, **kwargs):
        ex_type, ex, stack = sys.exc_info()

        if ex_type == exceptions.HelpfulError:
            log.info("Exception in " + str(event))
            log.info(ex.message)

            await asyncio.sleep(2)  # don't ask
            await self.logout()

        elif issubclass(ex_type, exceptions.Signal):
            self.exit_signal = ex_type
            await self.logout()

        else:
            await super().on_error(event, *args, **kwargs)

    async def on_ready(self):
        log.info("\rConnected!  Giesela v%s\n" % BOTVERSION)

        if self.config.owner_id == self.user.id:
            raise exceptions.HelpfulError("Your OwnerID is incorrect or you've used the wrong credentials.",
                                          "The bot needs its own account to function.  "
                                          "The OwnerID is the id of the owner, not the bot.  "
                                          "Figure out which one is which and use the correct information."
                                          )

        self.init_ok = True

        log.info("Bot:   %s/%s#%s" % (self.user.id, self.user.name,
                                      self.user.discriminator))

        if not self.guilds:
            log.info("Giesela is not on any servers.")

        config_string = "\nConfig:\n"

        all_options = self.config.get_all_options()
        for option in all_options:
            opt, val = option

            opt_string = "  {}: ".format(opt)

            lines = wrap(str(val), 100 - len(opt_string))
            if len(lines) > 1:
                val_string = "{}\n{}\n".format(lines[0],
                                               indent("\n".join(lines[1:]), len(opt_string) * " ")
                                               )
            else:
                val_string = lines[0]

            config_string += opt_string + val_string + "\n"

        log.info(config_string)

        if not self.config.save_videos and os.path.isdir(ABS_AUDIO_CACHE_PATH):
            if _delete_old_audiocache():
                log.info("Deleting old audio cache")
            else:
                log.info("Could not delete old audio cache, moving on.")

        log.info("Ready to go!")

        if self.config.open_websocket:
            WebieselaServer.run(self)

    async def on_server_update(self, before: discord.Guild, after: discord.Guild):
        if before.region != after.region:
            log.info("[Servers] \"%s\" changed regions: %s -> %s" %
                     (after.name, before.region, after.region))

    async def on_reaction_remove(self, reaction, user):
        await ui_utils.handle_reaction(reaction, user)

    async def on_reaction_add(self, reaction, user):
        await ui_utils.handle_reaction(reaction, user)

    async def on_message(self, message):
        log.debug("message", message)
        await self.wait_until_ready()

        message_content = message.content.strip()

        if message.author.id in self.users_in_menu:
            log.info("{} is currently in a menu. Ignoring \"{}\"".format(message.author, message_content))
            return

        if not message_content.startswith(self.config.command_prefix) and message.channel.id not in self.config.owned_channels:
            return

        # don't react to own messages or messages from bots
        if message.author == self.user or message.author.bot:
            return

        raw_command, *args = message_content.split()
        command = raw_command.lstrip(self.config.command_prefix).lower().strip()

        handler = getattr(self, "cmd_%s" % command, None)
        if not handler:
            if self.config.delete_unrelated_in_owned and message.channel.id in self.config.owned_channels:
                await self.safe_delete_message(message)
                log.info("Removed message because it's unrelated")

            return

        if command in self.blocked_commands:
            required_args, reason = self.blocked_commands[command]
            if all(arg in args for arg in required_args):
                await self.safe_send_message(message.channel, reason)
                return

        if isinstance(message.channel, discord.DMChannel):
            if not (message.author.id == self.config.owner_id and command ==
                    "joinserver") and command not in self.config.private_chat_commands:
                await self.safe_send_message(message.channel,
                                             localization.get(message.author, "errors.private_chat")
                                             )
                return
        log.info("[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))

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
                handler_kwargs["server"] = message.guild

            if params.pop("player", None):
                handler_kwargs["player"] = await self.get_player(message.guild)

            if params.pop("user_mentions", None):
                handler_kwargs["user_mentions"] = list(map(message.guild.get_member, message.raw_mentions))

            if params.pop("channel_mentions", None):
                handler_kwargs["channel_mentions"] = list(map(message.guild.get_channel,
                                                              message.raw_channel_mentions))

            if params.pop("voice_channel", None):
                handler_kwargs[
                    "voice_channel"] = message.guild.me.voice_channel

            if params.pop("leftover_args", None):
                handler_kwargs["leftover_args"] = args

            args_expected = []
            for key, param in list(params.items()):
                doc_key = "[%s=%s]" % (key, param.default
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

                await self.safe_send_message(message.channel,
                                             content,
                                             expire_in=response.delete_after
                                             if self.config.delete_messages else 0,
                                             also_delete=message
                                             if self.config.delete_invoking else None,
                                             embed=response.embed
                                             )

        except (exceptions.CommandError, exceptions.HelpfulError, exceptions.ExtractionError) as e:
            log.info("{0.__class__}: {0.message}".format(e))

            expirein = e.expire_in if self.config.delete_messages else None
            alsodelete = message if self.config.delete_invoking else None

            await self.safe_send_message(message.channel,
                                         "```\n%s\n```" % e.message,
                                         expire_in=expirein,
                                         also_delete=alsodelete)

        except exceptions.Signal:
            raise

        except Exception:
            raven_client.captureException()

            traceback.print_exc()
            if self.config.debug_mode:
                await self.safe_send_message(message.channel, "```\n%s\n```" % traceback.format_exc())

    async def on_server_join(self, server):
        for channel in server.channels:
            if channel.type is not ChannelType.text:
                continue

            msg = await self.safe_send_message(channel,
                                               "Hello there,\nMy name is {}!\n\n*Type {}help to find out more.*".format(self.user.mention,
                                                                                                                        self.config.command_prefix))
            if msg is not None:
                return

    async def on_voice_state_update(self, before, after):
        if not self.config.auto_pause:
            return

        user_left_voice_channel = False

        if before.voice.voice_channel and not after.voice.voice_channel:
            user_left_voice_channel = True

        if after.guild.me != after and after.bot:
            return

        if before.voice.voice_channel != after.voice.voice_channel:
            my_channel = after.guild.me.voice.voice_channel
            if not my_channel:
                return

            # I was alone but a non-bot joined
            if sum(1 for vm in my_channel.voice_members if not vm.bot) == 1 and not user_left_voice_channel:
                player = await self.get_player(after.guild)
                if player.is_paused:
                    log.info("[AUTOPAUSE] Resuming")
                    player.resume()

            # I am now alone
            if sum(1 for vm in my_channel.voice_members if not vm.bot) == 0:
                player = await self.get_player(after.guild)
                if player.is_playing:
                    log.info("[AUTOPAUSE] Pausing")
                    player.pause()
