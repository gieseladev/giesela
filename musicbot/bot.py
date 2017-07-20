import asyncio
import inspect
import os
import re
import shutil
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from random import choice

import aiohttp
import discord
from discord import Client, utils
from discord.enums import ChannelType
from discord.object import Object
from discord.utils import find
from discord.voice_client import VoiceClient

from . import downloader, exceptions
from .commands.admin_commands import AdminCommands
from .commands.fun_commands import FunCommands
from .commands.info_commands import InfoCommands
from .commands.misc_commands import MiscCommands
from .commands.player_commands import PlayerCommands
from .commands.playlist_commands import PlaylistCommands
from .commands.queue_commands import QueueCommands
from .commands.tool_commands import ToolCommands
from .config import Config, ConfigDefaults
from .constants import VERSION as BOTVERSION
from .constants import AUDIO_CACHE_PATH, DISCORD_MSG_CHAR_LIMIT
from .entry import RadioSongEntry, StreamEntry, TimestampEntry
from .games.game_cah import GameCAH
from .opus_loader import load_opus_lib
from .player import MusicPlayer
from .random_sets import RandomSets
from .reminder import Calendar
from .saved_playlists import Playlists
from .settings import Settings
from .utils import Response, load_file, ordinal, paginate
from .web_socket_server import GieselaServer

load_opus_lib()


class MusicBot(Client, AdminCommands, FunCommands, InfoCommands,  MiscCommands, PlayerCommands, PlaylistCommands, QueueCommands, ToolCommands):

    def __init__(self):
        self.players = {}
        self.the_voice_clients = {}
        self.locks = defaultdict(asyncio.Lock)
        self.voice_client_connect_lock = asyncio.Lock()
        self.voice_client_move_lock = asyncio.Lock()

        self.config = Config(ConfigDefaults.options_file)
        self.playlists = Playlists(ConfigDefaults.playlists_file)
        self.random_sets = RandomSets(ConfigDefaults.random_sets)
        self.online_loggers = {}
        self.cah = GameCAH(self)

        self.blacklist = set(load_file(self.config.blacklist_file))
        self.autoplaylist = load_file(self.config.auto_playlist_file)
        self.downloader = downloader.Downloader(download_folder='audio_cache')
        self.calendar = Calendar(self)

        self.exit_signal = None
        self.init_ok = False
        self.cached_client_id = None
        self.chatters = {}
        self.blocked_commands = Settings.get_setting(
            "blocked_commands", default={})
        self.users_in_menu = set()

        if not self.autoplaylist:
            print("Warning: Autoplaylist is empty, disabling.")
            self.config.auto_playlist = False

        ssd_defaults = {'last_np_msg': None, 'auto_paused': False}
        self.server_specific_data = defaultdict(lambda: dict(ssd_defaults))

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += ' MusicBot/%s' % BOTVERSION
        self.instant_translate = False
        self.instant_translate_mode = 1
        self.instant_translate_certainty = .7

        self.load_online_loggers()

    @staticmethod
    def _fixg(x, dp=2):
        return ('{:.%sf}' % dp).format(x).rstrip('0').rstrip('.')

    def _get_owner(self, voice=False):
        if voice:
            for server in self.servers:
                for channel in server.channels:
                    for m in channel.voice_members:
                        if m.id == self.config.owner_id:
                            return m
        else:
            return discord.utils.find(lambda m: m.id == self.config.owner_id,
                                      self.get_all_members())

    def _delete_old_audiocache(self, path=AUDIO_CACHE_PATH):
        try:
            shutil.rmtree(path)
            return True
        except:
            try:
                os.rename(path, path + '__')
            except:
                return False
            try:
                shutil.rmtree(path)
            except:
                os.rename(path + '__', path)
                return False

        return True

    async def _auto_summon(self):
        owner = self._get_owner(voice=True)
        if owner:
            print("Found owner in \"%s\", attempting to join..." %
                  owner.voice_channel.name)
            await self.cmd_summon(owner.voice_channel, owner, None)
            return owner.voice_channel

    async def _autojoin_channels(self, channels):
        joined_servers = []

        for channel in channels:
            if channel.server in joined_servers:
                print("Already joined a channel in %s, skipping" %
                      channel.server.name)
                continue

            if channel and channel.type == discord.ChannelType.voice:
                print("Attempting to autojoin %s in %s" %
                      (channel.name, channel.server.name))

                chperms = channel.permissions_for(channel.server.me)

                if not chperms.connect:
                    print("Cannot join channel \"%s\", no permission." %
                          channel.name)
                    continue

                elif not chperms.speak:
                    print(
                        "Will not join channel \"%s\", no permission to speak."
                        % channel.name)
                    continue

                try:
                    player = await self.get_player(channel, create=True)

                    if player.is_stopped:
                        player.play()

                    if self.config.auto_playlist:
                        await self.on_player_finished_playing(player)

                    joined_servers.append(channel.server)
                except Exception as e:
                    if self.config.debug_mode:
                        traceback.print_exc()
                    print("Failed to join", channel.name)

            elif channel:
                print("Not joining %s on %s, that's a text channel." %
                      (channel.name, channel.server.name))

            else:
                print("Invalid channel thing: " + channel)

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def _manual_delete_check(self, message, *, quiet=False):
        if self.config.delete_invoking:
            await self.safe_delete_message(message, quiet=quiet)

    async def generate_invite_link(self, *, permissions=None, server=None):
        if not self.cached_client_id:
            appinfo = await self.application_info()
            self.cached_client_id = appinfo.id

        return discord.utils.oauth_url(
            self.cached_client_id, permissions=permissions, server=server)

    async def get_voice_client(self, channel):
        if isinstance(channel, Object):
            channel = self.get_channel(channel.id)

        if getattr(channel, 'type', ChannelType.text) != ChannelType.voice:
            raise AttributeError('Channel passed must be a voice channel')

        with await self.voice_client_connect_lock:
            server = channel.server
            if server.id in self.the_voice_clients:
                return self.the_voice_clients[server.id]

            s_id = self.ws.wait_for('VOICE_STATE_UPDATE',
                                    lambda d: d.get('user_id') == self.user.id)
            _voice_data = self.ws.wait_for('VOICE_SERVER_UPDATE',
                                           lambda d: True)

            await self.ws.voice_state(server.id, channel.id)

            s_id_data = await asyncio.wait_for(
                s_id, timeout=10, loop=self.loop)
            voice_data = await asyncio.wait_for(
                _voice_data, timeout=10, loop=self.loop)
            session_id = s_id_data.get('session_id')

            kwargs = {
                'user': self.user,
                'channel': channel,
                'data': voice_data,
                'loop': self.loop,
                'session_id': session_id,
                'main_ws': self.ws
            }
            voice_client = VoiceClient(**kwargs)
            self.the_voice_clients[server.id] = voice_client

            retries = 3
            for x in range(retries):
                try:
                    print("Attempting connection...")
                    await asyncio.wait_for(
                        voice_client.connect(), timeout=10, loop=self.loop)
                    print("Connection established.")
                    break
                except:
                    traceback.print_exc()
                    print("Failed to connect, retrying (%s/%s)..." %
                          (x + 1, retries))
                    await asyncio.sleep(1)
                    await self.ws.voice_state(server.id, None, self_mute=True)
                    await asyncio.sleep(1)

                    if x == retries - 1:
                        raise exceptions.HelpfulError(
                            "Cannot establish connection to voice chat.  "
                            "Something may be blocking outgoing UDP connections.",
                            "This may be an issue with a firewall blocking UDP.  "
                            "Figure out what is blocking UDP and disable it.  "
                            "It's most likely a system firewall or overbearing anti-virus firewall.  "
                        )

            return voice_client

    def get_global_user(self, user_id):
        for server in self.servers:
            mem = server.get_member(user_id)
            if mem is not None:
                return mem

        return None

    async def mute_voice_client(self, channel, mute):
        await self._update_voice_state(channel, mute=mute)

    async def deafen_voice_client(self, channel, deaf):
        await self._update_voice_state(channel, deaf=deaf)

    async def move_voice_client(self, channel):
        await self._update_voice_state(channel)

    async def reconnect_voice_client(self, server):
        if server.id not in self.the_voice_clients:
            return

        vc = self.the_voice_clients.pop(server.id)
        _paused = False

        player = None
        if server.id in self.players:
            player = self.players[server.id]
            if player.is_playing:
                player.pause()
                _paused = True

        try:
            await vc.disconnect()
        except:
            print("Error disconnecting during reconnect")
            traceback.print_exc()

        await asyncio.sleep(0.1)

        if player:
            new_vc = await self.get_voice_client(vc.channel)
            player.reload_voice(new_vc)

            if player.is_paused and _paused:
                player.resume()

    async def disconnect_voice_client(self, server):
        if server.id not in self.the_voice_clients:
            return

        if server.id in self.players:
            self.players.pop(server.id).kill()

        await self.the_voice_clients.pop(server.id).disconnect()

    async def disconnect_all_voice_clients(self):
        for vc in self.the_voice_clients.copy().values():
            await self.disconnect_voice_client(vc.channel.server)

    async def _update_voice_state(self, channel, *, mute=False, deaf=False):
        if isinstance(channel, Object):
            channel = self.get_channel(channel.id)

        if getattr(channel, 'type', ChannelType.text) != ChannelType.voice:
            raise AttributeError('Channel passed must be a voice channel')

        # I'm not sure if this lock is actually needed
        with await self.voice_client_move_lock:
            server = channel.server

            payload = {
                'op': 4,
                'd': {
                    'guild_id': server.id,
                    'channel_id': channel.id,
                    'self_mute': mute,
                    'self_deaf': deaf
                }
            }

            await self.ws.send(utils.to_json(payload))
            self.the_voice_clients[server.id].channel = channel

    async def get_player(self, channel=None, create=False, auto_summon=True, server_id=None):
        server = channel.server if channel else self.get_server(server_id)

        if server.id not in self.players:
            if not create:
                if auto_summon:
                    channel = await self.goto_home(
                        channel.server)
                else:
                    raise exceptions.CommandError(
                        'The bot is not in a voice channel.  '
                        'Use %ssummon to summon it to your voice channel.' %
                        self.config.command_prefix)

            voice_client = await self.get_voice_client(channel)

            player = MusicPlayer(self, voice_client) \
                .on('play', self.on_player_play) \
                .on('resume', self.on_player_resume) \
                .on('pause', self.on_player_pause) \
                .on('stop', self.on_player_stop) \
                .on('finished-playing', self.on_player_finished_playing) \
                .on('entry-added', self.on_player_entry_added)

            self.players[server.id] = player

        return self.players[server.id]

    async def on_player_play(self, player, entry):
        GieselaServer.send_player_information_update(
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
                            'last_np_msg'] = None
                    break  # This is probably redundant

            if isinstance(entry, TimestampEntry):
                sub_entry = entry.current_sub_entry
                sub_title = sub_entry["name"]
                sub_index = sub_entry["index"] + 1
                newmsg = "Now playing **{0}** ({1}{2} entry) from \"{3}\"".format(
                    sub_title, sub_index, ordinal(sub_index), entry.whole_title)
            elif isinstance(entry, RadioSongEntry):
                newmsg = "Now playing **{}**".format(
                    " - ".join((entry.artist, entry.title)))
            else:
                newmsg = "Now playing **{}**".format(entry.title)

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
        GieselaServer.send_player_information_update(
            player.voice_client.server.id)

    async def on_player_pause(self, player, entry, **_):
        await self.update_now_playing(entry, True)
        GieselaServer.send_player_information_update(
            player.voice_client.server.id)

    async def on_player_stop(self, player, **_):
        await self.update_now_playing()
        GieselaServer.send_player_information_update(
            player.voice_client.server.id)

    async def on_player_finished_playing(self, player, **_):
        if not player.playlist.entries and not player.current_entry:
            GieselaServer.send_player_information_update(
                player.voice_client.server.id)

        if not player.playlist.entries and not player.current_entry and self.config.auto_playlist:
            if self.config.auto_playlist:
                while self.autoplaylist:
                    song_url = choice(self.autoplaylist)
                    info = await self.downloader.safe_extract_info(
                        player.playlist.loop,
                        song_url,
                        download=False,
                        process=False)

                    if not info:
                        self.autoplaylist.remove(song_url)
                        print(
                            "[Info] Removing unplayable song from autoplaylist: %s"
                            % song_url)
                        write_file(self.config.auto_playlist_file,
                                   self.autoplaylist)
                        continue

                    if info.get('entries', None):  # or .get('_type', '') == 'playlist'
                        pass  # Wooo playlist
                        # Blarg how do I want to do this

                    try:
                        await player.playlist.add_entry(
                            song_url, channel=None, author=None)
                    except exceptions.ExtractionError as e:
                        print("Error adding song from autoplaylist:", e)
                        continue

                    break

                if not self.autoplaylist:
                    print(
                        "[Warning] No playable songs in the autoplaylist, disabling."
                    )
                    self.config.auto_playlist = False

    async def on_player_entry_added(self, playlist, entry, **_):
        pass

    async def update_now_playing(self, entry=None, is_paused=False):
        game = None

        if self.user.bot:
            activeplayers = sum(1 for p in self.players.values()
                                if p.is_playing)
            if activeplayers > 1:
                game = discord.Game(name="Music")
                entry = None

            elif activeplayers == 1:
                player = discord.utils.get(
                    self.players.values(), is_playing=True)
                entry = player.current_entry

        if entry:
            prefix = "\u275A\u275A" if is_paused else ""

            if isinstance(entry, StreamEntry):
                prefix += "\u25CE"
                name = entry.title
            elif isinstance(entry, TimestampEntry):
                prefix += "\u1F4DC"
                name = entry.title
            else:
                name = entry.title

            name = u"{} {}".format(prefix, name)[:128]
            game = discord.Game(name=name)

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
                        asyncio.ensure_future(
                            self._wait_delete_msg(nmsg, expire_in))

                    if also_delete and isinstance(also_delete,
                                                  discord.Message):
                        asyncio.ensure_future(
                            self._wait_delete_msg(also_delete, expire_in))
            else:
                msg = await self.send_message(
                    dest, content, tts=tts, embed=embed)

                if msg and expire_in:
                    asyncio.ensure_future(
                        self._wait_delete_msg(msg, expire_in))

                if also_delete and isinstance(also_delete, discord.Message):
                    asyncio.ensure_future(
                        self._wait_delete_msg(also_delete, expire_in))

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

    async def safe_edit_message(self, message, new, *, send_if_fail=False, quiet=False, keep_at_bottom=False):
        if keep_at_bottom:
            async for lmsg in self.logs_from(message.channel, limit=5):
                if lmsg.id == message.id:
                    break
            else:
                await self.safe_delete_message(message)
                return await self.safe_send_message(message.channel, new)
                return

        try:
            return await self.edit_message(message, new)

        except discord.NotFound:
            if not quiet:
                print(
                    "Warning: Cannot edit message \"%s\", message not found" %
                    message.clean_content)
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                return await self.safe_send_message(message.channel, new)

    async def send_typing(self, destination):
        try:
            return await super().send_typing(destination)
        except discord.Forbidden:
            if self.config.debug_mode:
                print(
                    "Could not send typing to %s, no permssion" % destination)

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

    async def goto_home(self, server, join=True):
        channel = find(lambda c: c.type == ChannelType.voice and any(x in c.name.lower().split(
        ) for x in ["giesela", "musicbot", "bot", "music", "reign"]), server.channels)
        if channel is None:
            channel = choice(
                filter(lambda c: c.type == ChannelType.voice, server.channels))
        if join:
            await self.get_player(channel, create=True)
        return channel

    async def logout(self):
        await self.disconnect_all_voice_clients()
        return await super().logout()

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

    async def on_resumed(self):
        for vc in self.the_voice_clients.values():
            vc.main_ws = self.ws

    async def on_ready(self):
        print('\rConnected!  Musicbot v%s\n' % BOTVERSION)

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

        owner = self._get_owner(voice=True) or self._get_owner()
        if owner and self.servers:
            print("Owner: %s/%s#%s\n" % (owner.id, owner.name,
                                         owner.discriminator))

            print('Server List:')
            [print(' - ' + s.name) for s in self.servers]

        elif self.servers:
            print("Owner could not be found on any server (id: %s)\n" %
                  self.config.owner_id)

            print('Server List:')
            [print(' - ' + s.name) for s in self.servers]

        else:
            print("Owner unknown, bot is not on any servers.")
            if self.user.bot:
                print(
                    "\nTo make the bot join a server, paste this link in your browser."
                )
                print(
                    "Note: You should be logged into your main account and have \n"
                    "manage server permissions on the server you want the bot to join.\n"
                )
                print("    " + await self.generate_invite_link())

        print()

        if self.config.bound_channels:
            chlist = set(
                self.get_channel(i) for i in self.config.bound_channels if i)
            chlist.discard(None)
            invalids = set()

            invalids.update(c for c in chlist
                            if c.type == discord.ChannelType.voice)
            chlist.difference_update(invalids)
            self.config.bound_channels.difference_update(invalids)

            print("Bound to text channels:")
            [
                print(' - %s/%s' % (ch.server.name.strip(),
                                    ch.name.strip())) for ch in chlist if ch
            ]

            if invalids and self.config.debug_mode:
                print("\nNot binding to voice channels:")
                [
                    print(' - %s/%s' % (ch.server.name.strip(),
                                        ch.name.strip())) for ch in invalids
                    if ch
                ]

            print()

        else:
            print("Not bound to any text channels")

        if self.config.autojoin_channels:
            chlist = set(
                self.get_channel(i) for i in self.config.autojoin_channels
                if i)
            chlist.discard(None)
            invalids = set()

            invalids.update(c for c in chlist
                            if c.type == discord.ChannelType.text)
            chlist.difference_update(invalids)
            self.config.autojoin_channels.difference_update(invalids)

            print("Autojoining voice chanels:")
            [
                print(' - %s/%s' % (ch.server.name.strip(),
                                    ch.name.strip())) for ch in chlist if ch
            ]

            if invalids and self.config.debug_mode:
                print("\nCannot join text channels:")
                [
                    print(' - %s/%s' % (ch.server.name.strip(),
                                        ch.name.strip())) for ch in invalids
                    if ch
                ]

            autojoin_channels = chlist

        else:
            print("Not autojoining any voice channels")
            autojoin_channels = set()

        print()
        print("Options:")

        print("  Command prefix: " + self.config.command_prefix)
        print(
            "  Default volume: %s%%" % int(self.config.default_volume * 100))
        print("  Auto-Summon: " + ['Disabled', 'Enabled'
                                   ][self.config.auto_summon])
        print("  Auto-Playlist: " + ['Disabled', 'Enabled'
                                     ][self.config.auto_playlist])
        print("  Auto-Pause: " + ['Disabled', 'Enabled'
                                  ][self.config.auto_pause])
        print("  Delete Messages: " + ['Disabled', 'Enabled'
                                       ][self.config.delete_messages])
        if self.config.delete_messages:
            print("    Delete Invoking: " + ['Disabled', 'Enabled'
                                             ][self.config.delete_invoking])
        print("  Debug Mode: " + ['Disabled', 'Enabled'
                                  ][self.config.debug_mode])
        print("  Downloaded songs will be %s" % ['deleted', 'saved'
                                                 ][self.config.save_videos])
        print()

        # maybe option to leave the ownerid blank and generate a random command for the owner to use
        # wait_for_message is pretty neato

        if not self.config.save_videos and os.path.isdir(AUDIO_CACHE_PATH):
            if self._delete_old_audiocache():
                print("Deleting old audio cache")
            else:
                print("Could not delete old audio cache, moving on.")

        if self.config.autojoin_channels:
            await self._autojoin_channels(autojoin_channels)

        elif self.config.auto_summon:
            print("Attempting to autosummon...", flush=True)

            # waitfor + get value
            owner_vc = await self._auto_summon()

            if owner_vc:
                print("Done!", flush=True)
                if self.config.auto_playlist:
                    print("Starting auto-playlist")
                    await self.on_player_finished_playing(
                        await self.get_player(owner_vc))
            else:
                print(
                    "Owner not found in a voice channel, could not autosummon."
                )

        print()
        # t-t-th-th-that's all folks!

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
        command = raw_command.lstrip(self.config.command_prefix).lower().strip()

        handler = getattr(self, 'cmd_%s' % command, None)
        if not handler:
            return

        if command in self.blocked_commands:
            required_args, reason = self.blocked_commands[command]
            if all(arg in args for arg in required_args):
                await self.send_message(message.channel, reason)
                return

        if message.channel.is_private:
            if not (message.author.id == self.config.owner_id and command ==
                    'joinserver') and not command in self.config.private_chat_commands:
                await self.send_message(
                    message.channel,
                    'You cannot use this command in private messages.')
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

        # noinspection PyBroadException
        try:
            handler_kwargs = {}
            if params.pop("message", None):
                handler_kwargs["message"] = message

            if params.pop("raw_content", None):
                handler_kwargs["raw_content"] = raw_content

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('server', None):
                handler_kwargs['server'] = message.server

            if params.pop("player", None):
                handler_kwargs["player"] = await self.get_player(
                    message.channel)

            if params.pop('user_mentions', None):
                handler_kwargs['user_mentions'] = list(
                    map(message.server.get_member, message.raw_mentions))

            if params.pop('channel_mentions', None):
                handler_kwargs['channel_mentions'] = list(
                    map(message.server.get_channel,
                        message.raw_channel_mentions))

            if params.pop('voice_channel', None):
                handler_kwargs[
                    'voice_channel'] = message.server.me.voice_channel

            if params.pop('leftover_args', None):
                handler_kwargs['leftover_args'] = args

            args_expected = []
            for key, param in list(params.items()):
                doc_key = '[%s=%s]' % (
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
                    content = '%s, %s' % (message.author.mention, content)

                sentmsg = await self.safe_send_message(
                    message.channel,
                    content,
                    expire_in=response.delete_after
                    if self.config.delete_messages else 0,
                    also_delete=message
                    if self.config.delete_invoking else None,
                    embed=response.embed
                )

        except (exceptions.CommandError, exceptions.HelpfulError,
                exceptions.ExtractionError) as e:
            print("{0.__class__}: {0.message}".format(e))

            expirein = e.expire_in if self.config.delete_messages else None
            alsodelete = message if self.config.delete_invoking else None

            await self.safe_send_message(
                message.channel,
                '```\n%s\n```' % e.message,
                expire_in=expirein,
                also_delete=alsodelete)

        except exceptions.Signal:
            raise

        except Exception:
            traceback.print_exc()
            if self.config.debug_mode:
                await self.safe_send_message(
                    message.channel, '```\n%s\n```' % traceback.format_exc())

    async def autopause(self, before, after):
        if not all([before, after]):
            return

        if before.voice_channel == after.voice_channel:
            return

        if before.server.id not in self.players:
            return

        # This should always work, right?
        my_voice_channel = after.server.me.voice_channel

        if not my_voice_channel:
            return

        if before.voice_channel == my_voice_channel:
            joining = False
        elif after.voice_channel == my_voice_channel:
            joining = True
        else:
            return  # Not my channel

        moving = before == before.server.me

        player = await self.get_player(my_voice_channel)

        if after == after.server.me and after.voice_channel:
            player.voice_client.channel = after.voice_channel

        if not self.config.auto_pause:
            return

        vm_count = sum(
            1 for m in my_voice_channel.voice_members if m != after.server.me and not m.bot)
        if vm_count == 0:
            if player.is_playing:
                print("[AUTOPAUSE] Pausing")
                player.pause()
        elif vm_count == 1 and joining:
            if player.is_paused:
                print("[AUTOPAUSE] Unpausing")
                player.resume()

    async def on_server_update(self,
                               before: discord.Server,
                               after: discord.Server):
        if before.region != after.region:
            print("[Servers] \"%s\" changed regions: %s -> %s" %
                  (after.name, before.region, after.region))

            await self.reconnect_voice_client(after)

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
        await self.autopause(before, after)

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


if __name__ == '__main__':
    bot = MusicBot()
    bot.run()
