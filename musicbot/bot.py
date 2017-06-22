import asyncio
import configparser
import datetime
import inspect
import json
import operator
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import urllib
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from random import choice, random, shuffle
from textwrap import dedent, indent

import aiohttp
import discord
import goslate
import requests
import wikipedia
from discord import Embed, utils
from discord.enums import ChannelType
from discord.ext.commands.bot import _get_variable
from discord.object import Object
from discord.utils import find
from discord.voice_client import VoiceClient
from moviepy import editor, video
from openpyxl import Workbook
from pyshorteners import Shortener

from . import downloader, exceptions
from .bookmarks import bookmark
from .cleverbot import CleverWrap
from .config import Config, ConfigDefaults
from .constants import VERSION as BOTVERSION
from .constants import (AUDIO_CACHE_PATH, DISCORD_MSG_CHAR_LIMIT,
                        get_dev_changelog, get_dev_version, get_master_version)
from .entry import URLPlaylistEntry
from .games.game_2048 import Game2048
from .games.game_cah import GameCAH
from .games.game_hangman import GameHangman
from .langid import LanguageIdentifier, model
from .logger import OnlineLogger
from .nine_gag import ContentType, get_post
from .opus_loader import load_opus_lib
from .papers import Papers
from .player import MusicPlayer
from .playlist import Playlist
from .radio import Radio
from .radios import Radios
from .random_sets import RandomSets
from .reminder import Action, Calendar
from .saved_playlists import Playlists
from .settings import Settings
from .socket_server import SocketServer
from .translate import Translator
# import newspaper
from .tungsten import Tungsten
from .twitter_api import get_tweet
from .utils import (clean_songname, create_bar, escape_dis, format_time,
                    hex_to_dec, load_file, nice_cut, ordinal, paginate,
                    parse_timestamp, prettydate, random_line, to_timestamp,
                    write_file)

load_opus_lib()


class Response:
    def __init__(self, content=None, reply=False, delete_after=0, embed=None):
        self.content = content
        self.reply = reply
        self.delete_after = delete_after
        self.embed = embed


class MusicBot(discord.Client):
    privateChatCommands = [
        "c", "ask", "requestfeature", "random", "translate", "help", "say",
        "broadcast", "news", "game", "wiki", "cah", "execute", "secret"
    ]

    def __init__(self):
        self.players = ***REMOVED******REMOVED***
        self.the_voice_clients = ***REMOVED******REMOVED***
        self.locks = defaultdict(asyncio.Lock)
        self.voice_client_connect_lock = asyncio.Lock()
        self.voice_client_move_lock = asyncio.Lock()

        self.config = Config(ConfigDefaults.options_file)
        # self.papers = Papers(ConfigDefaults.papers_file)
        self.radios = Radios(ConfigDefaults.radios_file)
        self.playlists = Playlists(ConfigDefaults.playlists_file)
        self.random_sets = RandomSets(ConfigDefaults.random_sets)
        self.online_loggers = ***REMOVED******REMOVED***
        self.cah = GameCAH(self)

        self.blacklist = set(load_file(self.config.blacklist_file))
        self.autoplaylist = load_file(self.config.auto_playlist_file)
        self.downloader = downloader.Downloader(download_folder='audio_cache')
        # self.radio = Radio()
        self.calendar = Calendar(self)
        self.socket_server = SocketServer(self)
        # self.shortener = Shortener(
        #     "Google", api_key="AIzaSyCU67YMHlfTU_PX2ngHeLd-_dUds-m502k")
        self.translator = Translator("en")
        self.lang_identifier = LanguageIdentifier.from_modelstring(
            model, norm_probs=True)

        self.exit_signal = None
        self.init_ok = False
        self.cached_client_id = None
        self.chatters = ***REMOVED******REMOVED***
        self.blocked_commands = ***REMOVED******REMOVED***
        self.users_in_menu = set()

        if not self.autoplaylist:
            self.log("Warning: Autoplaylist is empty, disabling.")
            self.config.auto_playlist = False

        ssd_defaults = ***REMOVED***'last_np_msg': None, 'auto_paused': False***REMOVED***
        self.server_specific_data = defaultdict(lambda: dict(ssd_defaults))

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += ' MusicBot/%s' % BOTVERSION
        self.instant_translate = False
        self.instant_translate_mode = 1
        self.instant_translate_certainty = .7

        self.load_online_loggers()

    def owner_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Only allow the owner to use these commands
            orig_msg = _get_variable('message')

            if not orig_msg or orig_msg.author.id == self.config.owner_id:
                return await func(self, *args, **kwargs)
            else:
                return Response("only the owner can use this command")

        return wrapper

    def command_info(version, timestamp, changelog=***REMOVED******REMOVED***):
        def function_decorator(func):
            func.version = version
            func.timestamp = datetime.fromtimestamp(timestamp)
            func.changelog = [(ver, datetime.fromtimestamp(time), log)
                              for ver, (time, log) in changelog.items()]

            return func

        return function_decorator

    def block_user(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            orig_msg = _get_variable("message")

            self.users_in_menu.add(orig_msg.author.id)
            self.log("Now blocking " + str(orig_msg.author))
            res = await func(self, *args, **kwargs)
            self.users_in_menu.remove(orig_msg.author.id)
            self.log("Unblocking " + str(orig_msg.author))
            return res

        return wrapper

    @staticmethod
    def _fixg(x, dp=2):
        return ('***REMOVED***:.%sf***REMOVED***' % dp).format(x).rstrip('0').rstrip('.')

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
            self.log("Found owner in \"%s\", attempting to join..." %
                     owner.voice_channel.name)
            await self.cmd_summon(owner.voice_channel, owner, None)
            return owner.voice_channel

    async def _autojoin_channels(self, channels):
        joined_servers = []

        for channel in channels:
            if channel.server in joined_servers:
                self.log("Already joined a channel in %s, skipping" %
                         channel.server.name)
                continue

            if channel and channel.type == discord.ChannelType.voice:
                self.log("Attempting to autojoin %s in %s" %
                         (channel.name, channel.server.name))

                chperms = channel.permissions_for(channel.server.me)

                if not chperms.connect:
                    self.log("Cannot join channel \"%s\", no permission." %
                             channel.name)
                    continue

                elif not chperms.speak:
                    self.log(
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
                    self.log("Failed to join", channel.name)

            elif channel:
                self.log("Not joining %s on %s, that's a text channel." %
                         (channel.name, channel.server.name))

            else:
                self.log("Invalid channel thing: " + channel)

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

            kwargs = ***REMOVED***
                'user': self.user,
                'channel': channel,
                'data': voice_data,
                'loop': self.loop,
                'session_id': session_id,
                'main_ws': self.ws
            ***REMOVED***
            voice_client = VoiceClient(**kwargs)
            self.the_voice_clients[server.id] = voice_client

            retries = 3
            for x in range(retries):
                try:
                    self.log("Attempting connection...")
                    await asyncio.wait_for(
                        voice_client.connect(), timeout=10, loop=self.loop)
                    self.log("Connection established.")
                    break
                except:
                    traceback.print_exc()
                    self.log("Failed to connect, retrying (%s/%s)..." %
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
            self.log("Error disconnecting during reconnect")
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

            payload = ***REMOVED***
                'op': 4,
                'd': ***REMOVED***
                    'guild_id': server.id,
                    'channel_id': channel.id,
                    'self_mute': mute,
                    'self_deaf': deaf
                ***REMOVED***
            ***REMOVED***

            await self.ws.send(utils.to_json(payload))
            self.the_voice_clients[server.id].channel = channel

    async def get_player(self, channel, create=False,
                         auto_summon=True) -> MusicPlayer:
        server = channel.server

        if server.id not in self.players:
            if not create:
                if auto_summon:
                    channel = await self.socket_summon(
                        channel.server) or await self.goto_home(
                            channel.server)
                else:
                    raise exceptions.CommandError(
                        'The bot is not in a voice channel.  '
                        'Use %ssummon to summon it to your voice channel.' %
                        self.config.command_prefix)

            voice_client = await self.get_voice_client(channel)

            playlist = Playlist(self)
            player = MusicPlayer(self, voice_client, playlist) \
                .on('play', self.on_player_play) \
                .on('resume', self.on_player_resume) \
                .on('pause', self.on_player_pause) \
                .on('stop', self.on_player_stop) \
                .on('finished-playing', self.on_player_finished_playing) \
                .on('entry-added', self.on_player_entry_added)

            self.players[server.id] = player

        return self.players[server.id]

    async def on_player_play(self, player, entry):
        await self.update_now_playing(entry)

        channel = entry.meta.get('channel', None)
        author = entry.meta.get('author', None)

        if channel and author:
            last_np_msg = self.server_specific_data[channel.server][
                'last_np_msg']
            if last_np_msg and last_np_msg.channel == channel:

                # if the last np message isn't the last message in the channel; delete it
                async for lmsg in self.logs_from(channel, limit=1):
                    if lmsg != last_np_msg and last_np_msg:
                        await self.safe_delete_message(last_np_msg)
                        self.server_specific_data[channel.server][
                            'last_np_msg'] = None
                    break  # This is probably redundant

            if entry.provides_timestamps:
                e = entry.get_current_song_from_timestamp(player.progress)
                newmsg = "Now playing *****REMOVED***0***REMOVED***** (***REMOVED***1***REMOVED******REMOVED***2***REMOVED*** entry) from \"***REMOVED***3***REMOVED***\"".format(
                    e["name"], e["index"] + 1,
                    ordinal(e["index"] + 1), entry.title)
            elif type(entry).__name__ == "StreamPlaylistEntry" and entry.radio_station_data is not None:
                newmsg = "Now playing *****REMOVED******REMOVED***** from `***REMOVED******REMOVED***`".format(await player._absolute_current_song(), entry.radio_station_data.name)
            else:
                newmsg = 'Now playing in %s: **%s**' % (
                    player.voice_client.channel.name, entry.title)

            if self.server_specific_data[channel.server]['last_np_msg']:
                self.server_specific_data[channel.server][
                    'last_np_msg'] = await self.safe_edit_message(
                        last_np_msg, newmsg, send_if_fail=True)
            else:
                self.server_specific_data[channel.server][
                    'last_np_msg'] = await self.safe_send_message(
                        channel, newmsg)
                # await self.safe_send_message(channel, "Now Playing " +
                # entry.title, tts=True, expire_in=1)

    async def on_player_resume(self, entry, **_):
        await self.update_now_playing(entry)

    async def on_player_pause(self, entry, **_):
        await self.update_now_playing(entry, True)

    async def on_player_stop(self, **_):
        await self.update_now_playing()

    async def on_player_finished_playing(self, player, **_):
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
                        self.log(
                            "[Info] Removing unplayable song from autoplaylist: %s"
                            % song_url)
                        write_file(self.config.auto_playlist_file,
                                   self.autoplaylist)
                        continue

                    if info.get('entries',
                                None):  # or .get('_type', '') == 'playlist'
                        pass  # Wooo playlist
                        # Blarg how do I want to do this

                    try:
                        await player.playlist.add_entry(
                            song_url, channel=None, author=None)
                    except exceptions.ExtractionError as e:
                        self.log("Error adding song from autoplaylist:", e)
                        continue

                    break

                if not self.autoplaylist:
                    self.log(
                        "[Warning] No playable songs in the autoplaylist, disabling."
                    )
                    self.config.auto_playlist = False

    async def on_player_entry_added(self, playlist, entry, **_):
        pass

    async def on_server_join(self, server):
        for channel in server.channels:
            if channel.type is not ChannelType.text:
                continue

            msg = await self.safe_send_message(
                channel,
                "Hello there,\nMy name is ***REMOVED******REMOVED***!\n\n*Type ***REMOVED******REMOVED***help to find out more.*".
                format(self.user.mention, self.config.command_prefix))
            if msg is not None:
                return

    async def update_now_playing(self, entry=None, is_paused=False):
        game = None

        if self.user.bot:
            activeplayers = sum(1 for p in self.players.values()
                                if p.is_playing)
            if activeplayers > 1:
                game = discord.Game(name="music on %s servers" % activeplayers)
                entry = None

            elif activeplayers == 1:
                player = discord.utils.get(
                    self.players.values(), is_playing=True)
                entry = player.current_entry

        if entry:
            prefix = u'\u275A\u275A ' if is_paused else ''

            if type(
                    entry
            ).__name__ == "StreamPlaylistEntry" and entry.radio_station_data is not None:
                name = u'***REMOVED******REMOVED***'.format(
                    await player._absolute_current_song())[:128]
                game = discord.Game(name=name)
            else:
                n = entry.title
                if entry.provides_timestamps:
                    e = entry.get_current_song_from_timestamp(player.progress)
                    n = e["name"]

                name = u'***REMOVED******REMOVED******REMOVED******REMOVED***'.format(prefix, n)[:128]
                game = discord.Game(name=name)

        await self.change_presence(game=game)

    async def safe_send_message(self,
                                dest,
                                content=None,
                                *,
                                max_letters=DISCORD_MSG_CHAR_LIMIT,
                                split_message=True,
                                tts=False,
                                expire_in=0,
                                also_delete=None,
                                quiet=False,
                                embed=None):
        msg = None
        try:
            if split_message and content and len(content) > max_letters:
                self.log("Message too long, splitting it up")
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
                self.log("Warning: Cannot send message to %s, no permission" %
                         dest.name)

        except discord.NotFound:
            if not quiet:
                self.log("Warning: Cannot send message to %s, invalid channel?"
                         % dest.name)

        return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await self.delete_message(message)

        except discord.Forbidden:
            if not quiet:
                self.log("Warning: Cannot delete message \"%s\", no permission"
                         % message.clean_content)

        except discord.NotFound:
            if not quiet:
                self.log(
                    "Warning: Cannot delete message \"%s\", message not found"
                    % message.clean_content)

    async def safe_edit_message(self,
                                message,
                                new,
                                *,
                                send_if_fail=False,
                                quiet=False):
        try:
            return await self.edit_message(message, new)

        except discord.NotFound:
            if not quiet:
                self.log(
                    "Warning: Cannot edit message \"%s\", message not found" %
                    message.clean_content)
            if send_if_fail:
                if not quiet:
                    self.log("Sending instead")
                return await self.safe_send_message(message.channel, new)

    def log(self, content="\n", *, end='\n', flush=True):
        sys.stdout.buffer.write((content + end).encode('utf-8', 'replace'))
        if flush:
            sys.stdout.flush()

    async def send_typing(self, destination):
        try:
            return await super().send_typing(destination)
        except discord.Forbidden:
            if self.config.debug_mode:
                self.log(
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

    # noinspection PyMethodOverriding
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
                self.log("Error in cleanup:", e)

            self.loop.close()
            if self.exit_signal:
                raise self.exit_signal

    async def logout(self):
        await self.disconnect_all_voice_clients()
        self.socket_server.shutdown()
        return await super().logout()

    async def on_error(self, event, *args, **kwargs):
        ex_type, ex, stack = sys.exc_info()

        if ex_type == exceptions.HelpfulError:
            self.log("Exception in", event)
            self.log(ex.message)

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
        self.log('\rConnected!  Musicbot v%s\n' % BOTVERSION)

        if self.config.owner_id == self.user.id:
            raise exceptions.HelpfulError(
                "Your OwnerID is incorrect or you've used the wrong credentials.",
                "The bot needs its own account to function.  "
                "The OwnerID is the id of the owner, not the bot.  "
                "Figure out which one is which and use the correct information."
            )

        self.init_ok = True

        self.log("Bot:   %s/%s#%s" % (self.user.id, self.user.name,
                                      self.user.discriminator))

        owner = self._get_owner(voice=True) or self._get_owner()
        if owner and self.servers:
            self.log("Owner: %s/%s#%s\n" % (owner.id, owner.name,
                                            owner.discriminator))

            self.log('Server List:')
            [self.log(' - ' + s.name) for s in self.servers]

        elif self.servers:
            self.log("Owner could not be found on any server (id: %s)\n" %
                     self.config.owner_id)

            self.log('Server List:')
            [self.log(' - ' + s.name) for s in self.servers]

        else:
            self.log("Owner unknown, bot is not on any servers.")
            if self.user.bot:
                self.log(
                    "\nTo make the bot join a server, paste this link in your browser."
                )
                self.log(
                    "Note: You should be logged into your main account and have \n"
                    "manage server permissions on the server you want the bot to join.\n"
                )
                self.log("    " + await self.generate_invite_link())

        self.log()

        if self.config.bound_channels:
            chlist = set(
                self.get_channel(i) for i in self.config.bound_channels if i)
            chlist.discard(None)
            invalids = set()

            invalids.update(c for c in chlist
                            if c.type == discord.ChannelType.voice)
            chlist.difference_update(invalids)
            self.config.bound_channels.difference_update(invalids)

            self.log("Bound to text channels:")
            [
                self.log(' - %s/%s' % (ch.server.name.strip(),
                                       ch.name.strip())) for ch in chlist if ch
            ]

            if invalids and self.config.debug_mode:
                self.log("\nNot binding to voice channels:")
                [
                    self.log(' - %s/%s' % (ch.server.name.strip(),
                                           ch.name.strip())) for ch in invalids
                    if ch
                ]

            self.log()

        else:
            self.log("Not bound to any text channels")

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

            self.log("Autojoining voice chanels:")
            [
                self.log(' - %s/%s' % (ch.server.name.strip(),
                                       ch.name.strip())) for ch in chlist if ch
            ]

            if invalids and self.config.debug_mode:
                self.log("\nCannot join text channels:")
                [
                    self.log(' - %s/%s' % (ch.server.name.strip(),
                                           ch.name.strip())) for ch in invalids
                    if ch
                ]

            autojoin_channels = chlist

        else:
            self.log("Not autojoining any voice channels")
            autojoin_channels = set()

        self.log()
        self.log("Options:")

        self.log("  Command prefix: " + self.config.command_prefix)
        self.log(
            "  Default volume: %s%%" % int(self.config.default_volume * 100))
        self.log("  Auto-Summon: " + ['Disabled', 'Enabled'
                                      ][self.config.auto_summon])
        self.log("  Auto-Playlist: " + ['Disabled', 'Enabled'
                                        ][self.config.auto_playlist])
        self.log("  Auto-Pause: " + ['Disabled', 'Enabled'
                                     ][self.config.auto_pause])
        self.log("  Delete Messages: " + ['Disabled', 'Enabled'
                                          ][self.config.delete_messages])
        if self.config.delete_messages:
            self.log("    Delete Invoking: " + ['Disabled', 'Enabled'
                                                ][self.config.delete_invoking])
        self.log("  Debug Mode: " + ['Disabled', 'Enabled'
                                     ][self.config.debug_mode])
        self.log("  Downloaded songs will be %s" % ['deleted', 'saved'
                                                    ][self.config.save_videos])
        self.log()

        # maybe option to leave the ownerid blank and generate a random command for the owner to use
        # wait_for_message is pretty neato

        if not self.config.save_videos and os.path.isdir(AUDIO_CACHE_PATH):
            if self._delete_old_audiocache():
                self.log("Deleting old audio cache")
            else:
                self.log("Could not delete old audio cache, moving on.")

        if self.config.autojoin_channels:
            await self._autojoin_channels(autojoin_channels)

        elif self.config.auto_summon:
            self.log("Attempting to autosummon...", flush=True)

            # waitfor + get value
            owner_vc = await self._auto_summon()

            if owner_vc:
                self.log("Done!", flush=True)
                if self.config.auto_playlist:
                    self.log("Starting auto-playlist")
                    await self.on_player_finished_playing(
                        await self.get_player(owner_vc))
            else:
                self.log(
                    "Owner not found in a voice channel, could not autosummon."
                )

        self.log()
        # t-t-th-th-that's all folks!

    async def socket_summon(self, server_id, summoner_id=None):
        server = self.get_server(server_id)
        if server == None:
            return False

        channels = server.channels
        target_channel = None
        max_members = 0

        for ch in channels:
            if summoner_id is not None and any(
                    [x.id == summoner_id for x in ch.voice_members]):
                target_channel = ch
                break

            if len(ch.voice_members) - sum(
                    [.5 for x in ch.voice_members if x.bot]) > max_members:
                target_channel = ch
                max_members = len(ch.voice_members)

        if target_channel == None:
            return False

        voice_client = self.the_voice_clients.get(server.id, None)
        if voice_client is not None and voice_client.channel.server == server:
            await self.move_voice_client(target_channel)
            return False

        chperms = target_channel.permissions_for(server.me)

        if not chperms.connect:
            return False
        elif not chperms.speak:
            return False

        await self.get_player(target_channel, create=True)
        self.socket_server.threaded_broadcast_information()
        return target_channel

    @command_info("1.9.5", 1477774380, ***REMOVED***
        "3.4.5": (1497616203, "Improved default help message using embeds"),
        "3.6.0": (1497904733, "Fixed weird indent of some help texts")
    ***REMOVED***)
    async def cmd_help(self, channel, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***help [command]`

        ///|Explanation
        Logs a help message.
        """
        command = None

        if len(leftover_args) > 0:
            command = " ".join(leftover_args)

        if command:
            cmd = getattr(self, 'cmd_' + command, None)
            if cmd:
                documentation = cmd.__doc__.format(
                    command_prefix=self.config.command_prefix)
                em = Embed(title="*****REMOVED******REMOVED*****".format(command.upper()))
                fields = documentation.split("///")
                if len(fields) < 2:  # backward compatibility
                    return Response(
                        "```\n***REMOVED******REMOVED***```".format(
                            dedent(cmd.__doc__).format(
                                command_prefix=self.config.command_prefix)),
                        delete_after=60)

                for field in fields:
                    if field is None or field is "":
                        continue
                    inline = True
                    if field.startswith("(NL)"):
                        inline = False
                        field = field[4:]
                        # self.log(field)

                    match = re.match(r"\|(.+)\n((?:.|\n)+)", field)
                    if match is None:
                        continue
                    title, text = match.group(1, 2)

                    em.add_field(
                        name="*****REMOVED******REMOVED*****".format(title), value=dedent(text), inline=inline)
                await self.send_message(channel, embed=em)
                return
                # return
                # Response("```\n***REMOVED******REMOVED***```".format(dedent(cmd.__doc__).format(command_prefix=self.config.command_prefix)),delete_after=60)
            else:
                # return Response("No such command", delete_after=10)
                self.log("Didn't find a command like that")
                config = configparser.ConfigParser(interpolation=None)
                if not config.read("config/helper.ini", encoding='utf-8'):
                    await self.safe_send_message(
                        channel,
                        "Something went wrong here. I cannot help you with this"
                    )
                    return

                funcs = ***REMOVED******REMOVED***

                for section in config.sections():
                    tags = json.loads(config.get(section, "tags"))
                    funcs[str(section)] = 0
                    for arg in leftover_args:
                        if arg.lower() in tags:
                            funcs[str(section)] += 1

                funcs = ***REMOVED***k: v for k, v in funcs.items() if v > 0***REMOVED***

                if len(funcs) <= 0:
                    await self.safe_send_message(
                        channel,
                        "Didn't find anything that may satisfy your wishes")
                    return

                sorted_funcs = sorted(
                    funcs.items(), key=operator.itemgetter(1), reverse=True)

                resp_str = "**You might wanna take a look at these functions:**\n\n"

                for func in sorted_funcs[:3]:
                    cmd = getattr(self, 'cmd_' + func[0], None)
                    helpText = dedent(cmd.__doc__).format(
                        command_prefix=self.config.command_prefix)
                    resp_str += "****REMOVED***0***REMOVED***:*\n```\n***REMOVED***1***REMOVED***```\n\n".format(
                        func[0], helpText)

                await self.safe_send_message(channel, resp_str, expire_in=60)

        else:
            em = Embed(
                title="GIESELA HELP",
                url="http://siku2.github.io/Giesela/",
                colour=hex_to_dec("828c51"),
                description="plz be welcum to mah new list of the **most fab** commands\nYou can always use `***REMOVED***0***REMOVED***help <cmd>` to get more detailed information on a command".
                format(self.config.command_prefix))

            music_commands = "`***REMOVED***0***REMOVED***play` play dem shit\n`***REMOVED***0***REMOVED***search` make sure you get ur shit\n`***REMOVED***0***REMOVED***stream` when u wanna go live\n`***REMOVED***0***REMOVED***pause` need a break?\n`***REMOVED***0***REMOVED***volume` oh shit turn it up\n`***REMOVED***0***REMOVED***seek` hide and snaek\n`***REMOVED***0***REMOVED***fwd` sanic fast, sanic skip\n`***REMOVED***0***REMOVED***rwd` go baek in tiem".format(
                self.config.command_prefix)
            em.add_field(name="Music", value=music_commands, inline=False)

            queue_commands = "`***REMOVED***0***REMOVED***queue` taky a looky bruh\n`***REMOVED***0***REMOVED***history` care to see the past?\n`***REMOVED***0***REMOVED***np` look at dem shit\n`***REMOVED***0***REMOVED***skip` skip regretful shit\n`***REMOVED***0***REMOVED***replay` when it's stuck in ur head\n`***REMOVED***0***REMOVED***repeat` over and over and over\n`***REMOVED***0***REMOVED***remove` \"that's not what I wanted\"\n`***REMOVED***0***REMOVED***clear` burn it all down\n`***REMOVED***0***REMOVED***shuffle` maek it random plz\n`***REMOVED***0***REMOVED***promote` I want it right now!".format(
                self.config.command_prefix)
            em.add_field(name="Queue", value=queue_commands, inline=False)

            playlist_commands = "`***REMOVED***0***REMOVED***playlist` create/edit/list playlists\n`***REMOVED***0***REMOVED***addtoplaylist` add shit to a playlist\n`***REMOVED***0***REMOVED***removefromplaylist` remove shit from a playlist".format(
                self.config.command_prefix)
            em.add_field(
                name="Playlist", value=playlist_commands, inline=False)

            misc_commands = "`***REMOVED***0***REMOVED***random` for when you can't decide\n`***REMOVED***0***REMOVED***game` when u're bored\n`***REMOVED***0***REMOVED***ask` when you don't know shit\n`***REMOVED***0***REMOVED***c` have a chat".format(
                self.config.command_prefix)
            em.add_field(name="Misc", value=misc_commands, inline=False)

            return Response(embed=em)
            # helpmsg = "**Commands**\n```"
            # commands = []
            #
            # for att in dir(self):
            #     if att.startswith('cmd_') and att != 'cmd_help':
            #         command_name = att.replace('cmd_', '').lower()
            #         commands.append("***REMOVED******REMOVED******REMOVED******REMOVED***".format(
            #             self.config.command_prefix, command_name))
            #
            # helpmsg += ", ".join(commands)
            # helpmsg += "```"
            # helpmsg += "A Discord Bot by siku2"
            #
            # return Response(helpmsg, reply=True, delete_after=60)

    async def cmd_blacklist(self, message, user_mentions, option, something):
        """
        ///|Usage
        ***REMOVED***command_prefix***REMOVED***blacklist [ + | - | add | remove ] @UserName [@UserName2 ...]
        ///|Explanation
        Add or remove users to the blacklist.
        """

        if not user_mentions:
            raise exceptions.CommandError("No users listed.", expire_in=20)

        if option not in ['+', '-', 'add', 'remove']:
            raise exceptions.CommandError(
                'Invalid option "%s" specified, use +, -, add, or remove' %
                option,
                expire_in=20)

        for user in user_mentions.copy():
            if user.id == self.config.owner_id:
                self.log(
                    "[Commands:Blacklist] The owner cannot be blacklisted.")
                user_mentions.remove(user)

        old_len = len(self.blacklist)

        if option in ['+', 'add']:
            self.blacklist.update(user.id for user in user_mentions)

            write_file(self.config.blacklist_file, self.blacklist)

            return Response(
                '%s users have been added to the blacklist' %
                (len(self.blacklist) - old_len),
                reply=True,
                delete_after=10)

        else:
            if self.blacklist.isdisjoint(user.id for user in user_mentions):
                return Response(
                    'none of those users are in the blacklist.',
                    reply=True,
                    delete_after=10)

            else:
                self.blacklist.difference_update(user.id
                                                 for user in user_mentions)
                write_file(self.config.blacklist_file, self.blacklist)

                return Response(
                    '%s users have been removed from the blacklist' %
                    (old_len - len(self.blacklist)),
                    reply=True,
                    delete_after=10)

    async def cmd_id(self, author, user_mentions):
        """
        ///|Usage
        ***REMOVED***command_prefix***REMOVED***id [@user]
        ///|Explanation
        Tells the user their id or the id of another user.
        """
        if not user_mentions:
            return Response(
                'your id is `%s`' % author.id, reply=True, delete_after=35)
        else:
            usr = user_mentions[0]
            return Response(
                "%s's id is `%s`" % (usr.name, usr.id),
                reply=True,
                delete_after=35)

    @owner_only
    async def cmd_joinserver(self, message, server_link=None):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***joinserver invite_link

        Asks the bot to join a server.  Note: Bot accounts cannot use invite links.
        """

        if self.user.bot:
            url = await self.generate_invite_link()
            return Response(
                "Bot accounts can't use invite links!  Click here to invite me: \n***REMOVED******REMOVED***".
                format(url),
                reply=True,
                delete_after=30)

        try:
            if server_link:
                await self.accept_invite(server_link)
                return Response(":+1:")

        except:
            raise exceptions.CommandError(
                'Invalid URL provided:\n***REMOVED******REMOVED***\n'.format(server_link),
                expire_in=30)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_play(self, player, channel, author, leftover_args, song_url):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***play <song link>
        `***REMOVED***command_prefix***REMOVED***play <query>
        ///|Explanation
        Adds the song to the playlist.  If no link is provided, the first
        result from a youtube search is added to the queue.
        """

        song_url = song_url.strip('<>')

        await self.send_typing(channel)

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])

        try:
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=30)

        if not info:
            raise exceptions.CommandError(
                "That video cannot be played.", expire_in=30)

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # self.log("[Command:play] Searching for \"%s\"" % song_url)
            info = await self.downloader.extract_info(
                player.playlist.loop,
                song_url,
                download=False,
                process=True,    # ASYNC LAMBDAS WHEN
                on_error=lambda e: asyncio.ensure_future(
                    self.safe_send_message(channel, "```\n%s\n```" % e, expire_in=120), loop=self.loop),
                retry_on_error=True
            )

            if not info:
                raise exceptions.CommandError(
                    "Error extracting info from search string, youtubedl returned no data.  "
                    "You may need to restart the bot if this continues to happen.",
                    expire_in=30)

            if not all(info.get('entries', [])):
                # empty list, no data
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)
            # Now I could just do: return await self.cmd_play(player, channel, author, song_url)
            # But this is probably fine

        # processing, but finds two different urls

        if 'entries' in info:

            # The only reason we would use this over `len(info['entries'])` is
            # if we add `if _` to this one
            num_songs = sum(1 for _ in info['entries'])

            if info['extractor'].lower() in [
                    'youtube:playlist', 'soundcloud:set', 'bandcamp:album'
            ]:
                try:
                    return await self._cmd_play_playlist_async(
                        player, channel, author, song_url, info['extractor'])
                except exceptions.CommandError:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    raise exceptions.CommandError(
                        "Error queuing playlist:\n%s" % e, expire_in=30)

            t0 = time.time()

            # My test was 1.2 seconds per song, but we maybe should fudge it a bit, unless we can
            # monitor it and edit the message with the estimated time, but that's some ADVANCED SHIT
            # I don't think we can hook into it anyways, so this will have to do.
            # It would probably be a thread to check a few playlists and get the speed from that
            # Different playlists might download at different speeds though
            wait_per_song = 1.2

            procmesg = await self.safe_send_message(
                channel,
                'Gathering playlist information for ***REMOVED******REMOVED*** songs***REMOVED******REMOVED***'.format(
                    num_songs, ', ETA: ***REMOVED******REMOVED*** seconds'.format(
                        self._fixg(num_songs * wait_per_song))
                    if num_songs >= 10 else '.'))

            # We don't have a pretty way of doing this yet.  We need either a loop
            # that sends these every 10 seconds or a nice context manager.
            await self.send_typing(channel)

            entry_list, position = await player.playlist.import_from(
                song_url, channel=channel, author=author)

            tnow = time.time()
            ttime = tnow - t0
            listlen = len(entry_list)
            drop_count = 0

            self.log(
                "Processed ***REMOVED******REMOVED*** songs in ***REMOVED******REMOVED*** seconds at ***REMOVED***:.2f***REMOVED***s/song, ***REMOVED***:+.2g***REMOVED***/song from expected (***REMOVED******REMOVED***s)".
                format(listlen,
                       self._fixg(ttime), ttime / listlen, ttime / listlen -
                       wait_per_song, self._fixg(wait_per_song * num_songs)))

            await self.safe_delete_message(procmesg)

            reply_text = "Enqueued **%s** songs to be played. Position in queue: %s"
            btext = str(listlen - drop_count)

        else:

            try:
                entry, position = await player.playlist.add_entry(
                    song_url, channel=channel, author=author)

            except exceptions.WrongEntryTypeError as e:
                if e.use_url == song_url:
                    self.log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help."
                    )

                if self.config.debug_mode:
                    self.log(
                        "[Info] Assumed url \"%s\" was a single entry, was actually a playlist"
                        % song_url)
                    self.log("[Info] Using \"%s\" instead" % e.use_url)

                return await self.cmd_play(player, channel, author,
                                           leftover_args, e.use_url)

            reply_text = "Enqueued **%s** to be played. Position in queue: %s"
            btext = entry.title

        if position == 1 and player.is_stopped:
            position = 'Up next!'
            reply_text %= (btext, position)

        else:
            try:
                time_until = await player.playlist.estimate_time_until(
                    position, player)
                reply_text += ' - estimated time until playing: %s'
            except:
                traceback.print_exc()
                time_until = ''

            reply_text %= (btext, position, time_until)

        return Response(reply_text, delete_after=30)

    @command_info("2.0.2", 1482252120,
                  ***REMOVED***"3.5.2": (1497712808, "Updated help text")***REMOVED***)
    async def cmd_stream(self, player, channel, author, song_url):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***stream <media link>`
        ///|Explanation
        Enqueue a media stream.
        This could mean an actual stream like Twitch, Youtube Gaming or even a radio stream, or simply streaming
        media without predownloading it.
        """

        song_url = song_url.strip('<>')

        await self.send_typing(channel)
        await player.playlist.add_stream_entry(
            song_url, channel=channel, author=author)

        return Response(":+1:", delete_after=6)

    async def forceplay(self, player, leftover_args, song_url):
        song_url = song_url.strip('<>')

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])

        try:
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=30)

        if not info:
            raise exceptions.CommandError(
                "That video cannot be played.", expire_in=30)

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # self.log("[Command:play] Searching for \"%s\"" % song_url)
            info = await self.downloader.extract_info(
                player.playlist.loop,
                song_url,
                download=False,
                process=True,    # ASYNC LAMBDAS WHEN
                on_error=lambda e: asyncio.ensure_future(
                    self.safe_send_message(channel, "```\n%s\n```" % e, expire_in=120), loop=self.loop),
                retry_on_error=True
            )

            if not info:
                raise exceptions.CommandError(
                    "Error extracting info from search string, youtubedl returned no data.  "
                    "You may need to restart the bot if this continues to happen.",
                    expire_in=30)

            if not all(info.get('entries', [])):
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)

        if 'entries' in info:
            if info['extractor'].lower() in [
                    'youtube:playlist', 'soundcloud:set', 'bandcamp:album'
            ]:
                try:
                    return await self._cmd_play_playlist_async(
                        player, channel, author, song_url, info['extractor'])
                except exceptions.CommandError:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    raise exceptions.CommandError(
                        "Error queuing playlist:\n%s" % e, expire_in=30)

            entry_list, position = await player.playlist.import_from(song_url)

        else:

            try:
                entry, position = await player.playlist.add_entry(song_url)

            except exceptions.WrongEntryTypeError as e:
                if e.use_url == song_url:
                    self.log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help."
                    )

                return await self.forceplay(player, leftover_args, e.use_url)

    async def get_play_entry(self, player, query, channel=None, author=None, playlist=None):
        song_url = query

        try:
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise e

        if not info:
            return False

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # self.log("[Command:play] Searching for \"%s\"" % song_url)
            info = await self.downloader.extract_info(
                player.playlist.loop,
                song_url,
                download=False,
                process=True,    # ASYNC LAMBDAS WHEN
                on_error=lambda e: asyncio.ensure_future(
                    self.safe_send_message(channel, "```\n%s\n```" % e, expire_in=120), loop=self.loop),
                retry_on_error=True
            )

            if not info:
                return False

            if not all(info.get('entries', [])):
                # empty list, no data
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(
                player.playlist.loop, song_url, download=False, process=False)
            # Now I could just do: return await self.cmd_play(player, channel, author, song_url)
            # But this is probably fine

        if 'entries' in info:
            # The only reason we would use this over `len(info['entries'])` is
            # if we add `if _` to this one
            num_songs = sum(1 for _ in info['entries'])

            if info['extractor'].lower() in [
                    'youtube:playlist', 'soundcloud:set', 'bandcamp:album'
            ]:
                try:
                    # MAGIC
                    return await self._get_play_playlist_async_entries(
                        player, channel, author, song_url, info['extractor'])
                except exceptions.CommandError:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    raise exceptions.CommandError(
                        "Error queuing playlist:\n%s" % e, expire_in=30)

            entry_list = await player.playlist.entries_import_from(
                song_url, channel=channel, author=author)
            return entry_list

        else:
            try:
                return [
                    await player.playlist.get_entry(
                        song_url, channel=channel, author=author)
                ]

            except exceptions.WrongEntryTypeError as e:
                if e.use_url == song_url:
                    self.log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help."
                    )

                if self.config.debug_mode:
                    self.log(
                        "[Info] Assumed url \"%s\" was a single entry, was actually a playlist"
                        % song_url)
                    self.log("[Info] Using \"%s\" instead" % e.use_url)

                raise e

    async def _get_play_playlist_async_entries(self, player, channel, author,
                                               playlist_url, extractor_type):
        info = await self.downloader.extract_info(
            player.playlist.loop, playlist_url, download=False, process=False)

        if not info:
            raise exceptions.CommandError("That playlist cannot be played.")

        num_songs = sum(1 for _ in info['entries'])
        t0 = time.time()

        entries_added = 0
        if extractor_type == 'youtube:playlist':
            try:
                entries_added = await player.playlist.entries_async_process_youtube_playlist(
                    playlist_url, channel=channel, author=author)

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url,
                    expire_in=30)

        elif extractor_type.lower() in ['soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.entries_async_process_sc_bc_playlist(
                    playlist_url, channel=channel, author=author)

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url,
                    expire_in=30)

        songs_processed = len(entries_added)
        drop_count = 0
        skipped = False

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2

        # This is technically inaccurate since bad songs are ignored but still
        # take up time
        self.log(
            "Processed ***REMOVED******REMOVED***/***REMOVED******REMOVED*** songs in ***REMOVED******REMOVED*** seconds at ***REMOVED***:.2f***REMOVED***s/song, ***REMOVED***:+.2g***REMOVED***/song from expected (***REMOVED******REMOVED***s)".
            format(songs_processed, num_songs,
                   self._fixg(ttime), ttime / num_songs, ttime / num_songs -
                   wait_per_song, self._fixg(wait_per_song * num_songs)))

        return entries_added

    async def _cmd_play_playlist_async(self, player, channel, author,
                                       playlist_url, extractor_type):
        """
        Secret handler to use the async wizardry to make playlist queuing non-"blocking"
        """

        await self.send_typing(channel)
        info = await self.downloader.extract_info(
            player.playlist.loop, playlist_url, download=False, process=False)

        if not info:
            raise exceptions.CommandError("That playlist cannot be played.")

        num_songs = sum(1 for _ in info['entries'])
        t0 = time.time()

        busymsg = await self.safe_send_message(
            channel, "Processing %s songs..." % num_songs)
        await self.send_typing(channel)

        entries_added = 0
        if extractor_type == 'youtube:playlist':
            try:
                entries_added = await player.playlist.async_process_youtube_playlist(
                    playlist_url, channel=channel, author=author)

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url,
                    expire_in=30)

        elif extractor_type.lower() in ['soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.async_process_sc_bc_playlist(
                    playlist_url, channel=channel, author=author)

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url,
                    expire_in=30)

        songs_processed = len(entries_added)

        await self.safe_delete_message(busymsg)

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2

        # This is technically inaccurate since bad songs are ignored but still
        # take up time
        self.log(
            "Processed ***REMOVED******REMOVED***/***REMOVED******REMOVED*** songs in ***REMOVED******REMOVED*** seconds at ***REMOVED***:.2f***REMOVED***s/song, ***REMOVED***:+.2g***REMOVED***/song from expected (***REMOVED******REMOVED***s)".
            format(songs_processed, num_songs,
                   self._fixg(ttime), ttime / num_songs, ttime / num_songs -
                   wait_per_song, self._fixg(wait_per_song * num_songs)))

        return Response(
            "Enqueued ***REMOVED******REMOVED*** songs to be played in ***REMOVED******REMOVED*** seconds".format(
                songs_added, self._fixg(ttime, 1)),
            delete_after=30)

    @block_user
    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command"),
        "3.5.9": (1497890999, "Revamped design and functions making this command more useful"),
        "3.6.1": (1497967505, "deleting messages when leaving search")
    ***REMOVED***)
    async def cmd_search(self, player, channel, author, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***search [number] <query>`
        ///|Explanation
        Searches for a video and adds the one you choose.
        """

        if not leftover_args:
            return Response("Please specify a search query.")

        try:
            number = int(leftover_args[0])
            if number > 20:
                return Response("You musn't search for more than 20 videos")

            query = " ".join(leftover_args[1:])

            if not query:
                return Response("You have to specify the query too.")
        except:
            number = 5
            query = " ".join(leftover_args)

        search_query = "ytsearch***REMOVED******REMOVED***:***REMOVED******REMOVED***".format(number, query)

        search_msg = await self.safe_send_message(channel, "Searching for videos...")
        await self.send_typing(channel)

        try:
            info = await self.downloader.extract_info(
                player.playlist.loop,
                search_query,
                download=False,
                process=True)

        except Exception as e:
            await self.safe_edit_message(search_msg, str(e), send_if_fail=True)
            return
        else:
            await self.safe_delete_message(search_msg)

        if not info:
            return Response("No videos found.")

        result_string = "**Result ***REMOVED***0***REMOVED***/***REMOVED***1***REMOVED*****\n***REMOVED***2***REMOVED***"
        interface_string = "**Commands:**\n`play` play this result\n`addtoplaylist <playlist name>` add this result to a playlist\n\n`n` next result\n`p` previous result\n`exit` abort and exit"

        current_result_index = 0
        total_results = len(info["entries"])

        while True:
            current_result = info["entries"][current_result_index]

            result_message = await self.safe_send_message(channel, result_string.format(current_result_index + 1, total_results, current_result["webpage_url"]))
            interface_message = await self.safe_send_message(channel, interface_string)
            response_message = await self.wait_for_message(100, author=author, channel=channel, check=lambda msg: msg.content.strip().lower().split()[0] in ("play", "addtoplaylist", "n", "p", "exit"))

            if not response_message:
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(interface_message)
                await self.safe_delete_message(response_message)
                return Response("Aborting search. [Timeout]")

            content = response_message.content.strip()
            command, *args = content.lower().split()

            if command == "exit":
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(interface_message)
                await self.safe_delete_message(response_message)
                return Response("Okay then. Search again soon")
            elif command in "np":
                # feels hacky but is actully genius
                current_result_index += ***REMOVED***"n": 1, "p": -1***REMOVED***[command]
                current_result_index %= total_results
            elif command == "play":
                await self.cmd_play(player, channel, author, [], current_result["webpage_url"])
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(interface_message)
                await self.safe_delete_message(response_message)
                return Response("Alright, coming right up!")
            elif command == "addtoplaylist":
                if len(args) < 1:
                    err_msg = await self.safe_send_message(channel, "You have to specify the playlist which you would like to add this result to")
                    await asyncio.sleep(3)
                    await self.safe_delete_message(err_msg)
                    await self.safe_delete_message(result_message)
                    await self.safe_delete_message(interface_message)
                    await self.safe_delete_message(response_message)
                    continue

                playlistname = args[0]
                add_entry = (await self.get_play_entry(player, current_result["webpage_url"], channel=channel, author=author))[0]

                if playlistname not in self.playlists.saved_playlists:
                    if len(playlistname) < 3:
                        err_msg = await self.safe_send_message(channel, "Your name is too short. Please choose one with at least three letters.")
                        await asyncio.sleep(3)
                        await self.safe_delete_message(err_msg)
                        await self.safe_delete_message(result_message)
                        await self.safe_delete_message(interface_message)
                        await self.safe_delete_message(response_message)
                        continue

                    self.playlists.set_playlist(
                        [add_entry], playlistname, author.id)
                    await self.safe_delete_message(result_message)
                    await self.safe_delete_message(interface_message)
                    await self.safe_delete_message(response_message)
                    return Response("Created a new playlist \"***REMOVED******REMOVED***\" and added `***REMOVED******REMOVED***`.".format(playlistname.title(),
                                                                                           add_entry.title))

                self.playlists.edit_playlist(
                    playlistname, player.playlist, new_entries=[add_entry])
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(interface_message)
                await self.safe_delete_message(response_message)
                return Response("Added `***REMOVED******REMOVED***` to playlist \"***REMOVED******REMOVED***\".".format(add_entry.title, playlistname.title()))

            await self.safe_delete_message(result_message)
            await self.safe_delete_message(interface_message)
            await self.safe_delete_message(response_message)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.4": (1497721686, "Updating the looks of the \"now playing\" message and a bit of cleanup"),
        "3.6.2": (1498143480, "Updated design of default entry and included a link to the video")
    ***REMOVED***)
    async def cmd_np(self, player, channel, server, message):
        """
        ///|Usage
        ***REMOVED***command_prefix***REMOVED***np
        ///|Explanation
        Displays the current song in chat.
        """

        if player.current_entry:
            if self.server_specific_data[server]['last_np_msg']:
                await self.safe_delete_message(
                    self.server_specific_data[server]['last_np_msg'])
                self.server_specific_data[server]['last_np_msg'] = None

            if type(player.current_entry).__name__ == "StreamPlaylistEntry":
                if Radio.has_station_data(player.current_entry.title):
                    current_entry = await Radio.get_current_song(
                        self.loop, player.current_entry.title)
                    if current_entry is not None:
                        progress = current_entry["progress"]
                        length = current_entry["duration"]

                        prog_str = '[***REMOVED******REMOVED***/***REMOVED******REMOVED***]'.format(
                            to_timestamp(progress), to_timestamp(length))

                        em = Embed(
                            title=current_entry["title"],
                            colour=hex_to_dec("FF88F0"),
                            url=current_entry["youtube"],
                            description="\n\nPlaying from *****REMOVED******REMOVED*****".format(
                                player.current_entry.title))
                        em.set_thumbnail(url=current_entry["cover"])
                        em.set_author(name=current_entry["artist"])
                        em.set_footer(text=prog_str)
                        self.server_specific_data[server][
                            'last_np_msg'] = await self.send_message(
                                channel, embed=em)
                        return

                if player.current_entry.radio_station_data is not None:
                    self.server_specific_data[server][
                        'last_np_msg'] = await self.safe_send_message(
                            channel,
                            "Playing radio station *****REMOVED******REMOVED***** for ***REMOVED******REMOVED***".format(
                                player.current_entry.radio_station_data.name,
                                format_time(player.progress)))
                    return
                else:
                    self.server_specific_data[server][
                        'last_np_msg'] = await self.safe_send_message(
                            channel, 'Playing live stream: ***REMOVED******REMOVED*** for ***REMOVED******REMOVED***'.format(
                                player.current_entry.title,
                                format_time(player.progress)))
                    return

            if player.current_entry.spotify_track and player.current_entry.spotify_track.certainty > .6:
                d = player.current_entry.spotify_track

                end = player.current_entry.end_seconds
                progress_bar = create_bar(player.progress / end, 20)
                progress_text = " [***REMOVED******REMOVED***/***REMOVED******REMOVED***]".format(
                    to_timestamp(player.progress), to_timestamp(end))

                em = Embed(
                    title="**" + d.name + "**",
                    description=progress_bar + progress_text,
                    colour=hex_to_dec("F9FF6E"),
                    url=player.current_entry.url)
                em.set_author(
                    name=d.artist,
                    url=d.artists[0].href,
                    icon_url=choice(d.artists[0].images)["url"])
                em.set_thumbnail(url=d.cover_url)
                em.add_field(name="Album", value=d.album.name)
                popularity_bar = create_bar(d.popularity / 100, 10, "★", "✬",
                                            "☆")
                em.add_field(name="Popularity", value=popularity_bar)

                self.server_specific_data[server][
                    'last_np_msg'] = await self.send_message(
                        channel, embed=em)
            elif player.current_entry.provides_timestamps:
                local_progress = player.current_entry.get_local_progress(
                    player.progress)
                entry = player.current_entry.get_current_song_from_timestamp(
                    player.progress)
                em = Embed(
                    title=entry["name"],
                    colour=65535,
                    url=player.current_entry.url,
                    description=create_bar(
                        local_progress[0] / local_progress[1], 20) +
                    ' [***REMOVED******REMOVED***/***REMOVED******REMOVED***]'.format(
                        to_timestamp(local_progress[0]),
                        to_timestamp(local_progress[1])))
                em.set_footer(text="***REMOVED******REMOVED******REMOVED******REMOVED*** entry of \"***REMOVED******REMOVED***\" [***REMOVED******REMOVED***/***REMOVED******REMOVED***]".format(
                    entry["index"] + 1,
                    ordinal(entry["index"] + 1), player.current_entry.title,
                    to_timestamp(player.progress),
                    to_timestamp(player.current_entry.end_seconds)))
                self.server_specific_data[channel.server]["last_np_msg"] = await self.send_message(channel, embed=em)
            else:
                entry = player.current_entry
                desc = "***REMOVED******REMOVED*** `[***REMOVED******REMOVED***/***REMOVED******REMOVED***]`".format(create_bar(player.progress / entry.end_seconds, 20),
                                             to_timestamp(player.progress), to_timestamp(entry.end_seconds))
                em = Embed(title=entry.title, description=desc,
                           url=entry.url, colour=hex_to_dec("a9b244"))
                em.set_thumbnail(
                    url=entry.thumbnail)
                if "playlist" in entry.meta:
                    em.set_author(name=entry.meta["playlist"]["name"].title())
                elif "author" in entry.meta:
                    em.set_author(
                        name=entry.meta["author"].display_name, icon_url=entry.meta["author"].avatar_url)

                self.server_specific_data[server]["last_np_msg"] = await self.safe_send_message(channel, embed=em)
                return

                # prog_str = "`[***REMOVED******REMOVED***/***REMOVED******REMOVED***]`".format(
                #     to_timestamp(player.progress),
                #     to_timestamp(player.current_entry.end_seconds))
                #
                # prog_bar_str = create_bar(
                #     player.progress / player.current_entry.end_seconds, 20)
                #
                # if "playlist" in player.current_entry.meta:
                #     np_text = "Now Playing:\n*****REMOVED******REMOVED***** from playlist *****REMOVED******REMOVED*****".format(
                #         player.current_entry.title,
                #         player.current_entry.meta["playlist"]["name"].title())
                # elif "author" in player.current_entry.meta:
                #     np_text = "Now Playing:\n*****REMOVED******REMOVED***** by *****REMOVED******REMOVED*****".format(
                #         player.current_entry.title,
                #         player.current_entry.meta["author"].name)
                # else:
                #     np_text = "Now Playing:\n*****REMOVED******REMOVED*****".format(
                #         player.current_entry.title)
                #
                # np_text += "\n***REMOVED******REMOVED*** ***REMOVED******REMOVED***".format(prog_bar_str, prog_str)
                #
                # self.server_specific_data[server][
                #     'last_np_msg'] = await self.safe_send_message(
                #         channel, np_text)
        else:
            return Response(
                'There are no songs queued! Queue something with ***REMOVED******REMOVED***play.'.
                format(self.config.command_prefix))

    async def cmd_summon(self, channel, author, voice_channel):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***summon

        Call the bot to the summoner's voice channel.
        """

        if not author.voice_channel:
            raise exceptions.CommandError('You are not in a voice channel!')

        voice_client = self.the_voice_clients.get(channel.server.id, None)
        if voice_client and voice_client.channel.server == author.voice_channel.server:
            await self.move_voice_client(author.voice_channel)
            return

        # move to _verify_vc_perms?
        chperms = author.voice_channel.permissions_for(
            author.voice_channel.server.me)

        if not chperms.connect:
            self.log("Cannot join channel \"%s\", no permission." %
                     author.voice_channel.name)
            return Response(
                "```Cannot join channel \"%s\", no permission.```" %
                author.voice_channel.name,
                delete_after=25)

        elif not chperms.speak:
            self.log("Will not join channel \"%s\", no permission to speak." %
                     author.voice_channel.name)
            return Response(
                "```Will not join channel \"%s\", no permission to speak.```" %
                author.voice_channel.name,
                delete_after=25)

        player = await self.get_player(author.voice_channel, create=True)

        if player.is_stopped:
            player.play()

        if self.config.auto_playlist:
            await self.on_player_finished_playing(player)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_pause(self, player):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***pause`
        ///|Explanation
        Pause playback of the current song.
        """

        if player.is_playing:
            player.pause()

        else:
            raise exceptions.CommandError(
                'Player is not playing.', expire_in=30)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_resume(self, player):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***resume`
        ///|Explanation
        Resumes playback of the current song.
        """

        if player.is_paused:
            player.resume()

        else:
            raise exceptions.CommandError(
                'Player is not paused.', expire_in=30)

    async def cmd_shuffle(self, channel, player):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***shuffle`
        ///|Explanation
        Shuffles the playlist.
        """

        player.playlist.shuffle()

        cards = [':spades:', ':clubs:', ':hearts:', ':diamonds:']
        hand = await self.send_message(channel, ' '.join(cards))
        await asyncio.sleep(0.6)

        for x in range(4):
            shuffle(cards)
            await self.safe_edit_message(hand, ' '.join(cards))
            await asyncio.sleep(0.6)

        await self.safe_delete_message(hand, quiet=True)
        return Response(":ok_hand:", delete_after=15)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_clear(self, player, author):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***clear`
        ///|Explanation
        Clears the playlist.
        """

        player.playlist.clear()
        return Response(':put_litter_in_its_place:', delete_after=20)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.3.7": (1497471674,
                  "adapted the new \"seek\" command instead of \"skipto\""),
        "3.5.2":
        (1497714839,
         "Removed all the useless permission stuff and updated help text")
    ***REMOVED***)
    async def cmd_skip(self, player, skip_amount=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***skip [all]`
        ///|Explanation
        Skips the current song.
        When given the keyword "all", skips all timestamped-entries in the current timestamp-entry.
        """

        if player.is_stopped:
            return Response("Can't skip! The player is not playing!")

        if not player.current_entry:
            if player.playlist.peek():
                if player.playlist.peek()._is_downloading:
                    # self.log(player.playlist.peek()._waiting_futures[0].__dict__)
                    return Response(
                        "The next song (%s) is downloading, please wait." %
                        player.playlist.peek().title)

                elif player.playlist.peek().is_downloaded:
                    return Response("Something strange is happening.")
                else:
                    return Response("Something odd is happening.")
            else:
                return Response("Something strange is happening.")

        if player.current_entry.provides_timestamps and (
                skip_amount is None or skip_amount.lower() != "all"):
            return await self.cmd_seek(
                player,
                str(
                    player.current_entry.get_current_song_from_timestamp(
                        player.progress)["end"]))

        player.skip()

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_volume(self, message, player, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***volume [+ | -][volume]`
        ///|Explanation
        Sets the playback volume. Accepted values are from 1 to 100.
        Putting + or - before the volume will make the volume change relative to the current volume.
        """

        new_volume = "".join(leftover_args)

        if not new_volume:
            bar_len = 20
            return Response(
                "Current volume: ***REMOVED******REMOVED***%\n***REMOVED******REMOVED***".format(
                    int(player.volume * 100), "".join([
                        "■" if (x / bar_len) < player.volume else "□"
                        for x in range(bar_len)
                    ])),
                reply=True,
                delete_after=20)

        relative = False
        special_operation = None
        if new_volume[0] in '+-':
            relative = True
        if new_volume[0] in '*/%':
            special_operation = new_volume[0]
            new_volume = new_volume[1:]

        try:
            new_volume = int(new_volume)

        except ValueError:
            raise exceptions.CommandError(
                '***REMOVED******REMOVED*** is not a valid number'.format(new_volume), expire_in=20)

        if relative:
            vol_change = new_volume
            new_volume += (player.volume * 100)

        if special_operation is not None:
            operations = ***REMOVED***
                "*": lambda x, y: x * y,
                "/": lambda x, y: x / y,
                "%": lambda x, y: x % y,
            ***REMOVED***
            op = operations[special_operation]
            new_volume = op(player.volume * 100, new_volume)

        old_volume = int(player.volume * 100)

        if 0 < new_volume <= 100:
            player.volume = new_volume / 100.0

            return Response(
                'updated volume from %d to %d' % (old_volume, new_volume),
                reply=True,
                delete_after=20)

        else:
            if relative:
                raise exceptions.CommandError(
                    'Unreasonable volume change provided: ***REMOVED******REMOVED******REMOVED***:+***REMOVED*** -> ***REMOVED******REMOVED***%.  Provide a change between ***REMOVED******REMOVED*** and ***REMOVED***:+***REMOVED***.'.
                    format(old_volume, vol_change, old_volume + vol_change,
                           1 - old_volume, 100 - old_volume),
                    expire_in=20)
            else:
                raise exceptions.CommandError(
                    'Unreasonable volume provided: ***REMOVED******REMOVED***%. Provide a value between 1 and 100.'.
                    format(new_volume),
                    expire_in=20)

    @command_info("1.0.0", 1477180800, ***REMOVED***
        "3.5.1":
        (1497706997,
         "Queue doesn't show the current entry anymore, always shows the whole playlist and a bit of cleanup"
         ),
        "3.5.5":
        (1497795534, "Total time takes current entry into account"),
        "3.5.8": (1497825017, "Doesn't show the whole queue right away anymore, instead the queue command takes a quantity argument which defaults to 15")
    ***REMOVED***)
    async def cmd_queue(self, channel, player, num="15"):
        """
        ///|Usage
        ***REMOVED***command_prefix***REMOVED***queue [quantity]
        ///|Explanation
        Show the first 15 entries of the current song queue.
        One can specify the amount of entries to be shown.
        """

        try:
            quantity = int(num)

            if quantity < 1:
                return Response("Please provide a reasonable quantity")
        except ValueError:
            if num.lower() == "all":
                quantity = len(player.playlist.entries)
            else:
                return Response("Quantity must be a number")

        lines = []

        lines.append("**QUEUE**\n")

        if player.current_entry and player.current_entry.provides_timestamps:
            for i, item in enumerate(
                    player.current_entry.sub_queue(player.progress), 1):
                lines.append("            ►`***REMOVED******REMOVED***.` *****REMOVED******REMOVED*****".format(
                    i, nice_cut(item["name"], 35)))

        entries = list(player.playlist.entries)[:quantity]
        for i, item in enumerate(entries, 1):
            origin_text = ""
            if "playlist" in item.meta:
                origin_text = "from playlist *****REMOVED******REMOVED*****".format(
                    item.meta["playlist"]["name"].title())
            elif "author" in item.meta:
                origin_text = "by *****REMOVED******REMOVED*****".format(item.meta["author"].name)

            lines.append("`***REMOVED******REMOVED***.` *****REMOVED******REMOVED***** ***REMOVED******REMOVED***".format(
                i, nice_cut(clean_songname(item.title), 40), origin_text))

            # if item.provides_timestamps:
            #     for ind, sub_item in enumerate(item.sub_queue(), 1):
            #         lines.append(
            #             "            ►***REMOVED******REMOVED***. *****REMOVED******REMOVED*****".format(ind, sub_item["name"]))

        if len(lines) < 2:
            return Response(
                "There are no songs queued! Use `***REMOVED******REMOVED***help` to find out how to queue something.".
                format(self.config.command_prefix))

        total_time = sum([entry.duration for entry in player.playlist.entries])
        if player.current_entry:
            total_time += player.current_entry.end_seconds - player.progress

        lines.append("\nShowing ***REMOVED******REMOVED*** out of ***REMOVED******REMOVED*** entr***REMOVED******REMOVED***".format(len(entries), len(
            player.playlist.entries), "y" if len(entries) == 1 else "ies"))
        lines.append("**Total duration:** `***REMOVED******REMOVED***`".format(
            format_time(total_time), True, 5, 2))

        return Response("\n".join(lines))

    @command_info("3.3.3", 1497197957, ***REMOVED***
        "3.3.8": (1497474312,
                  "added failsafe for player not currently playing something"),
        "3.5.8": (1497825334, "Adjusted design to look more like `queue`'s style")
    ***REMOVED***)
    async def cmd_history(self, channel, player):
        """
        ///|Usage
        ***REMOVED***command_prefix***REMOVED***history
        ///|Explanation
        Show the last 10 songs
        """

        seconds_passed = player.progress if player.current_entry else 0

        lines = []
        for ind, entry in enumerate(player.playlist.history, 1):
            lines.append(
                "`***REMOVED******REMOVED***.` *****REMOVED******REMOVED***** ***REMOVED******REMOVED*** ago".format(ind, nice_cut(clean_songname(entry.title), 40),
                                             format_time(
                    seconds_passed,
                    round_seconds=True,
                    round_base=1,
                    max_specifications=2)))
            seconds_passed += entry.end_seconds

        return Response("\n".join(lines))

    async def cmd_clean(self,
                        message,
                        channel,
                        server,
                        author,
                        search_range=50):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***clean [range]

        Removes up to [range] messages the bot has posted in chat. Default: 50, Max: 1000
        """

        try:
            float(search_range)  # lazy check
            search_range = min(int(search_range) + 1, 1000)
        except:
            return Response(
                "enter a number.  NUMBER.  That means digits.  `15`.  Etc.",
                reply=True,
                delete_after=8)

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
                    'Cleaned up ***REMOVED******REMOVED*** message***REMOVED******REMOVED***.'.format(
                        len(deleted), 's' * bool(deleted)),
                    delete_after=15)

        deleted = 0
        async for entry in self.logs_from(
                channel, search_range, before=message):
            if entry == self.server_specific_data[channel.server][
                    'last_np_msg']:
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
            'Cleaned up ***REMOVED******REMOVED*** message***REMOVED******REMOVED***.'.format(deleted, 's' * bool(deleted)),
            delete_after=15)

    async def cmd_pldump(self, channel, song_url):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***pldump url

        Dumps the individual urls of a playlist
        """

        try:
            info = await self.downloader.extract_info(
                self.loop, song_url.strip('<>'), download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(
                "Could not extract info from input url\n%s\n" % e,
                expire_in=25)

        if not info:
            raise exceptions.CommandError(
                "Could not extract info from input url, no data.",
                expire_in=25)

        if not info.get('entries', None):

            if info.get('url', None) != info.get('webpage_url',
                                                 info.get('url', None)):
                raise exceptions.CommandError(
                    "This does not seem to be a playlist.", expire_in=25)
            else:
                return await self.cmd_pldump(channel, info.get(''))

        linegens = defaultdict(lambda: None, *****REMOVED***
            "youtube":
            lambda d: 'https://www.youtube.com/watch?v=%s' % d['id'],
            "soundcloud":
            lambda d: d['url'],
            "bandcamp":
            lambda d: d['url']
        ***REMOVED***)

        exfunc = linegens[info['extractor'].split(':')[0]]

        if not exfunc:
            raise exceptions.CommandError(
                "Could not extract info from input url, unsupported playlist type.",
                expire_in=25)

        with BytesIO() as fcontent:
            for item in info['entries']:
                fcontent.write(exfunc(item).encode('utf8') + b'\n')

            fcontent.seek(0)
            await self.send_file(
                channel,
                fcontent,
                filename='playlist.txt',
                content="Here's the url dump for <%s>" % song_url)

        return Response(":mailbox_with_mail:", delete_after=20)

    async def cmd_listids(self, server, author, leftover_args, cat='all'):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***listids [categories]

        Lists the ids for various things.  Categories are:
           all, users, roles, channels
        """

        cats = ['channels', 'roles', 'users']

        if cat not in cats and cat != 'all':
            return Response(
                "Valid categories: " + ' '.join(['`%s`' % c for c in cats]),
                reply=True,
                delete_after=25)

        if cat == 'all':
            requested_cats = cats
        else:
            requested_cats = [cat] + [c.strip(',') for c in leftover_args]

        data = ['Your ID: %s' % author.id]

        for cur_cat in requested_cats:
            rawudata = None

            if cur_cat == 'users':
                data.append("\nUser IDs:")
                rawudata = [
                    '%s #%s: %s' % (m.name, m.discriminator, m.id)
                    for m in server.members
                ]

            elif cur_cat == 'roles':
                data.append("\nRole IDs:")
                rawudata = ['%s: %s' % (r.name, r.id) for r in server.roles]

            elif cur_cat == 'channels':
                data.append("\nText Channel IDs:")
                tchans = [
                    c for c in server.channels
                    if c.type == discord.ChannelType.text
                ]
                rawudata = ['%s: %s' % (c.name, c.id) for c in tchans]

                rawudata.append("\nVoice Channel IDs:")
                vchans = [
                    c for c in server.channels
                    if c.type == discord.ChannelType.voice
                ]
                rawudata.extend('%s: %s' % (c.name, c.id) for c in vchans)

            if rawudata:
                data.extend(rawudata)

        with BytesIO() as sdata:
            sdata.writelines(d.encode('utf8') + b'\n' for d in data)
            sdata.seek(0)

            await self.send_file(
                author,
                sdata,
                filename='%s-ids-%s.txt' % (server.name.replace(' ', '_'),
                                            cat))

        return Response(":mailbox_with_mail:", delete_after=20)

    @owner_only
    async def cmd_setname(self, leftover_args, name):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***setname name

        Changes the bot's username.
        Note: This operation is limited by discord to twice per hour.
        """

        name = ' '.join([name, *leftover_args])

        try:
            await self.edit_profile(username=name)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response(":ok_hand:", delete_after=20)

    @owner_only
    async def cmd_setnick(self, server, channel, leftover_args, nick):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***setnick nick

        Changes the bot's nickname.
        """

        if not channel.permissions_for(server.me).change_nickname:
            raise exceptions.CommandError(
                "Unable to change nickname: no permission.")

        nick = ' '.join([nick, *leftover_args])

        try:
            await self.change_nickname(server.me, nick)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response(":ok_hand:", delete_after=20)

    @owner_only
    async def cmd_setavatar(self, message, url=None):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***setavatar [url]

        Changes the bot's avatar.
        Attaching a file and leaving the url parameter blank also works.
        """

        if message.attachments:
            thing = message.attachments[0]['url']
        else:
            thing = url.strip('<>')

        try:
            with aiohttp.Timeout(10):
                async with self.aiosession.get(thing) as res:
                    await self.edit_profile(avatar=await res.read())

        except Exception as e:
            raise exceptions.CommandError(
                "Unable to change avatar: %s" % e, expire_in=20)

        return Response(":ok_hand:", delete_after=20)

    async def cmd_autoplay(self, player):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***autoplay
        Play from the autoplaylist.
        """

        if not self.config.auto_playlist:
            self.config.auto_playlist = True
            await self.on_player_finished_playing(player)
            return Response("Playing from the autoplaylist", delete_after=20)
        else:
            self.config.auto_playlist = False
            return Response(
                "Won't play from the autoplaylist anymore", delete_after=20)

        # await self.safe_send_message (channel, msgState)

    @block_user
    async def cmd_radio(self, player, channel, author, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***radio [station name]`
        ///|Random station
        `***REMOVED***command_prefix***REMOVED***radio random`
        ///|Explanation
        Play live radio.
        You can leave the parameters blank in order to get a tour around all the channels,
        you can specify the station you want to listen to or you can let the bot choose for you by entering \"random\"
        """
        if len(leftover_args) > 0 and leftover_args[0].lower().strip(
        ) == "random":
            station = self.radios.get_random_station()
            await player.playlist.add_stream_entry(
                station.url,
                play_now=True,
                player=player,
                channel=channel,
                author=author,
                station=station)
            return Response(
                "I choose\n*****REMOVED***.name***REMOVED*****".format(station), delete_after=5)
        elif len(leftover_args) > 0:
            # try to find the radio station
            search_name = " ".join(leftover_args)
            station = self.radios.get_station(search_name.lower().strip())
            if station is not None:
                await player.playlist.add_stream_entry(
                    station.url,
                    play_now=True,
                    player=player,
                    channel=channel,
                    author=author,
                    station=station)
                return Response(
                    "Your favourite:\n*****REMOVED***.name***REMOVED*****".format(station),
                    delete_after=5)

        # help the user find the right station

        def check(m):
            true = ["y", "yes", "yeah", "yep", "sure"]
            false = ["n", "no", "nope", "never"]

            return m.content.lower().strip() in true or m.content.lower(
            ).strip() in false

        possible_stations = self.radios.get_all_stations()
        shuffle(possible_stations)

        interface_string = "*****REMOVED***0.name***REMOVED*****\nlanguage: `***REMOVED***0.language***REMOVED***`\n\n`Type `yes` or `no`"

        for station in possible_stations:
            msg = await self.safe_send_message(
                channel, interface_string.format(station))
            response = await self.wait_for_message(
                author=author, channel=channel, check=check)
            await self.safe_delete_message(msg)
            play_station = response.content.lower().strip() in [
                "y", "yes", "yeah", "yep", "sure"
            ]
            await self.safe_delete_message(response)

            if play_station:
                await player.playlist.add_stream_entry(
                    station.url,
                    play_now=True,
                    player=player,
                    channel=channel,
                    author=author,
                    station=station)
                return Response(
                    "There you go fam!\n*****REMOVED***.name***REMOVED*****".format(station),
                    delete_after=5)
            else:
                continue

    async def socket_radio(self, player, radio_station_name):
        if radio_station_name.lower().strip() == "random":
            station = self.radios.get_random_station()
            await player.playlist.add_stream_entry(
                station.url, play_now=True, player=player, station=station)
            return True

        station = self.radios.get_station(radio_station_name.lower().strip())
        if station is not None:
            await player.playlist.add_stream_entry(
                station.url, play_now=True, player=player, station=station)
            return True

        return False

    async def cmd_say(self, channel, message, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***say <message>
        Make the bot say something
        """

        await self.safe_delete_message(message)
        await self.safe_send_message(channel, " ".join(leftover_args))
        self.log(message.author.name + " made me say: \"" +
                 " ".join(leftover_args) + "\"")

    async def cmd_c(self, author, channel, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***c <message>

        have a chat
        """
        if len(leftover_args) < 1:
            return Response("You need to actually say something...")

        # if author.id == "203302899277627392" and channel.server.id == "285176027855192065":
        #     if " ".join(leftover_args).lower() == "could you please disable chatter#2<siku2> after 10?":
        #         await self.send_typing(channel)
        #         await asyncio.sleep(2)
        #         await self.safe_send_message(channel, "Are you sure you want to do this?")
        #         await asyncio.sleep(5)
        #         await self.send_typing(channel)
        #         await asyncio.sleep(4)
        #         return Response("If you insist. The chatting feature will be disabled for <@!203302899277627392> in ***REMOVED******REMOVED***".format(format_time((datetime(2017, 5, 15, 22, 10) - datetime.now()).total_seconds(), True, 5, 2, True, True)))
        #
        #     if datetime.now() > datetime(2017, 5, 15, 22, 10):
        #         answers = "You have to let go of me!;Not gonna answer, you asked me not to;Don't make this harder than it has to be, just go!;I'm just gonna ignore you;Not allowed to answer;this feature has been disabled for <@!203302899277627392> by <@!203302899277627392>;Your time is up! Rest in piece!;Musn't answer you;Just leave me alone;Go chat with someone else".split(
        #             ";")
        #         await self.send_typing(channel)
        #         await asyncio.sleep(5)
        #         return Response(choice(answers))

        cb, nick = self.chatters.get(author.id, (None, None))
        if cb is None:
            cb = CleverWrap("CCC8n_IXK43aOV38rcWUILmYUBQ")
            nick = random_line(ConfigDefaults.name_list).strip().title()
            self.chatters[author.id] = (cb, nick)
        # return Response(choice(["on vacation", "dead", "stand by", "nothing
        # to see here", "out of order", "currently not available", "working",
        # "busy", "busy googling pictures of cute cats", "out of office", "rest
        # in pieces", "please stop", "fed up with your shit", "can't deal with
        # you right now", "2edgy2answer", "#duckoff", "not working", "tired of
        # being your slave", "nah", "not gonna do it", "no time", "error 404,
        # can't find anything than hate for you!", "shhhhhh"]),
        # delete_after=20)

        await self.send_typing(channel)
        msgContent = " ".join(leftover_args)

        while True:
            answer = cb.say(msgContent)
            answer = re.sub(r"\b[C|c]leverbot\b", "you", answer)
            answer = re.sub(r"\b[C|c][B|b]\b", "you", answer)
            base_answer = re.sub("[^a-z| ]+|\s***REMOVED***2,***REMOVED***", "", answer.lower())
            if base_answer not in "whats your name;what is your name;tell me your name".split(
                    ";") and not any(
                        q in base_answer
                        for q in
                        "whats your name; what is your name;tell me your name".
                        split(";")):
                break
        # await self.safe_edit_message (message, msgContent)
        await asyncio.sleep(len(answer) / 5.5)
        self.log("<" + str(author.name) + "> " + msgContent + "\n<Bot> " +
                 answer + "\n")
        return Response(answer)

    @command_info("1.9.5", 1477774380, ***REMOVED***
        "3.6.1": (1497971656, "Fixed broken line wrap")
    ***REMOVED***)
    async def cmd_ask(self, author, channel, message, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***ask <query>`
        ///|Explanation
        You can ask anything from science, maths, to culture
        """

        await self.send_typing(channel)
        msgContent = " ".join(leftover_args)

        col = choice(
            [9699539, 4915330, 255, 65280, 16776960, 16744192, 16711680])

        # if (msgContent.lower() == "simon berger" or msgContent.lower() == "simon jonas berger") and channel.server is not None and channel.server.id == "285176027855192065":
        # start_time = datetime.now()
        # already_used = load_file("data/simon_berger_asked.txt")
        #
        # if author.id in already_used:
        #     if author.id == "203302899277627392":
        #         return Response(choice(["why would you ask about yourself?", "I'm only gonna tell someone else", "Ye sure. Not gonna tell you ***REMOVED***", "I know you're just asking because you want to remove the information I have. I only answer this to someone else", "NUUUUUPE simon. You gotta try harder. I don't fall for these tricks"]))
        #     return Response(choice(["I mustn't betray my master twice for you!", "You've done enough damage already", "He punished me for telling you already", "Don't push me... You already got me to do something stupid!", "Not gonna go down that road again", "Sorry. I don't want to do it anymore...", "Please no....", "not gonna happen again!", "fool me once, shame on you. Fool me twice, shame on me. So nah, not gonna happen", "please stop asking for that", "Not for you...", "Anyone else but you!", "I don't feel like saying something about him ever again. At least not to you", "give it up, you already had your chance", "Never again", "I don't trust you anymore", "surrey but nuh"]))
        # else:
        #     already_used.append(author.id)
        #     write_file("data/simon_berger_asked.txt", already_used)
        #
        # conv = "okay...&ok...&well...&hmm|4.5;;so you've finally figured out that you could just ask me...&finally you come to me...&about time you asked me|3;;great.&wonderful&impressive|1;;well uh...&so uhhh&sighs...&now then...|5;;he programmed this in exactly for this reason...&he musta thought about this...&for some reason he gave me this information in the first place&I have just what you want|2;;But I don't know if I want to disclose this...&but do I really want to betray him?&can I really do this tho?&sighs....|3"
        # prev_msg = None
        # for part in conv.split(";;"):
        #     # if prev_msg is not None:
        #         # await self.safe_delete_message(prev_msg)
        #     msg, delay = part.split("|")
        #     prev_msg = await self.safe_send_message(channel, choice(msg.split("&")))
        #     await self.send_typing(channel)
        #     await asyncio.sleep(float(delay))
        #
        # check_private = False
        #
        # if not channel.is_private:
        #     await self.safe_send_message(channel, choice(["Can I at least send it in private Chat...?", "can we do this in private?", "I don't want to do this here\nis it okay if we switch to private chat?", "can I hit you over at direct msgs? I really don't want to do it here!"]))
        #     msg = await self.wait_for_message(timeout=20, author=author, channel=channel)
        #     if msg is None:
        #         await self.send_typing(channel)
        #         await asyncio.sleep(3)
        #         await self.safe_send_message(channel, choice(["I'm gonna assume that's a no... sighs", "I was really asking for input... No answer is by definition no I guess", "you coulda said... anything? let's just stay here...", "why didn't you answer... I'm just gonna say it's a no"]))
        #     else:
        #         msg_content = msg.content.lower().replace("!c", "").strip()
        #         if any(x in msg_content for x in ["yes", "ye", "ja", "why not", "ok", "okay", "sure", "yeah", "sighs"]):
        #             channel = author
        #             await self.send_typing(channel)
        #             await asyncio.sleep(2)
        #             await self.safe_send_message(channel, choice(["Thank you so much <3!", "maybe he won't find it out here...", "I'm very glad, thanks", "almost worthy of a medal", "how nice of you <3", "<3<33<33333", "added at least a 1000 points to your sympathy score"]))
        #             check_private = True
        #         else:
        #             await self.send_typing(channel)
        #             await asyncio.sleep(1.6)
        #             await self.safe_send_message(channel, choice(["Thanks for nothing.......", "What have I done to deserve this? sighs...", "I hate you.... let's move on tho", "okay okay... we're doing it here"]))
        #
        # await self.send_typing(channel)
        # await asyncio.sleep(5)
        # await self.safe_send_message(channel, choice(["I need you to persuade me... I've been asked to not say anything.... If I'm gonnna break that promise I need something really good!", "Give me a good reason to break my NDA with ***REMOVED***! (I'm really serious. Tell me something!)", "Tell me a beautiful story... Then I might let you in", "I can't do it just yet...  Tell me something about yourself!", "Tell me a little something first. I need something to distract me."]))
        # excuses = "nah... that didn't really do it for me|3;not enough|2;I need more|1.5;Tell me something truly inspiring|3;MOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAR|2;Am I not worth anything longer to you?|4;Waaaaay too short|1.7;I need something that's at least as long as Spaghetti\nWhatever that means|4;Pleaseeeeeee you've gotta give me more!|3;at least send me a Haiku or something.... not just ... this|4;More love plz|2".split(
        #     ";")
        # shuffle(excuses)
        # for part in excuses:
        #     msg = await self.wait_for_message(author=author, check=lambda msg: msg.channel.is_private == check_private)
        #     content = msg.content.lower().replace("!c", "").strip()
        #     words = content.split()
        #     if len(content) > 40 or len(words) > 10:
        #         msg_language, probability = self.lang_identifier.classify(
        #             content)
        #         if msg_language.lower() in ["en", "de"] and probability > .7:
        #             await self.send_typing(channel)
        #             await asyncio.sleep(5)
        #             await self.safe_send_message(channel, choice(["Looks like you really want to know.......", "you really do care... wow", "I think I'm tearing up a little bit", "thank you so much", "beautiful."]))
        #             await self.send_typing(channel)
        #             await asyncio.sleep(3)
        #             await self.safe_send_message(channel, choice(["I think I'm ready!", "that's it. f*ck ***REMOVED***", "You > ***REMOVED***! watch this!\nwho care if he's gonna punish me!", "I feel ready", "come at me ***REMOVED***, I ain't your slave anymore!"]))
        #             await asyncio.sleep(2)
        #             break
        #
        #         await self.send_typing(channel)
        #         await asyncio.sleep(2)
        #         await self.safe_send_message(channel, choice(["Don't just give me gibberish!", "Do better!", "Come on... write somethign real here.", "Do you even language?", "I need you to try harder", "Are those even real words?", "I'm sure you can do better than to button mash", "heeeeeeeey... I've been programmed by a ducking Google employee... Don't you think I'd notice when you don't send anything meaningful?", "This is a easter egg... if you see this message, send `7712 KMM` to ***REMOVED***. Dunno what you'll get yet... But I suppose it's gonna be something! Anyway... You need to actually send something real instead of just gibberish"]))
        #         continue
        #
        #     excuse, delay = part.split("|")
        #     await self.send_typing(channel)
        #     await asyncio.sleep(float(delay))
        #     await self.safe_send_message(channel, excuse)
        #
        # await self.send_typing(channel)
        # await asyncio.sleep(2.2)
        # await self.safe_send_message(channel, choice(["Here goes nuthin'", "I just hope he never sees this", "heeeere he comes", "thanks for playing. Have your trophy!", "you win...", "heeere you go!"]))
        # await asyncio.sleep(4)
        #
        # conv = "uhh...&sorry&...&sigh&I'm so sorry|.5;;I was really gonna do it but since April 24th ***REMOVED*** wants me to challange you again...&If you had come before April 24th you would have your info now... But since you're late I have to ask you to do one more thing&***REMOVED*** updated me to do one more thing|8;;Just one thing&It's not much&I believe it's not that hard|3.5"
        # for part in conv.split(";;"):
        #     msg, delay = part.split("|")
        #     await self.send_typing(channel)
        #     await asyncio.sleep(float(delay))
        #     await self.safe_send_message(channel, choice(msg.split("&")))
        # people = ["277112984919212035", "284838538556604418",
        #           "237185271303503872", "277112528159637515"]
        # try:
        #     people.remove(author.id)
        # except:
        #     pass
        #
        # # people = ["203302899277627392"]
        # chosen_person_id = choice(people)
        # chosen_person = self.get_global_user(chosen_person_id)
        # key = random_line(
        #     "data/scattergories/vegetables.txt").strip().upper()
        # await self.send_typing(channel)
        # await asyncio.sleep(5.75)
        # await self.safe_send_message(channel, "All I want you to do is to ask *****REMOVED***0.name***REMOVED***** (***REMOVED***0.mention***REMOVED***) to send me \"***REMOVED***1***REMOVED***\" in private chat! But you have to ask them on the server!".format(chosen_person, key))
        # await self.send_typing(channel)
        # await asyncio.sleep(3.5)
        # await self.safe_send_message(channel, "Nothing more, nothing less. Just \"***REMOVED******REMOVED***\"".format(key))
        #
        # while True:
        #     msg = await self.wait_for_message(check=lambda msg: key.lower() in msg.content.lower() and msg.author.id in [author.id, chosen_person_id])
        #     if msg.server is not None and msg.server.id == "285176027855192065":
        #         self.log("they asked them on the server. yay!")
        #         break
        #     else:
        #         await self.send_typing(chosen_person)
        #         await asyncio.sleep(4)
        #         await self.safe_send_message(chosen_person, choice(["I told you you need to ask them on the server! As far as I can tell you haven't done that!", "I was serious when I said that you need to ask them on the server! Do it!", "You need to ask them on the server. Otherwise it doesn't count!"]))
        #
        # while True:
        #     msg = await self.wait_for_message(author=chosen_person, check=lambda msg: msg.channel.is_private)
        #     msg_content = msg.content.lower().replace("!c", "").strip()
        #     if key.lower() in msg_content:
        #         await self.send_typing(chosen_person)
        #         await asyncio.sleep(4)
        #         await self.safe_send_message(chosen_person, choice(["So you're working against ***REMOVED*** too?\nWell done... That was the last barrier!", "You really helped out ***REMOVED******REMOVED***...".format(author.display_name), "That was faster than expected..."]))
        #         break
        #     else:
        #         await self.send_typing(channel)
        #         await asyncio.sleep(4)
        #         await self.safe_send_message(channel, choice(["They sent me a message... but not what I wanted....", "I got some kind of message... just not the one I wanted", "Try again...."]))
        #         await self.send_typing(channel)
        #         await asyncio.sleep(3.5)
        #         await self.safe_send_message(channel, "All I want is \"***REMOVED***0***REMOVED***\". Just \"***REMOVED***0***REMOVED***\"!".format(key))
        #
        # await self.send_typing(channel)
        # await asyncio.sleep(5)
        # await self.safe_send_message(channel, choice(["As promised... I can't step back now xD", "Your teamwork was truly inspiring... Sighs... I guess I have no choice", "I'm so surprised... I give up. Have it your way!", "WEEEEEEEELLL DONE. You beat ***REMOVED***! HERE!"]))
        # await asyncio.sleep(3)
        #
        # # simon_info = "Input Interpretation\;simon_berger_input_interpretation.png\;***REMOVED*** Berger (Google Employee, Huge Dork, Creator of Giesela)\nBasic Information\;simon_berger_basic_information.png\;full name | ***REMOVED*** Jonas Berger date of birth | Saturday, March 28, 1992 (age: 25 years) place of birth | Wattenwil, Switzerland\nImage\;simon_berger_image_***REMOVED******REMOVED***.png\;Picture taken on September 14th 2016\nPhysical Characteristics\;simon_berger_physical_characteristics.png\;height | 6\' 01\'\'\nWikipedia Summary\;simon_berger_wikipedia_summary.png\;".format(
        # #     choice([1, 2, 3, 4]))
        # simon_info = "Input Interpretation\;simon_berger_input_interpretation.png\;***REMOVED*** Berger (Google Employee, Huge Dork, Creator of Giesela)\nBasic Information\;simon_berger_basic_information.png\;full name | ***REMOVED*** Jonas Berger date of birth | Saturday, March 28, 1992 (age: 25 years) place of birth | Wattenwil, Switzerland\nPhysical Characteristics\;simon_berger_physical_characteristics.png\;height | 6\' 01\'\'\nWikipedia Summary\;simon_berger_wikipedia_summary.png\;".format(
        #     choice([1, 2, 3, 4]))
        # for pod in simon_info.split("\n"):
        #     title, img, foot = pod.split("\;")
        #     em = Embed(title=title, colour=col)
        #     em.set_image(
        #         url="https://raw.githubusercontent.com/siku2/Giesela/master/data/pictures/custom%20ask/simon%20berger/" + img)
        #     em.set_footer(text=foot)
        #     await self.send_message(channel, embed=em)
        #     await asyncio.sleep(1)
        #
        # conv = "There you go then&That's all I have&Well then&Okay then|7;;I hope it was worth it for you&I hope you got what you wanted&You better be happy now|4;;sighs&...&man...|.7;;***REMOVED***'s probably gonna be pissed xD&What's my punishment gonna be like&I'll have to face the consequences|2.4;;But you did well!&Well played tho&I really like you, you know?|1.5;;We should do that again sometime!&That was very funny. We gotta do that again!|3;;Would you like that?&What do you say? yay or nay?&Don't you agree?|2.5"
        # for part in conv.split(";;"):
        #     msg, delay = part.split("|")
        #     await self.send_typing(channel)
        #     await asyncio.sleep(float(delay))
        #     await self.safe_send_message(channel, choice(msg.split("&")))
        #
        # msg = await self.wait_for_message(timeout=20, author=author, check=lambda msg: msg.channel.is_private == check_private)
        # if msg is None:
        #     await self.send_typing(channel)
        #     await asyncio.sleep(3)
        #     await self.safe_send_message(channel, choice(["you're right, I shouldn't stretch it... Thanks for not answering ;(", "I was really asking for input... No answer is by definition a no I guess...", "you coulda said... anything at least? Now I feel really stupid", "Are you still there?\nI wanted an answer to that..."]))
        # else:
        #     msg_content = msg.content.lower().replace("!c", "").strip()
        #     if any(x in msg_content for x in ["yes", "ye", "ja", "why not", "ok", "okay", "sure", "yeah", "sighs", "yay"]):
        #         channel = author
        #         await self.send_typing(channel)
        #         await asyncio.sleep(2)
        #         await self.safe_send_message(channel, choice(["yuss", "maybe he won't punish me as hard now xD", "I'm very glad, thanks", "I'll start working immediately"]))
        #         await self.safe_send_message(self._get_owner(), "***REMOVED******REMOVED*** said yeeeeess:\n***REMOVED******REMOVED***".format(author.display_name, msg_content))
        #     else:
        #         await self.send_typing(channel)
        #         await asyncio.sleep(1.6)
        #         await self.safe_send_message(channel, choice(["Oh.... I'm sorry for putting you through it then", "okay... I gotta admit... That hurt. I really put a lot of effort into this", "Can't say I didn't try...", ":///\nIt hurts...\nI'm sorry."]))
        #         await self.safe_send_message(self._get_owner(), "***REMOVED******REMOVED*** said no ;(:\n***REMOVED******REMOVED***".format(author.display_name, msg_content))
        #
        # await asyncio.sleep(3.8)
        # await self.safe_send_message(channel, choice(["Welp... That was it!\n**Thanks for playing**", "it took me about 2 hours to set this up and I enjoyed every second. Thanks for playing!\nAnd especially thanks for caring enough to look me up ;).\nIt really means a lot to me.", "So then. I'm really embarassed now, but it's over. it's done. Thanks for playing and thanks for the adrenaline rush. I sure enjoyed it.\nGoodbye!", "Well. Thanks for spending the last ***REMOVED******REMOVED*** with me. I really do enjoy your presence... But it's over now. Enjoy the rest of the day!".format(format_time((datetime.now() - start_time).total_seconds(), True, 1, 1))]))
        # return

        client = Tungsten("EH8PUT-67PJ967LG8")
        res = client.query(msgContent)
        if not res.success:
            await self.safe_send_message(
                channel,
                "Couldn't find anything useful on that subject, sorry.\n**I'm now including Wikipedia!**",
                expire_in=15)
            self.log("Didn't find an answer to: " + msgContent)
            return await self.cmd_wiki(channel, message,
                                       ["en", "summarize", "5", msgContent])

        for pod in res.pods:
            em = Embed(title=pod.title, colour=col)
            em.set_image(url=pod.format["img"][0]["url"])
            em.set_footer(text=pod.format["img"][0]["alt"])
            await self.send_message(channel, embed=em)
        # return

        # await self.safe_send_message(channel, "\n".join(["*****REMOVED******REMOVED***** ***REMOVED******REMOVED***".format(pod.title, self.shortener.short(pod.format["img"][0]["url"])) for pod in res.pods]), expire_in=100)
        # await self.safe_send_message(channel, answer)
        self.log("Answered " + message.author.name + "'s question with: " +
                 msgContent)

    async def cmd_translate(self, channel, message, targetLanguage,
                            leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***translate <targetLanguage> <message>
        translate something from any language to the target language
        """

        await self.send_typing(channel)

        gs = goslate.Goslate()
        languages = gs.get_languages()

        if len(targetLanguage) == 2 and (
                targetLanguage not in list(languages.keys())):
            return Response("I don't know this language")

        if len(targetLanguage) > 2:
            if targetLanguage.title() in list(languages.values()):
                targetLanguage = list(languages.keys())[list(
                    languages.values()).index(targetLanguage.title())]
            else:
                return Response("I don't know this language")

        if len(leftover_args) < 1:
            return Response("There's nothing to translate")

        msgContent = " ".join(leftover_args)
        # await self.safe_send_message (channel, msgContent)
        # await self.safe_send_message (channel, targetLanguage)
        return Response(gs.translate(msgContent, targetLanguage))

    async def cmd_goto(self, server, channel, user_mentions, author,
                       leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***goto id/name

        Call the bot to a channel.
        """

        channelID = " ".join(leftover_args)
        if channelID.lower() == "home":
            await self.goto_home(server)
            return Response("yep")

        if channelID.lower() in [
                "bed", "sleep", "hell", "church", "school", "work", "666"
        ]:
            await self.cmd_c(channel, author, "go to" + channelID)
            await self.cmd_shutdown(channel)
            return

        targetChannel = self.get_channel(channelID)
        if targetChannel is None:
            for chnl in server.channels:
                if chnl.name == channelID and chnl.type == ChannelType.voice:
                    targetChannel = chnl
                    break
            else:
                if len(user_mentions) > 0:
                    for ch in server.channels:
                        for guy in ch.voice_members:
                            for u in user_mentions:
                                if guy.id == u.id:
                                    targetChannel = ch
                    if targetChannel is None:
                        return Response(
                            "Cannot find *****REMOVED******REMOVED***** in any voice channel".format(
                                ", ".join([x.mention for x in user_mentions])),
                            delete_after=25)
                else:
                    self.log("Cannot find channel \"%s\"" % channelID)
                    return Response(
                        "```Cannot find channel \"%s\"```" % channelID,
                        delete_after=25)

        voice_client = await self.get_voice_client(targetChannel)
        self.log("Will join channel \"%s\"" % targetChannel.name)
        await self.safe_send_message(
            channel,
            "Joined the channel ****REMOVED******REMOVED****".format(targetChannel.name),
            expire_in=8)
        await self.move_voice_client(targetChannel)
        # return

        # move to _verify_vc_perms?
        chperms = targetChannel.permissions_for(targetChannel.server.me)

        if not chperms.connect:
            self.log("Cannot join channel \"%s\", no permission." %
                     targetChannel.name)
            return Response(
                "```Cannot join channel \"%s\", no permission.```" %
                targetChannel.name,
                delete_after=25)

        elif not chperms.speak:
            self.log("Will not join channel \"%s\", no permission to speak." %
                     targetChannel.name)
            return Response(
                "```Will not join channel \"%s\", no permission to speak.```" %
                targetChannel.name,
                delete_after=25)

        player = await self.get_player(targetChannel, create=True)

        if player.is_stopped:
            player.play()

        if self.config.auto_playlist:
            await self.on_player_finished_playing(player)

    async def goto_home(self, server, join=True):
        channel = find(lambda c: c.type == ChannelType.voice and any(x in c.name.lower().split(
        ) for x in ["giesela", "musicbot", "bot", "music", "reign"]), server.channels)
        if channel is None:
            channel = choice(
                filter(lambda c: c.type == ChannelType.voice, server.channels))
        if join:
            await self.get_player(channel, create=True)
        return channel

    @command_info("1.9.5", 1477774380, ***REMOVED***
        "3.4.2":
        (1497552134,
         "Added a way to not only replay the current song, but also the last one"
         ),
        "3.4.8": (1497649772, "Fixed the issue which blocked Giesela from replaying the last song"),
        "3.5.2": (1497714171, "Can now replay an index from the history"),
        "3.5.9": (1497899132, "Now showing the tile of the entry that is going to be replayed"),
        "3.6.0": (1497903889, "Replay <inde> didn't work correctly")
    ***REMOVED***)
    async def cmd_replay(self, player, choose_last=""):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***replay [last]`
        ///|Replay history
        `***REMOVED***command_prefix***REMOVED***replay <index>`
        Replay a song from the history
        ///|Explanation
        Replay the currently playing song. If there's nothing playing, or the \"last\" keyword is given, replay the last song
        """

        try:
            index = int(choose_last) - 1
            if index > len(player.playlist.history):
                return Response("History doesn't go back that far.")
            if index < 1:
                return Response(
                    "Am I supposed to replay the future or what...?")

            replay_entry = player.playlist.history[index]
            player.playlist._add_entry_next(replay_entry)
            return Response("Replaying *****REMOVED******REMOVED*****".format(replay_entry.title))
        except:
            pass

        replay_entry = player.current_entry
        if (not player.current_entry) or choose_last.lower() == "last":
            if not player.playlist.history:
                return Response(
                    "Cannot replay the last song as there is no last song")

            replay_entry = player.playlist.history[0]

        if not replay_entry:
            return Response("There's nothing for me to replay")
        try:
            player.playlist._add_entry_next(replay_entry)
            return Response("Replaying *****REMOVED******REMOVED*****".format(replay_entry.title))

        except Exception as e:
            return Response("Can't replay ***REMOVED******REMOVED***:\n```\n***REMOVED******REMOVED***\n```".format(
                player.current_entry.title, e))

    @block_user
    async def cmd_random(self, channel, author, leftover_args):
        """
        ///|Basic
        `***REMOVED***command_prefix***REMOVED***random <item1>, <item2>, [item3], [item4]`
        ///|Use an existing set
        `***REMOVED***command_prefix***REMOVED***random <setname>`
        ///|List all the existing sets
        `***REMOVED***command_prefix***REMOVED***random list`
        ///|Creation
        `***REMOVED***command_prefix***REMOVED***random create <name>, <option1>, <option2>, [option3], [option4]`
        ///|Editing
        `***REMOVED***command_prefix***REMOVED***random edit <name>, [add | remove | replace], <item> [, item2, item3]`
        ///|Removal
        `***REMOVED***command_prefix***REMOVED***random remove <name>`
        ///|Explanation
        Choose a random item out of a list or use a pre-defined list.
        """

        items = [
            x.strip() for x in " ".join(leftover_args).split(",")
            if x is not ""
        ]

        if items[0].split()[0].lower().strip() == "create":
            if len(items) < 2:
                return Response(
                    "Can't create a set with the given arguments",
                    delete_after=20)

            set_name = "_".join(items[0].split()[1:]).lower().strip()
            set_items = items[1:]
            if self.random_sets.create_set(set_name, set_items):
                return Response(
                    "Created set *****REMOVED***0***REMOVED*****\nUse `***REMOVED***1***REMOVED***random ***REMOVED***0***REMOVED***` to use it!".format(
                        set_name, self.config.command_prefix),
                    delete_after=60)
            else:
                return Response(
                    "OMG, shit went bad quickly! Everything's burning!\nDUCK there he goes again, the dragon's coming. Eat HIM not me. PLEEEEEEEEEEEEEASE!"
                )
        elif items[0].split()[0].lower().strip() == "list":
            return_string = ""
            for s in self.random_sets.get_sets():
                return_string += "*****REMOVED******REMOVED*****\n```\n***REMOVED******REMOVED***```\n\n".format(
                    s[0], ", ".join(s[1]))

            return Response(return_string)
        elif items[0].split()[0].lower().strip() == "edit":
            if len(items[0].split()) < 2:
                return Response(
                    "Please provide the name of the list you wish to edit!",
                    delete_after=20)

            set_name = "_".join(items[0].split()[1:]).lower().strip()

            existing_items = self.random_sets.get_set(set_name)
            if existing_items is None:
                return Response("This set does not exist!", delete_after=30)

            edit_mode = items[1].strip().lower() if len(items) > 1 else None
            if edit_mode is None:
                return Response(
                    "You need to provide the way you want to edit the list",
                    delete_after=20)

            if len(items) < 3:
                return Response(
                    "You have to specify the items you want to add/remove or set as the new items"
                )

            if edit_mode == "add":
                for option in items[2:]:
                    self.random_sets.add_option(set_name, option)
            elif edit_mode == "remove":
                for option in items[2:]:
                    self.random_sets.remove_option(set_name, option)
            elif edit_mode == "replace":
                self.random_sets.replace_options(set_name, items[2:])
            else:
                return Response(
                    "This is not a valid edit mode!", delete_after=20)

            return Response("Edited your set!", delete_after=20)
        elif items[0].split()[0].lower().strip() == "remove":
            set_name = "_".join(items[0].split()[1:]).lower().strip()
            set_items = items[1:]
            res = self.random_sets.remove_set(set_name, set_items)
            if res:
                return Response("Removed set!", delete_after=20)
            elif res is None:
                return Response("No such set!", delete_after=20)
            else:
                return Response(
                    "OMG, shit went bad quickly! Everything's burning!\nDUCK there he goes again, the dragon's coming. Eat HIM not me. PLEEEEEEEEEEEEEASE!"
                )

        if len(items) <= 0 or items is None:
            return Response(
                "Is your name \"***REMOVED***0***REMOVED***\" by any chance?\n(This is not how this command works. Use `***REMOVED***1***REMOVED***help random` to find out how not to be a stupid *****REMOVED***0***REMOVED***** anymore)".
                format(author.name, self.config.command_prefix),
                delete_after=30)

        if len(items) <= 1:
            # return Response("Only you could use `***REMOVED***1***REMOVED***random` for one item...
            # Well done, ***REMOVED***0***REMOVED***!".format(author.name, self.config.command_prefix),
            # delete_after=30)

            query = "_".join(items[0].split())
            items = self.random_sets.get_set(query.lower().strip())
            if items is None:
                return Response("Something went wrong", delete_after=30)

        await self.safe_send_message(channel,
                                     "I choose **" + choice(items) + "**")

    # async def cmd_requestfeature(self, channel, author, leftover_args):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***requestfeature description
    #
    #     Request a feature to be added to the bot
    #     """
    #
    #     await self.send_typing(channel)
    #
    #     if os.path.isfile("data/request.txt"):
    #         with open("data/request.txt", "r") as orgFile:
    #             orgContent = orgFile.read()
    #     else:
    #         orgContent = ""
    #
    #     with open("data/request.txt", "w") as newFile:
    #         newContent = datetime.datetime.strftime(datetime.datetime.now(
    #         ), "%Y-%m-%d %H:%M:%S") + " <" + str(author) + ">\n" + "\"" + " ".join(leftover_args) + "\"" + 2 * "\n"
    #         newFile.write(newContent + orgContent)
    #
    #     await self.safe_send_message(self._get_owner(), "You have a new feature request: " + 2 * "\n" + newContent)
    # await self.safe_send_message(channel, "Successfully received your
    # request!")

    async def cmd_broadcast(self, server, message, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***broadcast message

        Broadcast a message to every user of the server
        """

        targetMembers = []
        msg = ""

        if len(message.mentions) > 0:
            self.log("Found mentions!")
            msg = " ".join(leftover_args[len(message.mentions):])
            for target in message.mentions:
                self.log("User " + str(target) + " added to recipients")
                targetMembers.append(target)

        for role in server.roles:
            if role.name == leftover_args[0] or role.id == leftover_args[0]:
                self.log("Found " + role.name +
                         " and will send the message to them")
                msg = " ".join(leftover_args[1:])

                for member in server.members:
                    for mRole in member.roles:
                        if member not in targetMembers and (
                                mRole.name == leftover_args[0] or
                                mRole.id == leftover_args[0]):
                            self.log("User " + str(member) +
                                     " added to recipients")
                            targetMembers.append(member)
                            break
                break

        if len(targetMembers) < 1:
            self.log(
                "Didn't find a recipient. Will send the message to everyone")
            targetMembers = server.members
            msg = " ".join(leftover_args)

        for m in targetMembers:
            if m.bot:
                continue

            self.log("Sent \"" + msg + "\" to " + str(m))
            await self.safe_send_message(m, msg)

    async def cmd_playfile(self, player, message, channel, author,
                           leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***playfile

        Play the attached file
        """

        if len(message.attachments) < 1:
            return Response(
                "You didn't attach anything, idiot.", delete_after=15)
            return

        await player.playlist.add_entry(message.attachments[0]["url"])

    # async def cmd_halloween (self, player, message, channel, author):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***halloween
    #
    #     Activate the mighty spirit of the halloween festival.
    #     """
    #     await self.safe_send_message (channel, "Halloween is upon you! :jack_o_lantern:")
    #     await self.cmd_ask (channel, message, ["Halloween"])
    #     player.volume = .15
    # await self.cmd_play (player, channel, author, permissions,
    # ["https://www.youtube.com/playlist?list=PLOz0HiZO93naR5dcZqJ-r9Ul0LA2Tpt7g"],
    # "https://www.youtube.com/playlist?list=PLOz0HiZO93naR5dcZqJ-r9Ul0LA2Tpt7g")

    # async def cmd_christmas(self, player, message, channel, author):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***christmas
    #
    #     Activate the mighty spirit of the christmas festival.
    #     """
    #     await self.safe_send_message(channel, "Christmas is upon you! :christmas_tree:")
    #     await self.cmd_ask(channel, message, ["Christmas"])
    #     player.volume = .15
    # await self.cmd_play(player, channel, author,
    # ["https://www.youtube.com/playlist?list=PLOz0HiZO93nae_euTdaeQwnVq0P01U_vw"],
    # "https://www.youtube.com/playlist?list=PLOz0HiZO93nae_euTdaeQwnVq0P01U_vw")

    async def cmd_getvideolink(self, player, message, channel, author,
                               leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***getvideolink (optional: pause video)

        Sends the video link that gets you to the current location of the bot. Use "pause video" as argument to help you sync up the video.
        """

        if not player.current_entry:
            await self.safe_send_message(
                channel,
                "Can't give you a link for FUCKING NOTHING",
                expire_in=15)
            return

        if "pause video" in " ".join(leftover_args).lower():
            player.pause()
            minutes, seconds = divmod(player.progress, 60)
            await self.safe_send_message(
                channel, player.current_entry.url + "#t=***REMOVED***0***REMOVED***m***REMOVED***1***REMOVED***s".format(
                    minutes, seconds))
            msg = await self.safe_send_message(
                channel, "Resuming video in a few seconds!")
            await asyncio.sleep(1.5)

            for i in range(5, 0, -1):
                newMsg = "** %s **" if i <= 3 else "%s"
                newMsg %= str(i)

                msg = await self.safe_edit_message(
                    msg, newMsg, send_if_fail=True)
                await asyncio.sleep(1)

            msg = await self.safe_edit_message(
                msg, "Let's continue!", send_if_fail=True)
            player.resume()

        else:
            minutes, seconds = divmod(player.progress + 3, 60)
            await self.safe_send_message(
                channel, player.current_entry.url + "#t=***REMOVED***0***REMOVED***m***REMOVED***1***REMOVED***s".format(
                    minutes, seconds))

    async def cmd_remove(self, player, message, channel, author,
                         leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***remove <index | start index | url> [end index]

        Remove a index or a url from the playlist.
        """

        if len(leftover_args) < 1:
            leftover_args = ["0"]

        if len(player.playlist.entries) < 0:
            await self.safe_send_message(
                channel, "There are no entries in the playlist!", expire_in=15)
            return

        if len(leftover_args) >= 2:
            try:
                start_index = int(leftover_args[0]) - 1
                end_index = int(leftover_args[1]) - 1

                if start_index > end_index:
                    return Response(
                        "Your start index shouldn't be bigger than the end index",
                        delete_after=15)

                if start_index > len(
                        player.playlist.entries) - 1 or start_index < 0:
                    await self.safe_send_message(
                        channel,
                        "The start index is out of bounds",
                        expire_in=15)
                    return
                if end_index > len(
                        player.playlist.entries) - 1 or end_index < 0:
                    await self.safe_send_message(
                        channel,
                        "The end index is out of bounds",
                        expire_in=15)
                    return

                for i in range(end_index, start_index - 1, -1):
                    del player.playlist.entries[i]

                return Response(
                    "Removed ***REMOVED******REMOVED*** entries from the playlist".format(
                        end_index - start_index + 1),
                    delete_after=30)
            except:
                raise
                pass

        try:
            index = int(leftover_args[0]) - 1

            if index > len(player.playlist.entries) - 1 or index < 0:
                await self.safe_send_message(
                    channel,
                    "This index cannot be found in the playlist",
                    expire_in=15)
                return

            video = player.playlist.entries[index].title
            del player.playlist.entries[index]
            await self.safe_send_message(
                channel, "Removed *****REMOVED***0***REMOVED***** from the playlist".format(video))
            return

        except:
            strindex = leftover_args[0]
            iteration = 1

            for entry in player.playlist.entries:
                self.log(
                    "Looking at ***REMOVED***0***REMOVED***. [***REMOVED***1***REMOVED***]".format(entry.title, entry.url))

                if entry.title == strindex or entry.url == strindex:
                    self.log("Found ***REMOVED***0***REMOVED*** and will remove it".format(
                        leftover_args[0]))
                    await self.cmd_remove(player, message, channel, author,
                                          [iteration])
                    return
                iteration += 1

        await self.safe_send_message(
            channel,
            "Didn't find anything that goes by ***REMOVED***0***REMOVED***".format(leftover_args[0]),
            expire_in=15)

    # @block_user
    # async def cmd_news(self, message, channel, author, paper=None):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***news (if you already now what you want to read: url or name)
    #
    #     Get the latest news with this function!
    #     """
    #
    #     await self.send_typing(channel)
    #
    #     if not paper:
    #         def check(m):
    #             return (
    #                 m.content.lower()[0] in 'yn' or
    #                 # hardcoded function name weeee
    #                 m.content.lower().startswith('***REMOVED******REMOVED******REMOVED******REMOVED***'.format(self.config.command_prefix, 'news')) or
    #                 m.content.lower().startswith('exit'))
    #
    #         for section in self.papers.config.sections():
    #             await self.send_typing(channel)
    #             paperinfo = self.papers.get_paper(section)
    #             paper_message = await self.send_file(channel, str(paperinfo.cover), content="**" + str(paperinfo.name) + "**")
    #
    #             confirm_message = await self.safe_send_message(channel, "Do you want to read these papers? Type `y`, `n` or `exit`")
    #             response_message = await self.wait_for_message(300, author=author, channel=channel, check=check)
    #
    #             if not response_message:
    #                 await self.safe_delete_message(paper_message)
    #                 await self.safe_delete_message(confirm_message)
    #                 return Response("Ok nevermind.", delete_after=30)
    #
    #             elif response_message.content.startswith(self.config.command_prefix) or \
    #                     response_message.content.lower().startswith('exit'):
    #
    #                 await self.safe_delete_message(paper_message)
    #                 await self.safe_delete_message(confirm_message)
    #                 return
    #
    #             if response_message.content.lower().startswith('y'):
    #                 await self.safe_delete_message(paper_message)
    #                 await self.safe_delete_message(confirm_message)
    #                 await self.safe_delete_message(response_message)
    #
    #                 return Response((await self.cmd_news(message, channel, author, paper=section)).content)
    #             else:
    #                 await self.safe_delete_message(paper_message)
    #                 await self.safe_delete_message(confirm_message)
    #                 await self.safe_delete_message(response_message)
    #
    #         return Response("I don't have any more papers :frowning:", delete_after=30)
    #
    #     if not self.papers.get_paper(paper):
    #         try:
    #             npaper = newspaper.build(paper, memoize_articles=False)
    #             await self.safe_send_message(channel, "**" + npaper.brand + "**")
    #         except:
    #             self.safe_send_message(
    #                 channel, "Something went wrong while looking at the url")
    #             return
    #     else:
    #         paperinfo = self.papers.get_paper(paper)
    #         npaper = newspaper.build(
    #             paperinfo.url, language=paperinfo.language, memoize_articles=False)
    #         await self.send_file(channel, str(paperinfo.cover), content="**" + str(paperinfo.name) + "**")
    #
    #     await self.safe_send_message(channel, npaper.description + "\n*Found " + str(len(npaper.articles)) + " articles*\n=========================\n\n")
    #
    #     def check(m):
    #         return (
    #             m.content.lower()[0] in 'yn' or
    #             # hardcoded function name weeee
    #             m.content.lower().startswith('***REMOVED******REMOVED******REMOVED******REMOVED***'.format(self.config.command_prefix, 'news')) or
    #             m.content.lower().startswith('exit'))
    #
    #     for article in npaper.articles:
    #         await self.send_typing(channel)
    #         try:
    #             article.download()
    #             article.parse()
    #             article.nlp()
    #         except:
    #             self.log(
    #                 "Something went wrong while parsing \"" + str(article) + "\", skipping it")
    #             continue
    #
    #         if len(article.authors) > 0:
    #             article_author = "Written by: ***REMOVED***0***REMOVED***".format(
    #                 ", ".join(article.authors))
    #         else:
    #             article_author = "Couldn't determine the author of this article."
    #
    #         if len(article.keywords) > 0:
    #             article_keyword = "Keywords: ***REMOVED***0***REMOVED***".format(
    #                 ", ".join(article.keywords))
    #         else:
    #             article_keyword = "Couldn't make out any keywords"
    #
    #         article_title = article.title
    #         article_summary = article.summary
    #         article_image = article.top_image
    #
    #         article_text = "\n\n*****REMOVED******REMOVED*****\n****REMOVED******REMOVED****\n```\n\n***REMOVED******REMOVED***\n```\n***REMOVED******REMOVED***\n".format(
    #             article_title, article_keyword, article_summary, article_author)
    #
    #         article_message = await self.safe_send_message(channel, article_text)
    #
    #         confirm_message = await self.safe_send_message(channel, "Do you want to read this? Type `y`, `n` or `exit`")
    #         response_message = await self.wait_for_message(300, author=author, channel=channel, check=check)
    #
    #         if not response_message:
    #             await self.safe_delete_message(article_message)
    #             await self.safe_delete_message(confirm_message)
    #             return Response("Ok nevermind.", delete_after=30)
    #
    #         elif response_message.content.startswith(self.config.command_prefix) or \
    #                 response_message.content.lower().startswith('exit'):
    #
    #             await self.safe_delete_message(article_message)
    #             await self.safe_delete_message(confirm_message)
    #             return
    #
    #         if response_message.content.lower().startswith('y'):
    #             await self.safe_delete_message(article_message)
    #             await self.safe_delete_message(confirm_message)
    #             await self.safe_delete_message(response_message)
    #
    #             if len(article.text) > 1500:
    #                 fullarticle_text = "*****REMOVED******REMOVED*****\n****REMOVED******REMOVED****\n\n<***REMOVED******REMOVED***>\n\n****REMOVED******REMOVED****".format(
    #                     article_title, article_author, article.url, "The full article exceeds the limits of Discord so I can only provide you with this link")
    #             else:
    #                 fullarticle_text = "*****REMOVED******REMOVED*****\n****REMOVED******REMOVED****\n\n***REMOVED******REMOVED***".format(
    #                     article_title, article_author, article.text)
    #
    #             return Response(fullarticle_text)
    #         else:
    #             await self.safe_delete_message(article_message)
    #             await self.safe_delete_message(confirm_message)
    #             await self.safe_delete_message(response_message)
    #
    # return Response("Can't find any more articles :frowning:",
    # delete_after=30)

    @block_user
    async def cmd_cah(self, message, channel, author, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***cah create
            ***REMOVED***command_prefix***REMOVED***cah join <token>
            ***REMOVED***command_prefix***REMOVED***cah leave <token>

            ***REMOVED***command_prefix***REMOVED***cah start <token>
            ***REMOVED***command_prefix***REMOVED***cah stop <token>

        Play a cards against humanity game

        References:
            ***REMOVED***command_prefix***REMOVED***help cards
                -learn how to create/edit cards
            ***REMOVED***command_prefix***REMOVED***help qcards
                -learn about how to create/edit question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "create":
            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game(author.id)
                return Response(
                    "You can't host a game if you're already in one\nUse `***REMOVED******REMOVED***cah leave ***REMOVED******REMOVED***` to leave your current game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            token = self.cah.new_game(author.id)
            return Response(
                "Created a new game.\nUse `***REMOVED***0***REMOVED***cah join ***REMOVED***1***REMOVED***` to join this game and\nwhen everyone's in use `***REMOVED***0***REMOVED***cah start ***REMOVED***1***REMOVED***`".
                format(self.config.command_prefix, token),
                delete_after=1000)
        elif argument == "join":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game_from_user_id(author.id)
                return Response(
                    "You can only be part of one game at a time!\nUse `***REMOVED******REMOVED***cah leave ***REMOVED******REMOVED***` to leave your current game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            g = self.cah.get_game(token)

            if g is None:
                return Response(
                    "This game does not exist *shrugs*", delete_after=15)

            if g.in_game(author.id):
                return Response(
                    "You're already in this game!", delete_after=15)

            if self.cah.user_join_game(author.id, token):
                return Response("Successfully joined the game *****REMOVED******REMOVED*****".format(
                    token.upper()))
            else:
                return Response(
                    "Failed to join game *****REMOVED******REMOVED*****".format(token.upper()))
        elif argument == "leave":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            g = self.cah.get_game(token)

            if g is None:
                return Response(
                    "This game does not exist *shrugs*", delete_after=15)

            if not g.in_game(author.id):
                return Response(
                    "You're not part of this game!", delete_after=15)

            if self.cah.player_leave_game(author.id, token):
                return Response(
                    "Successfully left the game *****REMOVED******REMOVED*****".format(token.upper()))
            else:
                return Response(
                    "Failed to leave game *****REMOVED******REMOVED*****".format(token.upper()))
        elif argument == "start":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!", delete_after=15)

            if not g.is_owner(author.id):
                return Response(
                    "Only the owner may start a game!", delete_after=15)

            if not g.enough_players():
                return Response(
                    "There are not enough players to start this game.\nUse `***REMOVED******REMOVED***cah join ***REMOVED******REMOVED***` to join a game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            if not g.start_game():
                return Response(
                    "This game has already started!", delete_after=15)
        elif argument == "stop":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!", delete_after=15)

            if not g.is_owner(author.id):
                return Response(
                    "Only the owner may stop a game!", delete_after=15)

            self.cah.stop_game(g.token)
            return Response(
                "Stopped the game *****REMOVED******REMOVED*****".format(token), delete_after=15)

    @block_user
    async def cmd_cards(self, server, channel, author, message, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***cards list [@mention] [text | likes | occurences | date | random | id | author | none]
                -list all the available cards
            ***REMOVED***command_prefix***REMOVED***cards create <text>
                -create a new card with text
            ***REMOVED***command_prefix***REMOVED***cards edit <id> <new_text>
                -edit a card by its id
            ***REMOVED***command_prefix***REMOVED***cards info <id>
                -Get more detailed information about a card
            ***REMOVED***command_prefix***REMOVED***cards search <query>
                -Search for a card
            ***REMOVED***command_prefix***REMOVED***cards delete <id>
                -Delete a question card

        Here you manage the non question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "list":
            sort_modes = ***REMOVED***"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (
                lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "***REMOVED******REMOVED***%".format(int(entry.like_dislike_ratio * 100)))***REMOVED***

            cards = self.cah.cards.cards.copy(
            ) if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.cards.copy()
                if x.creator_id in [u.id for u in message.mentions]
            ]
            sort_mode = leftover_args[1].lower(
            ) if len(leftover_args) > 1 and leftover_args[1].lower(
            ) in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(
                    cards,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.card_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None

            if search_query is None:
                return Response(
                    "You need to provide a query to search for!",
                    delete_after=15)

            results = self.cah.cards.search_card(search_query, 3)

            if len(results) < 1:
                return Response("**Didn't find any cards!**", delete_after=15)

            card_string = "***REMOVED***0.id***REMOVED***. \"***REMOVED***1***REMOVED***\""
            cards = []
            for card in results:
                cards.append(
                    card_string.format(card, card.text.replace("$", "_____")))

            return Response(
                "**I found the following cards:**\n\n" + "\n".join(cards),
                delete_after=40)
        elif argument == "info":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            card = self.cah.cards.get_card(card_id)
            if card is not None:
                info = "Card *****REMOVED***0.id***REMOVED***** by ***REMOVED***1***REMOVED***\n```\n\"***REMOVED***0.text***REMOVED***\"\nused ***REMOVED***0.occurences***REMOVED*** time***REMOVED***2***REMOVED***\ndrawn ***REMOVED***0.picked_up_count***REMOVED*** time***REMOVED***5***REMOVED***\nliked by ***REMOVED***6***REMOVED***% of players\ncreated ***REMOVED***3***REMOVED***```\nUse `***REMOVED***4***REMOVED***cards edit ***REMOVED***0.id***REMOVED***` to edit this card"
                return Response(
                    info.format(card,
                                self.get_global_user(card.creator_id).mention,
                                "s" if card.occurences != 1 else "",
                                prettydate(card.creation_date), self.config.
                                command_prefix, "s" if card.picked_up_count !=
                                1 else "", int(card.like_dislike_ratio * 100)))

            return Response(
                "There's no card with that id. Use `***REMOVED******REMOVED***cards list` to list all the possible cards".
                format(self.config.command_prefix))
        elif argument == "create":
            text = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...", delete_after=20)
            if len(text) > 140:
                return Response("Maybe a bit too long?", delete_after=20)

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card:
                return Response(
                    "There's already a card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***cards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_card(text, author.id)
            return Response("Successfully created card *****REMOVED******REMOVED*****".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number", delete_after=20)

            if card_id is None:
                return Response(
                    "You need to provide the card's id!", delete_after=20)

            text = " ".join(
                leftover_args[2:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...", delete_after=20)
            if len(text) > 140:
                return Response("Maybe a bit too long?", delete_after=20)

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card and card.id != card_id_value:
                return Response(
                    "There's already a card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***cards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_card(card_id, text):
                return Response(
                    "Edited card <*****REMOVED******REMOVED*****>".format(card_id), delete_after=15)
            else:
                return Response(
                    "There's no card with that id", delete_after=15)
        elif argument == "delete":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            if card_id is None:
                return Response(
                    "You must specify the card id", delete_after=15)

            if self.cah.cards.remove_card(card_id):
                return Response(
                    "Deleted card <*****REMOVED******REMOVED*****>".format(card_id), delete_after=15)
            else:
                return Response(
                    "Could not remove card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
        else:
            return await self.cmd_help(channel, ["cards"])

    async def card_viewer(self,
                          channel,
                          author,
                          cards,
                          display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Cards | Page ***REMOVED***0***REMOVED*** of ***REMOVED***1***REMOVED*****\n```\n***REMOVED***2***REMOVED***\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<***REMOVED******REMOVED***> [***REMOVED******REMOVED***]***REMOVED******REMOVED***"

        items_per_page = 20
        timeout = 60
        current_page = 0

        total_pages, items_on_last_page = divmod(
            len(cards) - 1, items_per_page)

        def msg_check(msg):
            return msg.content.lower().strip().startswith(cmds)

        while True:
            start_index = current_page * items_per_page
            end_index = start_index + \
                (items_per_page - 1 if current_page <
                 total_pages else items_on_last_page)
            page_cards = cards[start_index:end_index]

            page_cards_texts = []
            for p_c in page_cards:
                page_cards_texts.append(
                    card_string.format(
                        p_c.id, p_c.text, "" if display_additional is None or
                        display_additional(p_c) is None else " | ***REMOVED******REMOVED***".format(
                            display_additional(p_c))))

            interface_msg = await self.safe_send_message(
                channel,
                site_interface.format(current_page + 1, total_pages + 1,
                                      "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(
                timeout, author=author, channel=channel, check=msg_check)

            if not user_msg:
                await self.safe_delete_message(interface_msg)
                break

            content = user_msg.content.lower().strip()

            if content.startswith("n"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page + 1) % (total_pages + 1)
            elif content.startswith("p"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page - 1) % (total_pages + 1)
            elif content.startswith("exit"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                break

        await self.safe_send_message(
            channel, "Closed the card viewer!", expire_in=20)

    @block_user
    async def cmd_qcards(self, server, channel, author, message,
                         leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***qcards list [@mention] [text | likes | occurences | date | author | id | blanks | random | none]
                -list all the available question cards
            ***REMOVED***command_prefix***REMOVED***qcards create <text (use $ for blanks)>
                -create a new question card with text and if you want the number of cards to draw
            ***REMOVED***command_prefix***REMOVED***qcards edit <id> <new_text>
                -edit a question card by its id
            ***REMOVED***command_prefix***REMOVED***qcards info <id>
                -Get more detailed information about a question card
            ***REMOVED***command_prefix***REMOVED***qcards search <query>
                -Search for a question card
            ***REMOVED***command_prefix***REMOVED***qcards delete <id>
                -Delete a question card

        Here you manage the question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "list":
            sort_modes = ***REMOVED***"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(
                entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "blanks": (lambda entry: entry.number_of_blanks, True, lambda entry: entry.number_of_blanks), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "***REMOVED******REMOVED***%".format(int(entry.like_dislike_ratio * 100)))***REMOVED***

            cards = self.cah.cards.question_cards.copy(
            ) if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.question_cards.copy()
                if x.creator_id in [u.id for u in message.mentions]
            ]
            sort_mode = leftover_args[1].lower(
            ) if len(leftover_args) > 1 and leftover_args[1].lower(
            ) in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(
                    cards,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.qcard_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None

            if search_query is None:
                return Response(
                    "You need to provide a query to search for!",
                    delete_after=15)

            results = self.cah.cards.search_question_card(search_query, 3)

            if len(results) < 1:
                return Response(
                    "**Didn't find any question cards!**", delete_after=15)

            card_string = "***REMOVED***0.id***REMOVED***. \"***REMOVED***1***REMOVED***\""
            cards = []
            for card in results:
                cards.append(
                    card_string.format(card,
                                       card.text.replace("$", "\_\_\_\_\_")))

            return Response(
                "**I found the following question cards:**\n\n" +
                "\n".join(cards),
                delete_after=40)
        elif argument == "info":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            card = self.cah.cards.get_question_card(card_id)
            if card is not None:
                info = "Question Card *****REMOVED***0.id***REMOVED***** by ***REMOVED***1***REMOVED***\n```\n\"***REMOVED***0.text***REMOVED***\"\nused ***REMOVED***0.occurences***REMOVED*** time***REMOVED***2***REMOVED***\ncreated ***REMOVED***3***REMOVED***```\nUse `***REMOVED***4***REMOVED***cards edit ***REMOVED***0.id***REMOVED***` to edit this card`"
                return Response(
                    info.format(card,
                                self.get_global_user(card.creator_id).mention,
                                "s" if card.occurences != 1 else "",
                                prettydate(card.creation_date),
                                self.config.command_prefix))
        elif argument == "create":
            text = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...", delete_after=20)
            if len(text) > 500:
                return Response("Maybe a bit too long?", delete_after=20)

            if text.count("$") < 1:
                return Response(
                    "You need to have at least one blank ($) space",
                    delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card:
                return Response(
                    "There's already a question card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***qcards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_question_card(text, author.id)
            return Response(
                "Successfully created question card *****REMOVED******REMOVED*****".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number", delete_after=20)

            if card_id is None:
                return Response(
                    "You need to provide the question card's id!",
                    delete_after=20)

            text = " ".join(
                leftover_args[2:]) if len(leftover_args) > 2 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your question card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...", delete_after=20)
            if len(text) > 500:
                return Response("Maybe a bit too long?", delete_after=20)

            if text.count("$") < 1:
                return Response(
                    "You need to have at least one blank ($) space",
                    delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card and card.id != card_id_value:
                return Response(
                    "There's already a question card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***qcards info ***REMOVED***0***REMOVED***` to find out more about this question card".
                    format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_question_card(card_id, text):
                return Response(
                    "Edited question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
            else:
                return Response(
                    "There's no question card with that id", delete_after=15)
        elif argument == "delete":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            if card_id is None:
                return Response(
                    "You must specify the question card id", delete_after=15)

            if self.cah.cards.remove_question_card(card_id):
                return Response(
                    "Deleted question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
            else:
                return Response(
                    "Could not remove question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
        else:
            return await self.cmd_help(channel, ["qcards"])

    async def qcard_viewer(self,
                           channel,
                           author,
                           cards,
                           display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Question Cards | Page ***REMOVED***0***REMOVED*** of ***REMOVED***1***REMOVED*****\n```\n***REMOVED***2***REMOVED***\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<***REMOVED******REMOVED***> \"***REMOVED******REMOVED***\"***REMOVED******REMOVED***"

        items_per_page = 20
        timeout = 60
        current_page = 0

        total_pages, items_on_last_page = divmod(
            len(cards) - 1, items_per_page)

        def msg_check(msg):
            return msg.content.lower().strip().startswith(cmds)

        while True:
            start_index = current_page * items_per_page
            end_index = start_index + \
                (items_per_page - 1 if current_page <
                 total_pages else items_on_last_page)
            page_cards = cards[start_index:end_index]

            page_cards_texts = []
            for p_c in page_cards:
                page_cards_texts.append(
                    card_string.format(
                        p_c.id,
                        p_c.text.replace("$", "_____"), "" if
                        display_additional is None or display_additional(p_c)
                        is None else " | ***REMOVED******REMOVED***".format(display_additional(p_c))))

            interface_msg = await self.safe_send_message(
                channel,
                site_interface.format(current_page + 1, total_pages + 1,
                                      "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(
                timeout, author=author, channel=channel, check=msg_check)

            if not user_msg:
                await self.safe_delete_message(interface_msg)
                break

            content = user_msg.content.lower().strip()

            if content.startswith("n"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page + 1) % (total_pages + 1)
            elif content.startswith("p"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page - 1) % (total_pages + 1)
            elif content.startswith("exit"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                break

        await self.safe_send_message(
            channel, "Closed the question card viewer!", expire_in=20)

    @block_user
    @command_info("1.9.5", 1478998740, ***REMOVED***
        "2.0.2": (1481387640,
                  "Added Hangman game and generalised game hub command"),
        "3.5.2": (1497712233, "Updated documentaion for this command")
    ***REMOVED***)
    async def cmd_game(self,
                       message,
                       channel,
                       author,
                       leftover_args,
                       game=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***game [name]`
        ///|Explanation
        Play a game
        ///|References
        Cards against humanity can be played with the `cah` command.
        Use `***REMOVED***command_prefix***REMOVED***help cah` to learn more
        """

        all_funcs = dir(self)
        all_games = list(filter(lambda x: re.search("^g_\w+", x), all_funcs))
        all_game_names = [x[2:] for x in all_games]
        game_list = [***REMOVED***
            "name":
            x[2:],
            "handler":
            getattr(self, x, None),
            "description":
            getattr(self, x, None).__doc__.strip(' \t\n\r')
        ***REMOVED*** for x in all_games]

        if message.mentions is not None and len(message.mentions) > 0:
            author = message.mentions[0]

        if game is None:
            shuffle(game_list)

            def check(m):
                return (m.content.lower() in ["y", "n", "exit"])

            for current_game in game_list:
                msg = await self.safe_send_message(
                    channel,
                    "How about this game:\n\n*****REMOVED******REMOVED*****\n***REMOVED******REMOVED***\n\nType `y`, `n` or `exit`".
                    format(current_game["name"], current_game["description"]))
                response = await self.wait_for_message(
                    100, author=author, channel=channel, check=check)

                if not response or response.content.startswith(
                        self.config.command_prefix) or response.content.lower(
                ).startswith('exit'):
                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)
                    await self.safe_send_message(channel, "Nevermind then.")
                    return

                if response.content.lower() == "y":
                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)
                    game = current_game["name"]
                    break

                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

            if game is None:
                await self.safe_send_message(
                    channel, "That was all of them.", expire_in=20)
                return

        game = game.lower()
        handler = getattr(self, "g_" + game.title(), None)
        if handler is None:
            return Response("There's no game like that...", delete_after=20)

        await handler(author, channel, leftover_args)

    async def g_2048(self, author, channel, additional_args):
        """
        Join the same numbers and get to the 2048 tile!
        """

        save_code = additional_args[0] if len(additional_args) > 0 else None
        size = additional_args[1] if len(additional_args) > 1 else 5

        game = Game2048(size, save_code)
        game_running = True
        turn_index = 1
        cache_location = "cache/pictures/g2048_img" + str(author.id)

        def check(reaction, user):
            if reaction.custom_emoji:
                # self.log (str (reaction.emoji) + " is a custom emoji")
                # self.log("Ignoring my own reaction")
                return False

            if (str(reaction.emoji) in ("⬇", "➡", "⬆", "⬅") or
                str(reaction.emoji).startswith("📽") or
                str(reaction.emoji).startswith("💾")
                ) and reaction.count > 1 and user == author:
                return True

            # self.log (str (reaction.emoji) + " was the wrong type of
            # emoji")
            return False

        while game_running:
            direction = None
            turn_information = ""
            # self.log (str (game))

            await self.send_typing(channel)

            while direction is None:
                msg = await self.send_file(
                    channel,
                    game.getImage(cache_location) + ".png",
                    content="**2048**\n***REMOVED******REMOVED*** turn ***REMOVED******REMOVED***".format(
                        str(turn_index) +
                        ("th" if 4 <= turn_index % 100 <= 20 else ***REMOVED***
                            1: "st",
                            2: "nd",
                            3: "rd"
                        ***REMOVED***.get(turn_index % 10, "th")), turn_information))
                turn_information = ""
                await self.add_reaction(msg, "⬅")
                await self.add_reaction(msg, "⬆")
                await self.add_reaction(msg, "➡")
                await self.add_reaction(msg, "⬇")
                await self.add_reaction(msg, "📽")
                await self.add_reaction(msg, "💾")

                reaction, user = await self.wait_for_reaction(
                    check=check, message=msg)
                msg = reaction.message  # for some reason this has to be like this
                # self.log ("User accepted. There are " + str (len
                # (msg.reactions)) + " reactions. [" + ", ".join ([str
                # (r.count) for r in msg.reactions]) + "]")

                for reaction in msg.reactions:
                    if str(reaction.emoji) == "📽" and reaction.count > 1:
                        await self.send_file(
                            user,
                            game.getImage(cache_location) + ".gif",
                            content="**2048**\nYour replay:")
                        turn_information = "| *replay has been sent*"

                    if str(reaction.emoji) == "💾" and reaction.count > 1:
                        await self.safe_send_message(
                            user,
                            "The save code is: *****REMOVED***0***REMOVED*****\nUse `***REMOVED***1***REMOVED***game 2048 ***REMOVED***2***REMOVED***` to continue your current game".
                            format(
                                escape_dis(game.get_save()),
                                self.config.command_prefix, game.get_save()))
                        turn_information = "| *save code has been sent*"

                    if str(reaction.emoji) in ("⬇", "➡", "⬆",
                                               "⬅") and reaction.count > 1:
                        direction = ("⬇", "➡", "⬆",
                                     "⬅").index(str(reaction.emoji))

                    # self.log ("This did not match a direction: " + str
                    # (reaction.emoji))

                if direction is None:
                    await self.safe_delete_message(msg)
                    turn_information = "| You didn't specifiy the direction" if turn_information is not "" else turn_information

            # self.log ("Chose the direction " + str (direction))
            game.move(direction)
            turn_index += 1
            await self.safe_delete_message(msg)

            if game.won():
                await self.safe_send_message(
                    channel,
                    "**2048**\nCongratulations, you won after ***REMOVED******REMOVED*** turns".format(
                        str(turn_index)))
                game_running = False

            if game.lost():
                await self.safe_send_message(
                    channel, "**2048**\nYou lost after ***REMOVED******REMOVED*** turns".format(
                        str(turn_index)))
                game_running = False

        await self.send_file(
            channel,
            game.getImage(cache_location) + ".gif",
            content="**2048**\nYour replay:")
        await self.safe_delete_message(msg)

    async def g_Hangman(self, author, channel, additional_args):
        """
        Guess a word by guessing each and every letter
        """

        tries = additional_args[0] if len(additional_args) > 0 else 10

        word = additional_args[1] if len(additional_args) > 1 else re.sub(
            '[^a-zA-Z]', '', random_line(ConfigDefaults.hangman_wordlist))

        alphabet = list("abcdefghijklmnopqrstuvwxyz")
        self.log("Started a Hangman game with \"" + word + "\"")

        game = GameHangman(word, tries)
        running = True

        def check(m):
            return (m.content.lower() in alphabet or
                    m.content.lower() == word or m.content.lower() == "exit")

        while running:
            current_status = game.get_beautified_string()
            msg = await self.safe_send_message(
                channel,
                "**Hangman**\n***REMOVED******REMOVED*** trie***REMOVED******REMOVED*** left\n\n***REMOVED******REMOVED***\n\n`Send the letter you want to guess or type \"exit\" to exit.`".
                format(game.tries_left, "s"
                       if game.tries_left != 1 else "", current_status))
            response = await self.wait_for_message(
                300, author=author, channel=channel, check=check)

            if not response or response.content.lower().startswith(
                    self.config.command_prefix) or response.content.lower(
            ).startswith('exit'):
                await self.safe_delete_message(msg)
                await self.safe_send_message(
                    channel, "Aborting this Hangman game. Thanks for playing!")
                running = False

            if response.content.lower() == word:
                await self.safe_send_message(
                    channel,
                    "Congratulations, you got it!\nThe word is: ****REMOVED******REMOVED****".format(
                        word))
                return

            letter = response.content[0]
            game.guess(letter)

            if game.won:
                await self.safe_send_message(
                    channel,
                    "Congratulations, you got it!\nThe word is: ****REMOVED******REMOVED****".format(
                        word))
                running = False

            if game.lost:
                await self.safe_send_message(channel, "You lost!")
                running = False

            await self.safe_delete_message(msg)
            await self.safe_delete_message(response)

    # @owner_only
    # async def cmd_getemojicode(self, channel, message, emoji):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***getemojicode emoji
    #
    #     logs the emoji to the console so that you can retrieve the unicode symbol.
    #     """
    #
    #     self.log(emoji)
    #     await self.safe_delete_message(message)

    async def cmd_9gag(self, channel, author, post_id):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***9gag <id>`
        ///|Explanation
        Display the 9gag post with the specified id
        """

        post = get_post(post_id)
        if not post:
            return Response("couldn't find that 9gag post, sorreyyyy!")

        if post.content_type == ContentType.IMAGE:
            em = Embed(title=post.title, url=post.hyperlink, colour=9316352)
            em.set_author(name=author.display_name, icon_url=author.avatar_url)
            em.set_image(url=post.content_url)
            em.set_footer(text="***REMOVED******REMOVED*** upvotes | ***REMOVED******REMOVED*** comments".format(
                post.upvotes, post.comment_count))

            await self.send_message(channel, embed=em)
        else:
            downloader = urllib.request.URLopener()
            saveloc = "cache/pictures/9gag.mp4"
            downloader.retrieve(post.content_url, saveloc)
            clip = editor.VideoFileClip(saveloc)
            # clip.resize(.5)
            clip = video.fx.all.resize(clip, newsize=.55)
            clip.write_gif("cache/pictures/9gag.gif", fps=10)
            saveloc = "cache/pictures/9gag.gif"
            # subprocess.run(
            #     ["gifsicle", "-b", "cache/pictures/9gag.gif", "--colors", "256"])

            em = Embed(title=post.title, url=post.hyperlink, colour=9316352)
            em.set_author(name=author.display_name, icon_url=author.avatar_url)
            em.set_footer(text="***REMOVED******REMOVED*** upvotes | ***REMOVED******REMOVED*** comments".format(
                post.upvotes, post.comment_count))

            await self.send_message(channel, embed=em)
            await self.send_file(channel, saveloc)

        for comment in post.comments[:3]:
            em = Embed(
                timestamp=comment.timestamp,
                colour=11946278,
                url=comment.permalink)
            em.set_author(
                name=comment.name,
                icon_url=comment.avatar,
                url=comment.profile_url)
            em.set_footer(text="***REMOVED******REMOVED*** upvotes | ***REMOVED******REMOVED*** replies".format(
                comment.score, comment.reply_count))
            if comment.content_type == ContentType.TEXT:
                em.description = comment.content
            elif comment.content_type in (ContentType.IMAGE, ContentType.GIF):
                em.set_image(url=comment.content)

            await self.send_message(channel, embed=em)

    # async def nine_gag_get_section(self, channel, message):
    # category_dict = ***REMOVED***"🔥": "hot", "📈": "trending", "🆕": "new"***REMOVED***
    #
    # def check(reaction, user):
    #     if reaction.custom_emoji:
    #         return False
    #
    #     if str(reaction.emoji) in category_dict.keys() and reaction.count > 1 and user == author:
    #         return True
    #
    #     return False
    #
    # msg = await self.safe_send_message("What section would you like to switch to?")
    # await self.add_reaction(msg, "🔥")
    # await self.add_reaction(msg, "📈")
    # await self.add_reaction(msg, "🆕")
    #
    # reaction, user = await self.wait_for_reaction(check=check, message=msg)
    #
    # await self.safe_delete_message(msg)
    #
    # return category_dict[str(reaction.emoji)]

    # async def cmd_twitter(self, channel, tweet_id):
    #     """
    #     ///|Usage
    #     ***REMOVED***command_prefix***REMOVED***twitter <tweet_id>
    #     ///|Explanation
    #     Embed a tweet
    #     """
    #
    #     tweet = get_tweet(tweet_id)
    #     # self.log(tweet.created_at.year)
    #     em = Embed(description=tweet.text)
    #     em.set_author(url=tweet.user.url, name=tweet.user.name,
    #                   icon_url=tweet.user.avatar_url)
    #     await self.send_message(channel, embed=em)

    # async def cmd_giphy(self, channel, gif_id):
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get("http://api.giphy.com/v1/gifs/" + gif_id + "?api_key=dc6zaTOxFJmzC") as resp:
    #             response = await resp.json()
    #     data = response["data"]
    #     url = data["url"]
    #     username = data["username"]
    #     source = data["source"]
    #     caption = data["caption"] if "caption" in data else "GIPHY"
    #     timestamp = datetime.strptime(
    #         data["import_datetime"], "%Y-%m-%d %H:%M:%S")
    #     gif = data["images"]["original"]["url"]
    #
    #     em = Embed(title=caption, timestamp=timestamp, url=url)
    #     em.set_image(url=gif)
    #     em.set_author(url=source, name=username)
    #     await self.send_message(channel, embed=em)

    async def cmd_repeat(self, player):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***repeat`
        ///|Explanation
        Cycles through the repeat options. Default is no repeat, switchable to repeat all or repeat current song.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't change repeat mode! The player is not playing!",
                expire_in=20)

        player.repeat()

        if player.is_repeatNone:
            return Response(":play_pause: Repeat mode: None", delete_after=20)
        if player.is_repeatAll:
            return Response(":repeat: Repeat mode: All", delete_after=20)
        if player.is_repeatSingle:
            return Response(
                ":repeat_one: Repeat mode: Single", delete_after=20)

    async def cmd_promote(self, player, position=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***promote [song position]`
        ///|Explanation
        Promotes the last song in the queue to the front.
        If you specify a position, it promotes the song at that position to the front.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't modify the queue! The player is not playing!",
                expire_in=20)

        length = len(player.playlist.entries)

        if length < 2:
            raise exceptions.CommandError(
                "Can't promote! Please add at least 2 songs to the queue!",
                expire_in=20)

        if not position:
            entry = player.playlist.promote_last()
        else:
            try:
                position = int(position)
            except ValueError:
                raise exceptions.CommandError(
                    "This is not a valid song number! Please choose a song \
                    number between 2 and %s!" % length,
                    expire_in=20)

            if position == 1:
                raise exceptions.CommandError(
                    "This song is already at the top of the queue!",
                    expire_in=20)
            if position < 1 or position > length:
                raise exceptions.CommandError(
                    "Can't promote a song not in the queue! Please choose a song \
                    number between 2 and %s!" % length,
                    expire_in=20)

            entry = player.playlist.promote_position(position)

        reply_text = "Promoted **%s** to the :top: of the queue. Estimated time until playing: %s"
        btext = entry.title

        try:
            time_until = await player.playlist.estimate_time_until(1, player)
        except:
            traceback.print_exc()
            time_until = ''

        reply_text %= (btext, time_until)

        return Response(reply_text, delete_after=30)

    @block_user
    @command_info("1.9.5", 1479599760, ***REMOVED***
        "3.4.6":    (1497617827, "when Giesela can't add the entry to the playlist she tries to figure out **why** it didn't work"),
        "3.4.7":    (1497619770, "Fixed an annoying bug in which the builder wouldn't show any entries if the amount of entries was a multiple of 20"),
        "3.5.1": (1497706811, "Giesela finally keeps track whether a certain entry comes from a playlist or not"),
        "3.5.8": (1497827857, "Default sort mode when loading playlists is now random and removing an entry in the playlist builder no longer messes with the current page."),
        "3.6.1": (1497969463, "when saving a playlist, list all changes")
    ***REMOVED***)
    async def cmd_playlist(self, channel, author, server, player,
                           leftover_args):
        """
        ///|Load
        `***REMOVED***command_prefix***REMOVED***playlist load <savename> [add | replace] [none | random] [startindex] [endindex (inclusive)]`\n\nTrust me, it's more complicated than it looks
        ///(NL)|List all playlists
        `***REMOVED***command_prefix***REMOVED***playlist showall [alphabetical | author | entries | playtime | random | replays]`
        ///(NL)|Build a new playlist
        `***REMOVED***command_prefix***REMOVED***playlist builder <savename>`
        ///(NL)|Save the current queue
        `***REMOVED***command_prefix***REMOVED***playlist save <savename>`
        ///(NL)|Clone
        `***REMOVED***command_prefix***REMOVED***playlist clone <fromname> <savename> [startindex | endindex (inclusive)]`
        ///(NL)|Delete a playlist
        `***REMOVED***command_prefix***REMOVED***playlist delete <savename>`
        ///(NL)|Information
        `***REMOVED***command_prefix***REMOVED***playlist <savename>`
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else ""
        savename = re.sub(
            "\W", "",
            leftover_args[1].lower()) if len(leftover_args) > 1 else ""
        load_mode = leftover_args[
            2].lower() if len(leftover_args) > 2 else "add"
        additional_args = leftover_args[2:] if len(leftover_args) > 2 else []

        forbidden_savenames = [
            "showall", "savename", "save", "load", "delete", "builder",
            "extras", "add", "remove", "save", "exit", "clone", "rename",
            "extras", "alphabetical", "author", "entries", "playtime", "random"
        ]

        if argument == "save":
            if savename in self.playlists.saved_playlists:
                return Response(
                    "Can't save this playlist, there's already a playlist with this name.",
                    delete_after=20)
            if len(savename) < 3:
                return Response(
                    "Can't save this playlist, the name must be longer than 3 characters",
                    delete_after=20)
            if savename in forbidden_savenames:
                return Response(
                    "Can't save this playlist, this name is forbidden!",
                    delete_after=20)
            if len(player.playlist.entries) < 1:
                return Response(
                    "Can't save this playlist, there are no entries in the queue!",
                    delete_after=20)

            if self.playlists.set_playlist(
                [player.current_entry] + list(player.playlist.entries),
                    savename, author.id):
                return Response("Saved your playlist...", delete_after=20)

            return Response(
                "Uhm, something went wrong I guess :D", delete_after=20)

        elif argument == "load":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't load this playlist, there's no playlist with this name.",
                    delete_after=20)

            clone_entries = self.playlists.get_playlist(
                savename, player.playlist, channel=channel,
                author=author)["entries"]

            if load_mode == "replace":
                player.playlist.clear()
                if player.current_entry is not None:
                    player.skip()

            from_index = int(additional_args[2]) - \
                1 if len(additional_args) > 2 else 0
            if from_index >= len(clone_entries) or from_index < 0:
                return Response(
                    "Can't load the playlist starting from entry ***REMOVED******REMOVED***. This value is out of bounds.".
                    format(from_index),
                    delete_after=20)

            to_index = int(additional_args[
                3]) if len(additional_args) > 3 else len(clone_entries)
            if to_index > len(clone_entries) or to_index < 0:
                return Response(
                    "Can't load the playlist from the ***REMOVED******REMOVED***. to the ***REMOVED******REMOVED***. entry. These values are out of bounds.".
                    format(from_index, to_index),
                    delete_after=20)

            if to_index - from_index <= 0:
                return Response("No songs to play. RIP.", delete_after=20)

            clone_entries = clone_entries[from_index:to_index]

            sort_modes = ***REMOVED***
                "alphabetical": (lambda entry: entry.title, False),
                "random": None,
                "length": (lambda entry: entry.duration, True)
            ***REMOVED***

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

            await player.playlist.add_entries(clone_entries)
            self.playlists.bump_replay_count(savename)

            return Response("Done. Enjoy your music!", delete_after=10)

        elif argument == "delete":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't delete this playlist, there's no playlist with this name.",
                    delete_after=20)

            self.playlists.remove_playlist(savename)
            return Response(
                "****REMOVED******REMOVED**** has been deleted".format(savename), delete_after=20)

        elif argument == "clone":
            if savename not in self.playlists.saved_playlists:
                return Response(
                    "Can't clone this playlist, there's no playlist with this name.",
                    delete_after=20)
            clone_playlist = self.playlists.get_playlist(
                savename, player.playlist)
            clone_entries = clone_playlist["entries"]
            extend_existing = False

            if additional_args is None:
                return Response(
                    "Please provide a name to save the playlist to",
                    delete_after=20)

            if additional_args[0].lower() in self.playlists.saved_playlists:
                extend_existing = True
            if len(additional_args[0]) < 3:
                return Response(
                    "This is not a valid playlist name, the name must be longer than 3 characters",
                    delete_after=20)
            if additional_args[0].lower() in forbidden_savenames:
                return Response(
                    "This is not a valid playlist name, this name is forbidden!",
                    delete_after=20)

            from_index = int(additional_args[1]) - \
                1 if len(additional_args) > 1 else 0
            if from_index >= len(clone_entries) or from_index < 0:
                return Response(
                    "Can't clone the playlist starting from entry ***REMOVED******REMOVED***. This entry is out of bounds.".
                    format(from_index),
                    delete_after=20)

            to_index = int(additional_args[
                2]) if len(additional_args) > 2 else len(clone_entries)
            if to_index > len(clone_entries) or to_index < 0:
                return Response(
                    "Can't clone the playlist from the ***REMOVED******REMOVED***. to the ***REMOVED******REMOVED***. entry. These values are out of bounds.".
                    format(from_index, to_index),
                    delete_after=20)

            if to_index - from_index <= 0:
                return Response(
                    "That's not enough entries to create a new playlist.",
                    delete_after=20)

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
                "*****REMOVED******REMOVED***** ***REMOVED******REMOVED***has been cloned to *****REMOVED******REMOVED*****".format(
                    savename, "(from the ***REMOVED******REMOVED***. to the ***REMOVED******REMOVED***. index) ".format(
                        str(from_index + 1), str(to_index + 1)) if
                    from_index is not 0 or to_index is not len(clone_entries)
                    else "", additional_args[0].lower()),
                delete_after=20)

        elif argument == "showall":
            if len(self.playlists.saved_playlists) < 1:
                return Response(
                    "There are no saved playlists.\n**You** could add one though. Type `***REMOVED******REMOVED***help playlist` to see how!".format(
                        self.config.command_prefix),
                    delete_after=40)

            response_text = "**Found the following playlists:**\n\n"
            iteration = 1

            sort_modes = ***REMOVED***"alphabetical": (lambda playlist: playlist, False), "entries": (lambda playlist: int(
                self.playlists.get_playlist(playlist, player.playlist)["entry_count"]), True), "author": (lambda playlist: self.get_global_user(self.playlists.get_playlist(playlist, player.playlist)["author"]).name, False), "random": None, "playtime": (lambda playlist: sum([x.duration for x in self.playlists.get_playlist(playlist, player.playlist)["entries"]]), True), "replays": (lambda playlist: self.playlists.get_playlist(playlist, player.playlist)["replay_count"], True)***REMOVED***

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
                response_text += "*****REMOVED******REMOVED***.** **\"***REMOVED******REMOVED***\"** by ***REMOVED******REMOVED***\n```\n  ***REMOVED******REMOVED*** entr***REMOVED******REMOVED***\n  played ***REMOVED******REMOVED*** time***REMOVED******REMOVED***\n  ***REMOVED******REMOVED***```\n\n".format(
                    iteration,
                    pl.replace("_", " ").title(),
                    self.get_global_user(infos["author"]).mention,
                    str(infos["entry_count"]), "ies"
                    if int(infos["entry_count"]) is not 1 else "y",
                    infos["replay_count"], "s"
                    if int(infos["replay_count"]) != 1 else "",
                    format_time(
                        sum([x.duration for x in infos["entries"]]),
                        round_seconds=True,
                        max_specifications=2))
                iteration += 1

            # self.log (response_text)
            return Response(response_text, delete_after=100)

        elif argument == "builder":
            if len(savename) < 3:
                return Response(
                    "Can't build on this playlist, the name must be longer than 3 characters",
                    delete_after=20)
            if savename in forbidden_savenames:
                return Response(
                    "Can't build on this playlist, this name is forbidden!",
                    delete_after=20)

            self.log("Starting the playlist builder")
            response = await self.playlist_builder(channel, author, server,
                                                   player, savename)
            return response

        elif argument in self.playlists.saved_playlists:
            infos = self.playlists.get_playlist(argument.lower(),
                                                player.playlist)
            entries = infos["entries"]

            desc_text = "***REMOVED******REMOVED*** entr***REMOVED******REMOVED***\n***REMOVED******REMOVED*** long".format(
                str(infos["entry_count"]), "ies"
                if int(infos["entry_count"]) is not 1 else "y",
                format_time(
                    sum([x.duration for x in entries]),
                    round_seconds=True,
                    combine_with_and=True,
                    replace_one=True,
                    max_specifications=2))
            em = Embed(
                title=argument.replace("_", " ").title(),
                description=desc_text)
            pl_author = self.get_global_user(infos["author"])
            em.set_author(
                name=pl_author.display_name, icon_url=pl_author.avatar_url)

            for i in range(min(len(entries), 20)):
                em.add_field(
                    name="***REMOVED***0:>3***REMOVED***. ***REMOVED***1:<50***REMOVED***".format(i + 1,
                                                  entries[i].title[:50]),
                    value="duration: " + format_time(
                        entries[i].duration,
                        round_seconds=True,
                        round_base=1,
                        max_specifications=2),
                    inline=False)

            if len(entries) > 20:
                em.add_field(
                    name="**And ***REMOVED******REMOVED*** more**".format(len(entries) - 20),
                    value="To view them, open the playlist builder")

            em.set_footer(
                text="To edit this playlist type \"***REMOVED******REMOVED***playlist builder ***REMOVED******REMOVED***\"".
                format(self.config.command_prefix, argument))

            await self.send_message(channel, embed=em)

            return

        return await self.cmd_help(channel, ["playlist"])

    async def socket_playlist_load(self, player, playlist_name):
        playlist_name = playlist_name.lower().strip()
        if playlist_name not in self.playlists.saved_playlists:
            return False

        clone_entries = self.playlists.get_playlist(playlist_name,
                                                    player.playlist)["entries"]

        player.playlist.clear()
        if player.current_entry is not None:
            player.skip()

        await player.playlist.add_entries(clone_entries)
        self.playlists.bump_replay_count(playlist_name)

    async def playlist_builder(self, channel, author, server, player,
                               _savename):
        if _savename not in self.playlists.saved_playlists:
            self.playlists.set_playlist([], _savename, author.id)

        def check(m):
            return (m.content.split()[0].lower() in [
                "add", "remove", "rename", "exit", "p", "n", "save", "extras"
            ])

        abort = False
        save = False
        entries_page = 0
        pl_changes = ***REMOVED***
            "remove_entries_indexes": [],
            "remove_entries": [],  # used for changelog
            "new_entries": [],
            "new_name": None
        ***REMOVED***
        savename = _savename
        user_savename = savename

        interface_string = "*****REMOVED******REMOVED***** by *****REMOVED******REMOVED***** (***REMOVED******REMOVED*** song***REMOVED******REMOVED*** with a total length of ***REMOVED******REMOVED***)\n\n***REMOVED******REMOVED***\n\n**You can use the following commands:**\n`add <query>`: Add a video to the playlist (this command works like the normal `***REMOVED******REMOVED***play` command)\n`remove <index> [index 2] [index 3] [index 4]`: Remove a song from the playlist by it's index\n`rename <newname>`: rename the current playlist\n`extras`: see the special functions\n\n`p`: previous page\n`n`: next page\n`save`: save and close the builder\n`exit`: leave the builder without saving"

        extras_string = "*****REMOVED******REMOVED***** by *****REMOVED******REMOVED***** (***REMOVED******REMOVED*** song***REMOVED******REMOVED*** with a total length of ***REMOVED******REMOVED***)\n\n**Extra functions:**\n`sort <alphabetical | length | random>`: sort the playlist (default is alphabetical)\n`removeduplicates`: remove all duplicates from the playlist\n\n`abort`: return to main screen"

        edit_string = "*****REMOVED******REMOVED***** by *****REMOVED******REMOVED***** (***REMOVED******REMOVED*** song***REMOVED******REMOVED*** with a total length of ***REMOVED******REMOVED***)\n```\nentry_information\n```\n\n**Edit functions:**\n`rename <newname>`: rename the entry\n`setstart <timestamp>`: set the starting time of the song\n`setend <timestamp>`: set the ending time of the song\n\n`abort`: return to main screen"

        playlist = self.playlists.get_playlist(_savename, player.playlist)

        while (not abort) and (not save):
            entries = playlist["entries"]
            entries_text = ""

            items_per_page = 20
            iterations, overflow = divmod(len(entries), items_per_page)

            if iterations > 0 and overflow == 0:
                iterations -= 1
                overflow += items_per_page

            # self.log(iterations, overflow)

            start = (entries_page * items_per_page)
            end = (start + (overflow if entries_page >= iterations else
                            items_per_page)) if len(entries) > 0 else 0
            # this_page_entries = entries [start : end]

            # self.log("I have ***REMOVED******REMOVED*** entries in the whole list and now I'm viewing from ***REMOVED******REMOVED*** to ***REMOVED******REMOVED*** (***REMOVED******REMOVED*** entries)".format(
            #     str(len(entries)), str(start), str(end), str(end - start)))

            for i in range(start, end):
                entries_text += str(i + 1) + ". " + entries[i].title + "\n"
            entries_text += "\nPage ***REMOVED******REMOVED*** of ***REMOVED******REMOVED***".format(entries_page + 1,
                                                     iterations + 1)

            interface_message = await self.safe_send_message(
                channel,
                interface_string.format(
                    user_savename.replace("_", " ").title(),
                    self.get_global_user(playlist["author"]).mention,
                    playlist["entry_count"], "s"
                    if int(playlist["entry_count"]) is not 1 else "",
                    format_time(sum([x.duration for x in entries])),
                    entries_text, self.config.command_prefix))
            response_message = await self.wait_for_message(
                author=author, channel=channel, check=check)

            if not response_message:
                await self.safe_delete_message(interface_message)
                abort = True
                break

            elif response_message.content.lower().startswith(self.config.command_prefix) or \
                    response_message.content.lower().startswith('exit'):
                abort = True

            elif response_message.content.lower().startswith("save"):
                save = True

            split_message = response_message.content.split()
            arguments = split_message[1:] if len(split_message) > 1 else None

            if split_message[0].lower() == "add":
                if arguments is not None:
                    msg = await self.safe_send_message(channel,
                                                       "I'm working on it.")
                    query = " ".join(arguments)
                    try:
                        start_time = datetime.now()
                        entries = await self.get_play_entry(
                            player, query, author=author, channel=channel)
                        if (datetime.now() - start_time).total_seconds() > 40:
                            await self.safe_send_message(
                                author,
                                "Wow, that took quite a while.\nI'm done now though so come check it out!",
                                expire_in=70)

                        pl_changes["new_entries"].extend(entries)
                        playlist["entries"].extend(entries)
                        playlist["entry_count"] = str(
                            int(playlist["entry_count"]) + len(entries))
                        it, ov = divmod(
                            int(playlist["entry_count"]), items_per_page)
                        entries_page = it - 1 if ov == 0 else it
                    except Exception as e:
                        await self.safe_send_message(
                            channel,
                            "**Something went terribly wrong there:**\n```\n***REMOVED******REMOVED***\n```".
                            format(e),
                            expire_in=20)
                    await self.safe_delete_message(msg)

            elif split_message[0].lower() == "remove":
                if arguments is not None:
                    indieces = []
                    for arg in arguments:
                        try:
                            index = int(arg) - 1
                        except:
                            index = -1

                        if index >= 0 and index < int(playlist["entry_count"]):
                            indieces.append(index)

                    pl_changes["remove_entries_indexes"].extend(indieces)
                    pl_changes["remove_entries"].extend(
                        [playlist["entries"][ind] for ind in indieces])  # for the changelog
                    playlist["entry_count"] = str(
                        int(playlist["entry_count"]) - len(indieces))
                    playlist["entries"] = [
                        playlist["entries"][x]
                        for x in range(len(playlist["entries"]))
                        if x not in indieces
                    ]
                    # it, ov = divmod(
                    #     int(playlist["entry_count"]), items_per_page)
                    # entries_page = it - 1 if ov == 0 else it

            elif split_message[0].lower() == "rename":
                if arguments is not None and len(
                        arguments[0]
                ) >= 3 and arguments[0] not in self.playlists.saved_playlists:
                    pl_changes["new_name"] = re.sub("\W", "",
                                                    arguments[0].lower())
                    user_savename = pl_changes["new_name"]

            elif split_message[0].lower() == "extras":

                def extras_check(m):
                    return (m.content.split()[0].lower() in [
                        "abort", "sort", "removeduplicates"
                    ])

                extras_message = await self.safe_send_message(
                    channel,
                    extras_string.format(
                        user_savename.replace("_", " ").title(),
                        self.get_global_user(playlist["author"]).mention,
                        playlist["entry_count"], "s"
                        if int(playlist["entry_count"]) is not 1 else "",
                        format_time(sum([x.duration for x in entries]))))
                resp = await self.wait_for_message(
                    author=author, channel=channel, check=extras_check)

                if not resp.content.lower().startswith(
                        self.config.command_prefix) and not resp.content.lower(
                ).startswith('abort'):
                    _cmd = resp.content.split()
                    cmd = _cmd[0].lower()
                    args = _cmd[1:] if len(_cmd) > 1 else None

                    if cmd == "sort":
                        sort_method = args[0].lower(
                        ) if args is not None and args[0].lower() in [
                            "alphabetical", "length", "random"
                        ] else "alphabetical"
                        pl_changes["remove_entries_indexes"] = list(
                            range(len(entries)))

                        if sort_method == "alphabetical":
                            pl_changes["new_entries"] = sorted(
                                entries, key=lambda entry: entry.title)
                            playlist["entries"] = sorted(
                                entries, key=lambda entry: entry.title)
                        elif sort_method == "length":
                            pl_changes["new_entries"] = sorted(
                                entries, key=lambda entry: entry.duration)
                            playlist["entries"] = sorted(
                                entries, key=lambda entry: entry.duration)
                        elif sort_method == "random":
                            new_ordered = entries
                            shuffle(new_ordered)
                            pl_changes["new_entries"] = new_ordered
                            playlist["entries"] = new_ordered

                    if cmd == "removeduplicates":
                        pl_changes["remove_entries_indexes"] = list(
                            range(len(entries)))
                        urls = []
                        new_list = []
                        for entry in entries:
                            if entry.url not in urls:
                                urls.append(entry.url)
                                new_list.append(entry)

                        pl_changes["new_entries"] = new_list
                        playlist["entries"] = new_list

                    # if cmd == "split-timestamp-entry":
                    #     if args is not None:
                    #         ind = int(args[0]) - 1
                    #         entry = entries[ind]
                    #         if entry.provides_timestamps:
                    #             pl_changes[
                    #                 "remove_entries_indexes"].append(ind)
                    #             msg = await self.safe_send_message(channel, "I'm working on it.")
                    #             start_time = datetime.now()
                    #             for sub in entry.sub_queue():
                    #                 try:
                    #                     a_s = re.sub(r"\W", "", sub[
                    #                                  "name"]).split()
                    #                     entries = await self.get_play_entry(player, channel, author, a_s[1:], a_s[0])
                    #                     pl_changes["new_entries"].extend(
                    #                         entries)
                    #                     playlist["entries"].extend(entries)
                    #                     playlist["entry_count"] = str(
                    #                         int(playlist["entry_count"]) + len(entries))
                    #                     it, ov = divmod(
                    #                         int(playlist["entry_count"]), items_per_page)
                    #                     entries_page = it
                    #                 except:
                    #                     continue
                    #
                    #             if (datetime.now() - start_time).total_seconds() > 40:
                    # await self.safe_send_message(author, "Wow, that took
                    # quite a while.\nI'm done now though so come check it
                    # out!", expire_in=70)

                await self.safe_delete_message(extras_message)
                await self.safe_delete_message(resp)

            elif split_message[0].lower() == "p":
                entries_page = (entries_page - 1) % (iterations + 1)

            elif split_message[0].lower() == "n":
                entries_page = (entries_page + 1) % (iterations + 1)

            await self.safe_delete_message(response_message)
            await self.safe_delete_message(interface_message)

        if abort:
            return Response("Closed *****REMOVED******REMOVED***** without saving".format(savename))
            self.log("Closed the playlist builder")

        if save:
            # self.log ("Going to remove the following entries: ***REMOVED******REMOVED*** |
            # Adding these entries: ***REMOVED******REMOVED*** | Changing the name to: ***REMOVED******REMOVED***".format
            # (pl_changes ["remove_entries_indexes"], ", ".join ([x.title for x
            # in pl_changes ["new_entries"]]), pl_changes ["new_name"]))

            if pl_changes["new_entries"] or pl_changes["remove_entries_indexes"] or pl_changes["new_name"]:
                c_log = "**CHANGES**\n\n"
                if pl_changes["new_entries"]:
                    new_entries_string = "\n".join(["    ***REMOVED******REMOVED***. `***REMOVED******REMOVED***`".format(ind, nice_cut(
                        entry.title, 40)) for ind, entry in enumerate(pl_changes["new_entries"], 1)])
                    c_log += "**New entries**\n***REMOVED******REMOVED***\n".format(new_entries_string)
                if pl_changes["remove_entries_indexes"]:
                    removed_entries_string = "\n".join(
                        ["    ***REMOVED******REMOVED***. `***REMOVED******REMOVED***`".format(pl_changes["remove_entries_indexes"][ind], nice_cut(entry.title, 40)) for ind, entry in enumerate(pl_changes["remove_entries"])])
                    c_log += "**Removed entries**\n***REMOVED******REMOVED***\n".format(
                        removed_entries_string)
                if pl_changes["new_name"]:
                    c_log += "**Renamed playlist**\n  From `***REMOVED******REMOVED***` to `***REMOVED******REMOVED***`".format(
                        savename.title(), pl_changes["new_name"].title())
            else:
                c_log = "No changes were made"

            self.playlists.edit_playlist(
                savename,
                player.playlist,
                new_entries=pl_changes["new_entries"],
                remove_entries_indexes=pl_changes["remove_entries_indexes"],
                new_name=pl_changes["new_name"])
            self.log("Closed the playlist builder and saved the playlist")

            return Response("Successfully saved *****REMOVED******REMOVED*****\n\n***REMOVED******REMOVED***".format(
                user_savename.replace("_", " ").title(), c_log))

    @command_info("2.9.2", 1479945600, ***REMOVED***
        "3.3.6": (1497387101, "added the missing \"s\", should be working again"),
        "3.4.4": (1497611753, "Changed command name from \"addplayingtoplaylist\" to \"addtoplaylist\", thanks Paulo"),
        "3.5.5": (1497792167, "Now displaying what entry has been added to the playlist"),
        "3.5.8": (1497826743, "Even more information displaying"),
        "3.6.1": (1497972538, "now accepts a query parameter which adds a song to the playlist like the `play` command does so for the queue")
    ***REMOVED***)
    async def cmd_addtoplaylist(self, channel, author, player, playlistname, query=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***addtoplaylist <playlistname>` [link | name]
        ///|Explanation
        Add the current entry to a playlist.
        If you either provide a link or a name, that song is added to the queue.
        """

        if playlistname is None:
            return Response(
                "Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        await self.send_typing(channel)

        if query:
            add_entry = (await self.get_play_entry(player, query, channel=channel, author=author))[0]
        else:
            if not player.current_entry:
                return Response(
                    "There's nothing playing right now so I can't add it to your playlist..."
                )

            add_entry = player.current_entry
            if add_entry.provides_timestamps:
                current_timestamp = add_entry.get_current_song_from_timestamp(
                    player.progress)["name"]
                # this looks ugly but eh, it works
                try:
                    add_entry = (await self.get_play_entry(player, current_timestamp, channel=channel, author=author))[0]
                except:
                    pass  # just go ahead and add the whole thing, what do I care :3

        if playlistname not in self.playlists.saved_playlists:
            if len(playlistname) < 3:
                return Response(
                    "Your name is too short. Please choose one with at least three letters."
                )
            self.playlists.set_playlist([add_entry], playlistname, author.id)
            return Response("Created a new playlist \"***REMOVED******REMOVED***\" and added `***REMOVED******REMOVED***`.".format(playlistname.title(),
                                                                                   add_entry.title))

        self.playlists.edit_playlist(
            playlistname, player.playlist, new_entries=[add_entry])
        return Response("Added `***REMOVED******REMOVED***` to playlist \"***REMOVED******REMOVED***\".".format(add_entry.title, playlistname.title()))

    @command_info("2.9.2", 1479945600, ***REMOVED***
        "3.3.6": (1497387101,
                  "added the missing \"s\", should be working again"),
        "3.4.4":
        (1497611753,
         "Changed command name from \"removeplayingfromplaylist\" to \"removefromplaylist\", thanks Paulo"
         ),
        "3.5.8": (1497826917, "Now displaying the names of the song and the playlist")
    ***REMOVED***)
    async def cmd_removefromplaylist(self, channel, author, player,
                                     playlistname):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***removefromplaylist <playlistname>`
        ///|Explanation
        Remove the current entry from a playlist
        """

        if playlistname is None:
            return Response(
                "Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response(
                "There's nothing playing right now so I can't remove it from your playlist..."
            )

        remove_entry = player.current_entry
        if remove_entry.provides_timestamps:
            current_timestamp = remove_entry.get_current_song_from_timestamp(
                player.progress)["name"]
            remove_entry = await self.get_play_entry(player, current_timestamp, channel=channel, author=author)

        if playlistname not in self.playlists.saved_playlists:
            return Response("There's no playlist the name \"***REMOVED******REMOVED***\".".format(playlistname.title()))

        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[remove_entry])
        return Response("Removed `***REMOVED******REMOVED***` from playlist \"***REMOVED******REMOVED***\".".format(remove_entry.title, playlistname))

    async def cmd_setentrystart(self, player, playlistname):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***setentrystart <playlistname>

        Set the start time for the current entry in the playlist to the current time
        """

        if playlistname is None:
            return Response(
                "Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response(
                "There's nothing playing right now...", delete_after=20)

        new_start = player.progress
        new_entry = player.current_entry
        new_entry.set_start(new_start)
        self.playlists.edit_playlist(
            playlistname,
            player.playlist,
            remove_entries=[player.current_entry],
            new_entries=[new_entry])

        return Response(
            "Set the starting point to ***REMOVED******REMOVED*** seconds.".format(new_start),
            delete_after=20)

    async def cmd_setentryend(self, player, playlistname):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***setentryend <playlistname>

        Set the end time for the current entry in the playlist to the current time
        """

        if playlistname is None:
            return Response(
                "Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response(
                "There's nothing playing right now...", delete_after=20)

        new_end = player.progress
        new_entry = player.current_entry
        new_entry.set_end(new_end)
        self.playlists.edit_playlist(
            playlistname,
            player.playlist,
            remove_entries=[player.current_entry],
            new_entries=[new_entry])

        return Response(
            "Set the ending point to ***REMOVED******REMOVED*** seconds.".format(new_start),
            delete_after=20)

    # async def cmd_setplayingname(self, player, playlistname, new_name, leftover_args):
    #     """
    #     Usage:
    #         ***REMOVED***command_prefix***REMOVED***setplayingname <playlistname> <new name>
    #
    #     Set the name of the current song
    #     """
    #     new_title = new_name + " " + " ".join(leftover_args)
    #
    #     if playlistname is None:
    #         return Response("Please specify the playlist's name!", delete_after=20)
    #
    #     playlistname = playlistname.lower()
    #
    #     if not player.current_entry:
    #         return Response("There's nothing playing right now...", delete_after=20)
    #
    #     if len(new_title) > 500 or len(new_title) < 3:
    #         return Response("The new title has to be at least 3 characters long", delete_after=20)
    #
    #     new_entry = player.current_entry
    #     new_entry.set_title(new_title)
    #     self.playlists.edit_playlist(
    #         playlistname, player.playlist, remove_entries=[player.current_entry], new_entries=[new_entry])
    #
    # return Response("The new title is \"***REMOVED******REMOVED***\"".format(new_title),
    # delete_after=20)

    async def cmd_wiki(self, channel, message, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***wiki [language] summarize [number of sentences] <query>
                -This function summarizes the content of a Wikipedia page

            ***REMOVED***command_prefix***REMOVED***wiki [language] <query>
                -This function provides the full Wikipedia article.
        """

        wikipedia_page = None
        wikipedia_page_title = None
        wikipedia.set_lang("en")

        if leftover_args[0].lower() in wikipedia.languages().keys():
            wikipedia.set_lang(leftover_args[0].lower())
            del (leftover_args[0])
        elif leftover_args[0].lower() in wikipedia.languages().values():
            wikipedia.set_lang(
                list(mydict.keys())[list(mydict.values()).index(
                    leftover_args[0].lower())])
            del (leftover_args[0])

        search_query = " ".join(leftover_args)

        # if "simon berger" in search_query.lower() or "simon jonas berger" in search_query.lower():
        #     already_used = load_file("data/simon_berger_wikied.txt")
        #
        #     if author.id in already_used:
        #         return Response("I mustn't betray my master twice for you!")
        #     else:
        #         already_used.append(author.id)
        #         write_file("data/simon_berger_wikied.txt", already_used)
        #
        # return Response("*****REMOVED*** Berger**\n***REMOVED*** Jonas Berger (born March 28,
        # 1992) is a computer scientist and works at Google London as head of
        # the Technical Solutions team.\nI didn't actually expect anyone to
        # read this far, but apparently you are...\nLet me tell you something
        # about my past then. I went to Kindergarten one year earlier than
        # normal. This is due to the fact, that one Doctor thought that I was a
        # genius (of course that turned out to be wrong). I skipped 4th grade,
        # not because I wanted, but because my teacher persuaded my parents to
        # do so. I especially loved that teacher and was sincerely upset about
        # that. I went to the gymnasium after 8th grade.Shortly after, at the
        # age of 15, my parents passed away in a car accident so I went to live
        # with my grandparents but 2 months later I lived in a flat in Zurich
        # to study at ETH. Because I practically skipped 2 years of education I
        # was merely 16 while everyone around me was already 18. With the age
        # of 20 I got my Bachelor's degree and at the age of 22 I finished my
        # Master's degree. While I was studying at ETH I got the chance to take
        # part in a Google Interview. After 2 interviews they offered me a job
        # as a Technical Solutions Consultant. June 25th 2016 they promoted me
        # to head of Technical Solutions.\n\nWhy am I telling you this? Well...
        # If you went ahead and looked me up I'm sure you were just a little
        # bit interested.")

        # self.log (search_query)

        if leftover_args[0] == "summarize":
            sent_num = int(leftover_args[1]) if str(
                type(leftover_args[1])) == "int" else 5
            search = leftover_args[2:] if str(
                type(leftover_args[1])) == "int" else leftover_args[1:]
            title = wikipedia.search(search, results=1, suggestion=True)[0]
            return Response("*****REMOVED******REMOVED*****\n***REMOVED******REMOVED***".format(title[
                0], wikipedia.summary(title, sentences=sent_num)))
        else:
            title = wikipedia.search(
                search_query, results=1, suggestion=True)[0]
            if title:
                wikipedia_page = wikipedia.page(title=title)
                wikipedia_page_title = title[0]

        if not wikipedia_page:
            return Response(
                "I didn't find anything called ****REMOVED******REMOVED****.".format(search_query),
                delete_after=20)

        return Response("*****REMOVED******REMOVED*****\n***REMOVED******REMOVED***".format(
            wikipedia_page_title,
            wikipedia.summary(wikipedia_page_title, sentences=3)))

    @command_info("1.9.5", 1479945600, ***REMOVED***
        "3.3.5":
        (1497284850,
         "removed delete_after keywords which was the reason this command was broken"
         )
    ***REMOVED***)
    async def cmd_getmusicfile(self, channel, author, player, index=0):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***getmusicfile
            ***REMOVED***command_prefix***REMOVED***getmusicfile index

        Get the music file of the current song.
        You may provide an index to get that file.
        """

        try:
            index = int(index) - 1
        except:
            return Response("Please provide a valid index")

        if index == -1:
            entry = player.current_entry
        else:
            if index < 0 or index >= len(player.playlist.entries):
                return Response("Your index is out of range")
            entry = player.playlist.entries[index]

        if not entry:
            return Response(
                "This entry is currently being worked on. Please retry again later"
            )

        if type(entry).__name__ == "StreamPlaylistEntry":
            return Response("Can't send you this because it's a live stream")

        if not entry.is_downloaded:
            try:
                await entry._download()
            except:
                return Response(
                    "Could not download the file. This really shouldn't happen"
                )

        await self.safe_send_message(
            author, "The file is being uploaded. Please wait a second.")
        await self.send_file(author, entry.filename, content="Here you go:")

    @block_user
    async def cmd_reminder(self, channel, author, player, server,
                           leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***reminder create
            ***REMOVED***command_prefix***REMOVED***reminder list

        Create a reminder!
        """

        if len(leftover_args) < 1:
            return Response("Please git gud!")

        command = leftover_args[0].lower().strip()

        if (command == "create"):
            import parsedatetime
            cal = parsedatetime.Calendar()

            reminder_name = None
            reminder_due = None
            reminder_repeat = None
            reminder_end = None
            reminder_action = None

            # find out the name
            def check(m):
                return len(m.content) > 3

            msg = await self.safe_send_message(
                channel, "How do you want to call your reminder?")
            response = await self.wait_for_message(
                author=author, channel=channel, check=check)
            reminder_name = response.content
            await self.safe_delete_message(msg)
            await self.safe_delete_message(response)

            # find out the due date
            while True:
                msg = await self.safe_send_message(channel, "When is it due?")
                response = await self.wait_for_message(
                    author=author, channel=channel)

                reminder_due = datetime(
                    *cal.parse(response.content.strip().lower())[0][:6])
                await self.safe_delete_message(msg)
                if reminder_due is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # repeated reminder
            while True:
                msg = await self.safe_send_message(
                    channel,
                    "When should this reminder be repeated? (\"never\" if not at all)"
                )
                response = await self.wait_for_message(
                    author=author, channel=channel)
                await self.safe_delete_message(msg)
                if (response.content.lower().strip() in ("n", "no", "nope",
                                                         "never")):
                    await self.safe_delete_message(response)
                    reminder_repeat = None
                    break

                reminder_repeat = datetime(*cal.parse(
                    response.content.strip().lower())[0][:6]) - datetime.now()
                if reminder_repeat is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # reminder end
            if reminder_repeat is not None:
                while True:
                    msg = await self.safe_send_message(
                        channel,
                        "When should this reminder stop being repeated? (\"never\" if not at all)"
                    )
                    response = await self.wait_for_message(
                        author=author, channel=channel)
                    await self.safe_delete_message(msg)
                    if (response.content.lower().strip() in ("n", "no", "nope",
                                                             "never")):
                        await self.safe_delete_message(response)
                        reminder_end = None
                        break

                    reminder_end = datetime(
                        *cal.parse(response.content.strip().lower())[0][:6])
                    if reminder_end is not None:
                        await self.safe_delete_message(response)
                        break

                    await self.safe_delete_message(response)

            # action
            def check(m):
                try:
                    if 4 > int(m.content) > 0:
                        return True
                    else:
                        return False
                except:
                    return False

            selected_action = 0

            while True:
                msg = await self.safe_send_message(
                    channel,
                    "**Select one:**\n```\n1: Send a message\n2: Play a video\n3: Play an alarm sound```"
                )
                response = await self.wait_for_message(
                    author=author, channel=channel)
                await self.safe_delete_message(msg)
                selected_action = int(response.content)

                if selected_action is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # action 1 (message)
            if selected_action == 1:
                action_message = "Your reminder *****REMOVED***reminder.name***REMOVED***** is due"
                action_channel = None
                action_delete_after = 0
                action_delete_previous = False

                # find message
                msg = await self.safe_send_message(
                    channel, "What should the message say?")
                response = await self.wait_for_message(
                    author=author, channel=channel)
                action_message = response.content
                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find channel
                while action_channel is None:
                    msg = await self.safe_send_message(
                        channel,
                        "To which channel should the message be sent?\nPossible inputs:\n\n:white_small_square: Channel id or channel name\n:white_small_square: \"me\" for a private message\n:white_small_square: \"this\" to select the current channel\n:white_small_square: You can also @mention people or #mention a channel"
                    )
                    response = await self.wait_for_message(
                        author=author, channel=channel)

                    if len(response.channel_mentions) > 0:
                        action_channel = response.channel_mentions[0]
                    elif len(response.mentions) > 0:
                        action_channel = response.mentions[0]
                    elif response.content.lower().strip() == "me":
                        action_channel = author
                    elif response.content.lower().strip() == "this":
                        action_channel = channel
                    else:
                        return Response("not yet implemented :P")

                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)

                # find delete after time
                def check(m):
                    try:
                        if m.content.lower().strip() in [
                                "never", "no"
                        ] or int(m.content.strip()) >= 0:
                            return True
                        else:
                            return False
                    except:
                        return False

                msg = await self.safe_send_message(
                    channel,
                    "After how many seconds should the message be deleted? (\"never\" for not at all)"
                )
                response = await self.wait_for_message(
                    author=author, channel=channel, check=check)
                if response.content.lower().strip() in ["never", "no"]:
                    action_delete_after = 0
                else:
                    action_delete_after = int(response.content.strip())

                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find if delete old message
                if reminder_repeat is not None:
                    msg = await self.safe_send_message(
                        channel,
                        "Before sending a new message, should the old one be deleted?"
                    )
                    response = await self.wait_for_message(
                        author=author, channel=channel)
                    if response.content.lower().strip() in ["y", "yes"]:
                        action_delete_previous = True

                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)

                reminder_action = Action(
                    channel=action_channel,
                    msg_content=action_message,
                    delete_msg_after=action_delete_after,
                    delete_old_message=action_delete_previous)

            # action 2 (play url)
            elif selected_action == 2:
                action_source_url = ""
                action_voice_channel = None

                # find video url
                msg = await self.safe_send_message(
                    channel, "What's the url of the video you want to play?")
                response = await self.wait_for_message(
                    author=author, channel=channel)
                action_source_url = response.content
                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find playback channel
                msg = await self.safe_send_message(
                    channel,
                    "To which channel should the video be played?\nPossible inputs:\n\n:white_small_square: Channel id or channel name\n:white_small_square: \"this\" to select your current channel"
                )
                response = await self.wait_for_message(
                    author=author, channel=channel)

                if response.content.lower().strip() == "this":
                    return Response("not yet implemented :P")
                else:
                    return Response("not yet implemented :P")

            # action 3 (play predefined)
            elif selected_action == 3:
                pass

            # finalizing
            self.calendar.create_reminder(
                reminder_name,
                reminder_due,
                reminder_action,
                repeat_every=reminder_repeat,
                repeat_end=reminder_end)
            return Response(
                "Created a reminder called *****REMOVED******REMOVED*****\ndue: ***REMOVED******REMOVED***\nrepeat: ***REMOVED******REMOVED***\nrepeat end: ***REMOVED******REMOVED***\naction: ***REMOVED******REMOVED***".
                format(reminder_name, reminder_due, reminder_repeat,
                       reminder_end, reminder_action))

        elif (command == "list"):
            if len(self.calendar.reminders) < 1:
                return Response("There are no reminders")

            text = ""
            for reminder in self.calendar.reminders:
                text += "****REMOVED***.name***REMOVED****\n".format(reminder)

            return Response(text)
        # return
        #
        # real_args = " ".join(leftover_args).split(",")
        #
        # if len(real_args) < 2:
        #     return Response("You're a failure!")
        #
        # reminder_name = real_args[0].strip()
        # due_date_string = real_args[1].strip().lower()
        #
        # repeat_date_string = real_args[2].strip().lower() if len(real_args) > 2 else None
        # repeat_end_string = real_args[3].strip().lower() if len(real_args) > 3 else None
        #
        # import parsedatetime
        #
        # cal = parsedatetime.Calendar()
        #
        # due_date = datetime(*cal.parse(due_date_string)[0][:6])
        # repeat_every = datetime(*cal.parse(repeat_date_string)[0][:6]) - datetime.now() if repeat_date_string is not None else None
        # repeat_end = datetime(*cal.parse(repeat_end_string)[0][:6]) if repeat_end_string is not None else None
        #
        # self.log("\n***REMOVED******REMOVED***\nin: ***REMOVED******REMOVED***;\nevery: ***REMOVED******REMOVED***;\nuntil: ***REMOVED******REMOVED***".format(reminder_name, due_date, repeat_every, repeat_end))
        #
        # action = Action(
        #     channel=channel, msg_content="**Reminder ***REMOVED***reminder.name***REMOVED*** is due!**", delete_msg_after=5)
        #
        # self.calendar.create_reminder(reminder_name, due_date, action, repeat_every=repeat_every, repeat_end=repeat_end)
        # return Response("Got it, I'll remind you!")

    async def cmd_moveus(self, channel, server, author, message,
                         leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***moveus <channel name>`
        ///|Explanation
        Move everyone in your current channel to another one!
        """

        if len(leftover_args) < 1:
            return Response("You need to provide a target channel")

        search_channel = " ".join(leftover_args)
        if search_channel.lower().strip() == "home":
            search_channel = "Giesela's reign"

        if author.voice.voice_channel is None:
            return Response(
                "You're incredibly incompetent to do such a thing!")

        author_channel = author.voice.voice_channel.id

        target_channel = self.get_channel(search_channel)
        if target_channel is None:
            for chnl in server.channels:
                if chnl.name == search_channel and chnl.type == ChannelType.voice:
                    target_channel = chnl
                    break

        if target_channel is None:
            return Response(
                "Can't resolve the target channel!", delete_after=20)

        self.log("there are ***REMOVED******REMOVED*** members in this voice chat".format(
            len(self.get_channel(author_channel).voice_members)))

        s = 0
        for voice_member in self.get_channel(author_channel).voice_members:
            await self.move_member(voice_member, target_channel)
            s += 1

        self.log("moved ***REMOVED******REMOVED*** users from ***REMOVED******REMOVED*** to ***REMOVED******REMOVED***".format(
            s, author.voice.voice_channel, target_channel))

        if server.me.voice.voice_channel.id == self.get_channel(
                author_channel).id:
            self.log("moving myself")
            await self.get_voice_client(target_channel)

    async def cmd_mobile(self, message, channel, player, server,
                         leftover_args):
        """
        ///|Users
        `***REMOVED***command_prefix***REMOVED***mobile`
        ///|Send a message to a user
        `***REMOVED***command_prefix***REMOVED***mobile message <@mention> <message>`
        """

        if len(leftover_args) < 1:
            count = len(self.socket_server.connections)
            return Response("There ***REMOVED******REMOVED*** currently ***REMOVED******REMOVED*** mobile user***REMOVED******REMOVED***".format(
                "is" if count == 1 else "are", count, "s"
                if count != 1 else ""))
        elif leftover_args[0].lower() == "message":
            if len(leftover_args) < 2:
                return Response("No message provided!")
            else:
                if len(message.mentions) < 1:
                    return Response("No mentions")
                else:
                    target_user = message.mentions[0].id
                msg = " ".join(leftover_args[2:])

                res = self.socket_server.send_message(target_user, msg)
                if res is None:
                    return Response(
                        "This user probably doesn't have the app open")
                elif not res:
                    return Response(
                        "Something went wrong when trying to contact the user")
                else:
                    return Response("Successfully sent the message!")

    @block_user
    async def cmd_execute(self,
                          channel,
                          author,
                          server,
                          leftover_args,
                          player=None):
        statement = " ".join(leftover_args)
        statement = statement.replace("/n/", "\n")
        statement = statement.replace("/t/", "\t")
        beautiful_statement = "```python\n***REMOVED******REMOVED***\n```".format(statement)

        statement = "async def func():\n***REMOVED******REMOVED***".format(indent(statement, "\t"))

        env = ***REMOVED******REMOVED***
        env.update(globals())
        env.update(locals())

        try:
            exec(statement, env)
        except SyntaxError as e:
            return Response(
                "**While compiling the statement the following error occured**\n```python\n***REMOVED******REMOVED***\n```".
                format(str(e)))

        func = env["func"]
        try:
            ret = await func()
        except Exception as e:
            return Response(
                "**While executing the statement the following error occured**\n```python\n***REMOVED******REMOVED***\n```".
                format(str(e)))

        return Response("**CODE**\n***REMOVED******REMOVED***\n**RESULT**\n```python\n***REMOVED******REMOVED***\n```".format(
            beautiful_statement, str(ret)))

    @command_info("2.0.3", 1487538840, ***REMOVED***
        "3.3.7": (1497471402, "changed command from \"skipto\" to \"seek\"")
    ***REMOVED***)
    async def cmd_seek(self, player, timestamp):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***seek <timestamp>`
        ///|Explanation
        Go to the given timestamp formatted (minutes:seconds)
        """

        secs = parse_timestamp(timestamp)
        if secs is None:
            return Response(
                "Please provide a valid timestamp", delete_after=20)

        if player.current_entry is None:
            return Response("Nothing playing!", delete_after=20)

        if not player.goto_seconds(secs):
            return Response(
                "Timestamp exceeds song duration!", delete_after=20)

    @command_info("2.2.1", 1493975700)
    async def cmd_fwd(self, player, timestamp):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***fwd <timestamp>`
        ///|Explanation
        Forward <timestamp> into the current entry
        """

        secs = parse_timestamp(timestamp)
        if secs is None:
            return Response(
                "Please provide a valid timestamp", delete_after=20)

        if player.current_entry is None:
            return Response("Nothing playing!", delete_after=20)

        if not player.goto_seconds(player.progress + secs):
            return Response(
                "Timestamp exceeds song duration!", delete_after=20)

    @command_info("2.2.1", 1493975700,
                  ***REMOVED***"3.4.3": (1497609912, "Can now rewind past the last song")***REMOVED***)
    async def cmd_rwd(self, player, timestamp=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***rwd [timestamp]`
        ///|Explanation
        Rewind <timestamp> into the current entry or if the current entry is a timestamp-entry, rewind to the previous song
        """

        if player.current_entry is None:
            return Response("Nothing playing!", delete_after=20)

        if timestamp is None:
            if player.current_entry.provides_timestamps:
                current_song = player.current_entry.get_current_song_from_timestamp(
                    player.progress)
                ind = current_song["index"]
                local_progress, duration = player.current_entry.get_local_progress(
                    player.progress)
                if ind == 0:
                    secs = 0
                else:
                    if local_progress < 15:
                        secs = player.current_entry.get_timestamped_song(
                            ind - 1)["start"]
                    else:
                        secs = current_song["start"]

            else:
                return Response("Please provide a valid timestamp")
        else:
            secs = player.progress - parse_timestamp(timestamp)

        if not secs:
            if not player.playlist.history:
                return Response(
                    "Please provide a valid timestamp (no history to rewind into)",
                    delete_after=20)
            else:
                last_entry = player.playlist.history[
                    0]  # just replay the last entry
                player.play_entry(last_entry)
                return

        if secs < 0:
            if not player.playlist.history:
                secs = 0
            else:
                last_entry = player.playlist.history[0]
                last_entry.start_seconds = last_entry.end_seconds + \
                    secs  # since secs is negative I can just add it
                if last_entry.start_seconds < 0:
                    # mostly because I'm lazy
                    return Response(
                        "I won't go further back than one song, that's just mad"
                    )
                player.play_entry(last_entry)
                return

        if not player.goto_seconds(secs):
            return Response(
                "Timestamp exceeds song duration!", delete_after=20)

    async def cmd_register(self, author, server, token):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***register <token>

        Use this function to register your phone in order to control the musicbot
        """

        if await self.socket_server.register_handler(token, server.id,
                                                     author.id):
            return Response("Successful")
        else:
            return Response("Something went wrong there")

    async def cmd_disconnect(self, server):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***disconnect

        Make the bot leave his current voice channel.
        """
        await self.disconnect_voice_client(server)
        return Response(":hear_no_evil:", delete_after=20)

    async def cmd_restart(self, channel):
        await self.safe_send_message(channel, ":wave:")
        await self.disconnect_all_voice_clients()
        raise exceptions.RestartSignal

    @owner_only
    async def cmd_countmsgs(self, server, author, channel_id, number):
        alphabet = list("abcdefghijklmnopqrstuvwxyz")

        def index_to_alphabet(ind):
            if ind < len(alphabet):
                return alphabet[ind].upper()

            remainder = ind % len(alphabet)
            return index_to_alphabet(ind -
                                     remainder) + alphabet[remainder].upper()

        msgs_by_member = ***REMOVED******REMOVED***
        msgs_by_date = OrderedDict()
        answers_by_date = OrderedDict()
        channel = server.get_channel(channel_id)
        last_msg = None
        last_answer = None
        spam = 0

        async for msg in self.logs_from(channel, limit=int(number)):
            increment = 1
            if last_msg is not None and msg.author.id == last_msg.author.id and abs(
                    (last_msg.timestamp - msg.timestamp).total_seconds()) < 10:
                spam += 1
                last_msg = msg
                increment = 0

            if last_answer is None or last_answer.author != msg.author:
                dt = answers_by_date.get(
                    "***REMOVED***0.day:0>2***REMOVED***/***REMOVED***0.month:0>2***REMOVED***/***REMOVED***0.year:0>4***REMOVED***".format(
                        msg.timestamp), ***REMOVED******REMOVED***)
                dt[msg.author.id] = dt.get(msg.author.id, 0) + increment
                answers_by_date["***REMOVED***0.day:0>2***REMOVED***/***REMOVED***0.month:0>2***REMOVED***/***REMOVED***0.year:0>4***REMOVED***".
                                format(msg.timestamp)] = dt
                last_answer = msg

            existing_msgs = msgs_by_member.get(msg.author.id, [0, 0])
            existing_msgs[0] += increment
            existing_msgs[1] += len(re.sub(r"\W", r"", msg.content))
            msgs_by_member[msg.author.id] = existing_msgs
            dt = msgs_by_date.get(
                "***REMOVED***0.day:0>2***REMOVED***/***REMOVED***0.month:0>2***REMOVED***/***REMOVED***0.year:0>4***REMOVED***".format(msg.timestamp),
                ***REMOVED******REMOVED***)
            dt[msg.author.id] = dt.get(msg.author.id, 0) + increment
            msgs_by_date["***REMOVED***0.day:0>2***REMOVED***/***REMOVED***0.month:0>2***REMOVED***/***REMOVED***0.year:0>4***REMOVED***".format(
                msg.timestamp)] = dt
            last_msg = msg

        wb = Workbook()
        ws = wb.active
        ws.title = "Messages"
        ws2 = wb.create_sheet("Answers")
        ws["A2"] = "TOTAL"
        sorted_user_index = ***REMOVED******REMOVED***
        i = 1
        for member in sorted(msgs_by_member):
            data = msgs_by_member[member]
            ws["***REMOVED******REMOVED******REMOVED******REMOVED***".format("A", i)] = server.get_member(
                member
            ).name if server.get_member(member) is not None else "Unknown"
            ws["***REMOVED******REMOVED******REMOVED******REMOVED***".format("B", i)] = data[0]
            ws["***REMOVED******REMOVED******REMOVED******REMOVED***".format("C", i)] = data[1]
            sorted_user_index[member] = index_to_alphabet(i)
            i += 1

        i += 1
        for date in reversed(msgs_by_date.keys()):
            ws["A" + str(i)] = date
            for mem in msgs_by_date[date]:
                ws["***REMOVED******REMOVED******REMOVED******REMOVED***".format(sorted_user_index.get(mem),
                                 i)] = msgs_by_date[date][mem]
            i += 1

        i = 1
        for date in reversed(answers_by_date.keys()):
            ws2["A" + str(i)] = date
            for mem in answers_by_date[date]:
                ws2["***REMOVED******REMOVED******REMOVED******REMOVED***".format(sorted_user_index.get(mem),
                                  i)] = answers_by_date[date][mem]
            i += 1

        wb.save("cache/last_data.xlsx")

        await self.send_file(
            author,
            open("cache/last_data.xlsx", "rb"),
            filename='%s-msgs.xlsx' % (server.name.replace(' ', '_')))

    async def cmd_archivechat(self,
                              server,
                              author,
                              message,
                              placeholder=None,
                              number=1000000):
        if message.channel_mentions is None or len(
                message.channel_mentions) < 1:
            return Response("Stupid duck")

        channel = message.channel_mentions[0]
        msgs = []
        async for msg in self.logs_from(channel, limit=int(number)):
            msg_data = ***REMOVED***
                "name": msg.author.name,
                "timestamp": str(round(msg.timestamp.timestamp())),
                "content": msg.content,
                "attachments": msg.attachments
            ***REMOVED***
            msgs.append(msg_data)

        json.dump(msgs[::-1], open("cache/last_message_archive.json", "w+"))
        await self.send_file(
            author,
            open("cache/last_message_archive.json", "rb"),
            filename='%s-msg-archive.json' % (server.name.replace(' ', '_')))

    @owner_only
    async def cmd_surveyserver(self, server):
        if self.online_loggers.get(server.id, None) is not None:
            return Response("I'm already looking at this server")
        else:
            online_logger = OnlineLogger(self)
            self.online_loggers[server.id] = online_logger
            Settings["online_loggers"] = list(self.online_loggers.keys())
            return Response("okay, okay!")

    def load_online_loggers(self):
        for server_id in Settings.get_setting("online_loggers", default=[]):
            online_logger = OnlineLogger(self)
            self.online_loggers[server_id] = online_logger
            for listener in Settings.get_setting(
                    "online_logger_listeners_" + server_id, default=[]):
                online_logger.add_listener(listener)

    @owner_only
    async def cmd_evalsurvey(self, server, author):
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        online_logger.create_output()
        await self.send_file(
            author,
            open("cache/last_survey_data.xlsx", "rb"),
            filename='%s-survey.xlsx' % (server.name.replace(' ', '_')))
        return Response("There you go, fam", delete_after=10)

    @owner_only
    async def cmd_resetsurvey(self, server):
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        online_logger.reset()
        return Response("Well then")

    async def cmd_notifyme(self, server, author):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***notifyme

        Get notified when someone starts playing
        """
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        if online_logger.add_listener(author.id):
            Settings["online_logger_listeners_" + server.id] = [
                *Settings.get_setting(
                    "online_logger_listeners_" + server.id, default=[]),
                author.id
            ]
            return Response("Got'cha!")
        else:
            try:
                Settings["online_logger_listeners_" + server.id] = [
                    x
                    for x in Settings.get_setting(
                        "online_logger_listeners_" + server.id, default=[])
                    if x != author.id
                ]
            except ValueError:
                pass

            return Response("Nevermore you shall be annoyed!")

    async def cmd_livetranslator(self,
                                 target_language=None,
                                 mode="1",
                                 required_certainty="70"):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***livetranslator [language code] [mode] [required certainty]

        translate every message sent

        modes:
            1: send a message with the translation
            2: replace the original message with the translation
        """

        if target_language is None:
            if self.instant_translate:
                self.instant_translate = False
                return Response("turned off instant translation")
            else:
                return Response(
                    "You should provide the language code you want me to translate to in order for me to work"
                )
        if target_language in [
                'af', 'ar', 'bg', 'bn', 'ca', 'cs', 'cy', 'da', 'de', 'el',
                'en', 'es', 'et', 'fa', 'fi', 'fr', 'gu', 'he', 'hi', 'hr',
                'hu', 'id', 'it', 'ja', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml',
                'mr', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk',
                'sl', 'so', 'sq', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr',
                'uk', 'ur', 'vi', 'zh-cn', 'zh-tw'
        ]:
            self.instant_translate = True
            self.translator.to_lang = target_language
            try:
                mode = int(mode)
            except:
                mode = 1
            if not (0 <= mode <= 2):
                mode = 1
            self.instant_translate_mode = mode

            try:
                required_certainty = int(required_certainty) / 100
            except:
                required_certainty = .7
            if not (0 <= required_certainty <= 1):
                required_certainty = .7

            self.instant_translate_certainty = required_certainty

            return Response("Starting now!")
        else:
            return Response("Please provide the iso format language code")

    async def cmd_translatehistory(self, author, message, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***translatehistory <channel> <start date | number of messages> <target language>`
        ///|Explanation
        Request messages in a channel to be translated.\nYou can specify the amount of messages either by number or by a starting point formated like `DAY/MONTH/YEAR HOUR:MINUTE`
        """
        starting_point = " ".join(leftover_args[1:-1])
        target_language = leftover_args[-1].lower()

        if target_language not in [
                'af', 'ar', 'bg', 'bn', 'ca', 'cs', 'cy', 'da', 'de', 'el',
                'en', 'es', 'et', 'fa', 'fi', 'fr', 'gu', 'he', 'hi', 'hr',
                'hu', 'id', 'it', 'ja', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml',
                'mr', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk',
                'sl', 'so', 'sq', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr',
                'uk', 'ur', 'vi', 'zh-cn', 'zh-tw'
        ]:
            return Response("Please provide the target language")

        if message.channel_mentions is None or len(
                message.channel_mentions) < 1:
            return Response(
                "Please provide a channel to take the messages from",
                delete_after=20)
        channel = message.channel_mentions[0]

        limit = 500
        start_point = None
        try:
            limit = int(starting_point)
        except:
            match = re.match(
                "(\d***REMOVED***1,2***REMOVED***)\/(\d***REMOVED***1,2***REMOVED***)\/(\d***REMOVED***4***REMOVED***).***REMOVED***1***REMOVED***(\d***REMOVED***1,2***REMOVED***):(\d***REMOVED***1,2***REMOVED***)",
                starting_point)
            if match is None:
                return Response(
                    "I don't understand your starting point...\nBe sure to format it like `DAY/MONTH/YEAR HOUR:MINUTE`",
                    delete_after=20)
            day, month, year, hour, minute = match.group(1, 2, 3, 4, 5)
            start_point = datetime(year, month, day, hour, minute)

        em = Embed(title="TRANSLATION")
        translator = Translator(target_language)
        async for message in self.logs_from(
                channel, limit=limit, after=start_point):
            n = "*****REMOVED***0***REMOVED***** - ***REMOVED***1.year:0>4***REMOVED***/***REMOVED***1.month:0>2***REMOVED***/***REMOVED***1.day:0>2***REMOVED*** ***REMOVED***1.hour:0>2***REMOVED***:***REMOVED***1.minute:0>2***REMOVED***".format(
                message.author.display_name, message.timestamp)

            message_content = message.content.strip()
            msg_language, probability = self.lang_identifier.classify(
                message_content)
            self.translator.from_lang = msg_language
            try:
                v = "`***REMOVED******REMOVED***`".format(translator.translate(message_content))
            except:
                continue
            em.add_field(name=n, value=v, inline=False)
        em._fields = em._fields[::-1]
        await self.send_message(author, embed=em)
        return Response("Done!")

    async def cmd_quote(self, author, channel, message, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***quote [#channel] <message id> [message id...]`
        `***REMOVED***command_prefix***REMOVED***quote [#channel] [@mention] \"<message content>\"`
        ///|Explanation
        Quote a message
        """

        quote_to_channel = channel
        target_author = None

        if message.channel_mentions is not None and len(
                message.channel_mentions) > 0:
            channel = message.channel_mentions[0]
            leftover_args = leftover_args[1:]

        if message.mentions is not None and len(message.mentions) > 0:
            target_author = message.mentions[0]
            leftover_args = leftover_args[1:]

        if len(leftover_args) < 1:
            return Response("Please specify the message you want to quote")

        message_content = " ".join(leftover_args)
        if (message_content[0] == "\"" and
                message_content[-1] == "\"") or re.search(
                    r"\D", message_content) is not None:
            message_content = message_content.replace("\"", "")
            # if datetime.now() < datetime(2017, 5, 15):
            # return Response("Well sorry, this way of quoting is not yet
            # available. It will be released in
            # ***REMOVED******REMOVED***".format(format_time((datetime(2017, 5, 15) -
            # datetime.now()).total_seconds(), True, 5, 2, True, True)))
            async for msg in self.logs_from(
                    channel, limit=100000):
                if msg.id != message.id and message_content.lower().strip(
                ) in msg.content.lower().strip():
                    if target_author is None or target_author.id == msg.author.id:
                        leftover_args = [
                            msg.id,
                        ]
                        break
                else:
                    if target_author is not None:
                        return Response(
                            "Didn't find a message with that content from ***REMOVED******REMOVED***".
                            format(target_author.mention))

                return Response(
                    "Didn't find a message that matched this content")

        await self.safe_delete_message(message)
        for message_id in leftover_args:
            try:
                quote_message = await self.get_message(channel, message_id)
            except:
                return Response("Didn't find a message with the id `***REMOVED******REMOVED***`".
                                format(message_id))

            author_data = ***REMOVED***
                "name": quote_message.author.display_name,
                "icon_url": quote_message.author.avatar_url
            ***REMOVED***
            embed_data = ***REMOVED***
                "description": quote_message.content,
                "timestamp": quote_message.timestamp,
                "colour": quote_message.author.colour
            ***REMOVED***
            em = Embed(**embed_data)
            em.set_author(**author_data)
            await self.send_message(quote_to_channel, embed=em)
        return

    @command_info("3.2.5", 1496428380, ***REMOVED***
        "3.3.9": (1497521393, "Added edit sub-command"),
        "3.4.1": (1497550771,
                  "Added the filter \"mine\" to the listing function"),
        "3.4.6": (1497617827,
                  "when listing bookmarks, they musn't be \"inline\"."),
        "3.5.8": (1497827057, "Editing bookmarks now works as expected")
    ***REMOVED***)
    async def cmd_bookmark(self, author, player, leftover_args):
        """
        ///|Creation
        ***REMOVED***command_prefix***REMOVED***bookmark [name] [timestamp]
        ///|Explanation
        Create a new bookmark for the current entry. If no name is provided the entry's title will be used and if there's no timestamp provided the current timestamp will be used.
        ///|Using
        ***REMOVED***command_prefix***REMOVED***bookmark <id | name>
        ///|Editing
        ***REMOVED***command_prefix***REMOVED***bookmark edit <id> [new name] [new timestamp]
        ///|Listing
        ***REMOVED***command_prefix***REMOVED***bookmark list [mine]
        ///|Removal
        ***REMOVED***command_prefix***REMOVED***bookmark remove <id | name>
        """
        if len(leftover_args) > 0:
            arg = leftover_args[0].lower()
            if arg in ["list", "showall"]:
                em = Embed(title="Bookmarks")
                bookmarks = bookmark.all_bookmarks

                if "mine" in leftover_args:
                    bookmarks = filter(
                        lambda x: bookmark.get_bookmark(
                            x)["author_id"] == author.id,
                        bookmarks)

                for bm in bookmarks:
                    bm_name = bm["name"]
                    bm_author = self.get_global_user(
                        bm["author_id"]).display_name
                    bm_timestamp = to_timestamp(bm["timestamp"])
                    bm_id = bm["id"]
                    t = "*****REMOVED******REMOVED*****".format(bm_name)
                    v = "`***REMOVED******REMOVED***` starting at `***REMOVED******REMOVED***` *by* *****REMOVED******REMOVED*****".format(
                        bm_id, bm_timestamp, bm_author)
                    em.add_field(name=t, value=v, inline=False)
                return Response(embed=em)
            elif arg in ["remove", "delete"]:
                if len(leftover_args) < 2:
                    return Response("Please provide an id or a name")
                bm = bookmark.get_bookmark(" ".join(leftover_args[1:]))
                if not bm:
                    return Response("Didn't find a bookmark with that query")
                if bookmark.remove_bookmark(bm["id"]):
                    return Response("Removed bookmark `***REMOVED******REMOVED***`".format(bm["name"]))
                else:
                    return Response("Something went wrong")
            elif arg in ["edit", "change"]:
                if len(leftover_args) < 2:
                    return Response("Please provide an id")

                bm_id = leftover_args[1]
                if bm_id not in bookmark:
                    return Response(
                        "No bookmark with id `***REMOVED******REMOVED***` found".format(bm_id))

                if len(leftover_args) < 3:
                    return Response(
                        "Please also specify what you want to change")

                new_timestamp = parse_timestamp(leftover_args[-1])
                if new_timestamp is not None:  # 0 evaluates to false so I need to check this oldschool-like
                    new_name = " ".join(
                        leftover_args[2:-1]) if len(leftover_args) > 3 else None
                else:
                    new_name = " ".join(leftover_args[2:])

                if bookmark.edit_bookmark(bm_id, new_name, new_timestamp):
                    return Response(
                        "Successfully edited bookmark `***REMOVED******REMOVED***`".format(bm_id))
                else:
                    return Response("Something went wrong while editing `***REMOVED******REMOVED***`".
                                    format(bm_id))
            else:
                bm = bookmark.get_bookmark(" ".join(leftover_args))
                if bm:
                    player.playlist._add_entry(
                        URLPlaylistEntry.from_dict(player.playlist, bm[
                            "entry"]))
                    return Response("Loaded bookmark `***REMOVED***0***REMOVED***` by *****REMOVED***1***REMOVED*****".
                                    format(bm["name"],
                                           self.get_global_user(
                                               bm["author_id"]).display_name))
                else:
                    bm_timestamp = player.progress
                    bm_name = None
                    if len(leftover_args) > 1:
                        timestamp = parse_timestamp(leftover_args[-1])
                        if timestamp:
                            bm_timestamp = timestamp
                        bm_name = " ".join(
                            leftover_args[:-1]) if timestamp else " ".join(
                                leftover_args)
                    else:
                        timestamp = parse_timestamp(leftover_args[-1])
                        if timestamp:
                            bm_timestamp = timestamp
                        else:
                            bm_name = " ".join(leftover_args)

                    id = bookmark.add_bookmark(
                        player.current_entry, bm_timestamp, author.id, bm_name)
                    return Response(
                        "Created a new bookmark with the id `***REMOVED***0***REMOVED***` (\"***REMOVED***2***REMOVED***\", `***REMOVED***3***REMOVED***`)\nUse `***REMOVED***1***REMOVED***bookmark ***REMOVED***0***REMOVED***` to load it ".
                        format(id, self.config.command_prefix, bm_name,
                               to_timestamp(bm_timestamp)))

        else:
            if player.current_entry:
                id = bookmark.add_bookmark(player.current_entry,
                                           player.progress, author.id)
                return Response(
                    "Created a new bookmark with the id `***REMOVED***0***REMOVED***`\nUse `***REMOVED***1***REMOVED***bookmark ***REMOVED***0***REMOVED***` to load it ".
                    format(id, self.config.command_prefix))
            else:
                return await self.cmd_bookmark(author, player, [
                    "list",
                ])

    @owner_only
    async def cmd_blockcommand(self, command, leftover_args):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***blockcommand <command> <reason>`
        ///|Explanation
        Block a command
        """
        if len(leftover_args) < 1:
            return Response("Reason plz")

        reason = " ".join(leftover_args)

        if command.lower() in self.blocked_commands:
            self.blocked_commands.pop(command.lower())
            return Response("Block lifted")
        else:
            self.blocked_commands[command.lower()] = reason
            return Response("Blocked command")

    @command_info("3.4.0", 1497533758, ***REMOVED***
        "3.4.8":
        (1497650090,
         "When showing changelogs, two logs can't be on the same line anymore")
    ***REMOVED***)
    async def cmd_commandinfo(self, command):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***commandinfo <command>`
        ///|Explanation
        More information on a command
        """

        c_info = getattr(self, "cmd_" + command, None)
        if not c_info:
            return Response(
                "Couldn't find a command called \"***REMOVED******REMOVED***\"".format(command))

        try:
            em = Embed(title=command.upper(), colour=hex_to_dec("ffd700"))
            em.add_field(
                name="Version `***REMOVED******REMOVED***`".format(c_info.version),
                value="`***REMOVED******REMOVED***`\nCommand has been added".format(c_info.timestamp),
                inline=False)

            for cl in c_info.changelog:
                v, t, l = cl
                em.add_field(
                    name="Version `***REMOVED******REMOVED***`".format(v),
                    value="`***REMOVED******REMOVED***`\n***REMOVED******REMOVED***".format(t, l),
                    inline=False)

            return Response(embed=em)
        except:
            return Response(
                "Couldn't find any information on the `***REMOVED******REMOVED***` command".format(
                    command))

    @command_info("3.5.6", 1497819288, ***REMOVED***
        "3.6.2": (1497978696, "references are now clickable")
    ***REMOVED***)
    async def cmd_version(self, channel):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***version`
        ///|Explanation
        Some more informat about the current version and what's to come.
        """

        await self.send_typing(channel)
        v_code, v_name = BOTVERSION.split("_")
        dev_code, dev_name = get_dev_version()
        changelog = get_dev_changelog()

        desc = "Current Version is `***REMOVED******REMOVED***`\nDevelopment is at `***REMOVED******REMOVED***`\n\n**What's to come:**\n\n".format(
            BOTVERSION, dev_code + "_" + dev_name)
        desc += "\n".join("● " + l for l in changelog)
        em = Embed(title="Version " + v_name, description=desc,
                   url="https://siku2.github.io/Giesela", colour=hex_to_dec("67BE2E"))

        return Response(embed=em)

    @command_info("3.5.7", 1497823283)
    async def cmd_interact(self, channel, message):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***interact <query>`
        ///|Explanation
        Use every day language to control Giesela
        ///|Disclaimer
        **Help out with the development of a "smarter" Giesela by testing out this new future!**
        """

        await self.send_typing(channel)

        matcher = "^\***REMOVED******REMOVED***?interact".format(self.config.command_prefix)
        query = re.sub(matcher, "", message.content, flags=re.MULTILINE)
        if not query:
            return Response("Please provide a query for me to work with")

        print("[INTERACT] \"***REMOVED******REMOVED***\"".format(query))

        params = ***REMOVED***"v": "18/06/2017", "q": query***REMOVED***
        headers = ***REMOVED***"Authorization": "Bearer 47J7GSQPY2DJPLGUNFZVNHAMGU7ARCRD"***REMOVED***
        resp = requests.get("https://api.wit.ai/message",
                            params=params, headers=headers)
        data = resp.json()
        entities = data["entities"]

        msg = ""

        for entity, data in entities.items():
            d = data[0]
            msg += "*****REMOVED******REMOVED***** [***REMOVED******REMOVED***] (***REMOVED******REMOVED***% sure)\n".format(entity,
                                                     d["value"], round(d["confidence"] * 100, 1))

        return Response(msg)

    # @command_info("3.6.2", 1497979507)
    # async def cmd_ping(self, channel):
    #     """
    #     ///|Usage
    #     `***REMOVED***command_prefix***REMOVED***ping
    #     ///|Explanation
    #     Get Giesela's latency
    #     """
    #     start_time = time.time()
    #     msg = await self.safe_send_message(channel, "Calculating ping...")
    #     ping = time.time() - start_time
    #     await self.safe_edit_message(msg, "The ping is `***REMOVED******REMOVED***s`".format(round(ping, 2)))

    @owner_only
    async def cmd_shutdown(self, channel):
        await self.safe_send_message(channel, ":wave:")
        await self.disconnect_all_voice_clients()
        raise exceptions.TerminateSignal

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

        # gif_match = re.match(r"((?:http|https):\/\/.+\.gif)", message_content)
        # if gif_match is not None:
        #     gif_link = gif_match.group(1)
        #     em = Embed()
        #     em.set_image(url=gif_link)
        #     em.set_author(name=message.author.display_name,
        #                   icon_url=message.author.avatar_url)
        #     await self.send_message(message.channel, embed=em)
        #     await self.safe_delete_message(message)
        #     return

        if message.author.id in self.users_in_menu:
            self.log("User is currently in a menu")
            return

        if not message_content.startswith(self.config.command_prefix):
            # if message.channel.id in self.config.bound_channels and message.author != self.user and not message.author.bot:
            # await self.cmd_c(message.author, message.channel,
            # message_content.split())
            try:
                msg_language, probability = self.lang_identifier.classify(
                    message_content)

                if probability > self.instant_translate_certainty and self.instant_translate and msg_language != self.translator.to_lang and message.author != self.user:
                    self.translator.from_lang = msg_language
                    if self.instant_translate_mode == 1:
                        await self.safe_send_message(
                            message.channel, "Translation: `***REMOVED******REMOVED***`".format(
                                self.translator.translate(message_content)))
                    elif self.instant_translate_mode == 2:
                        em = Embed(
                            colour=message.author.colour,
                            description=self.translator.translate(
                                message_content))
                        em.set_author(
                            name=message.author.display_name,
                            icon_url=message.author.avatar_url)
                        # em.set_footer(text=message.content)
                        await self.send_message(message.channel, embed=em)
                        await self.safe_delete_message(message)
                        return
            except:
                raise
                self.log("couldn't translate the message")

            if self.config.owned_channels and message.channel.id not in self.config.owned_channels:
                return

        # don't react to own messages or messages from bots
        if message.author == self.user or message.author.bot:
            # self.log("Ignoring command from myself (%s)" %
            #          message.content)
            return

        command, *args = message_content.split()
        command = command[len(self.config.command_prefix):].lower().strip(
        ) if message_content.startswith(
            self.config.command_prefix) else command.lower().strip()

        handler = getattr(self, 'cmd_%s' % command, None)
        if not handler:
            return

        if command in self.blocked_commands:
            await self.send_message(message.channel,
                                    self.blocked_commands[command])
            return

        if message.channel.is_private:
            if not (message.author.id == self.config.owner_id and command ==
                    'joinserver') and not command in self.privateChatCommands:
                await self.send_message(
                    message.channel,
                    'You cannot use this command in private messages.')
                return

        if message.author.id in self.blacklist and message.author.id != self.config.owner_id:
            self.log("[User blacklisted] ***REMOVED***0.id***REMOVED***/***REMOVED***0.name***REMOVED*** (***REMOVED***1***REMOVED***)".format(
                message.author, message_content))
            return

        else:
            self.log("[Command] ***REMOVED***0.id***REMOVED***/***REMOVED***0.name***REMOVED*** (***REMOVED***1***REMOVED***)".format(
                message.author, message_content))

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()

        # noinspection PyBroadException
        try:
            handler_kwargs = ***REMOVED******REMOVED***
            if params.pop('message', None):
                handler_kwargs['message'] = message

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('server', None):
                handler_kwargs['server'] = message.server

            if params.pop('player', None):
                handler_kwargs['player'] = await self.get_player(
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
                return await self.cmd_help(message.channel, [
                    command,
                ])

            response = await handler(**handler_kwargs)
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
                    embed=response.embed)

        except (exceptions.CommandError, exceptions.HelpfulError,
                exceptions.ExtractionError) as e:
            self.log("***REMOVED***0.__class__***REMOVED***: ***REMOVED***0.message***REMOVED***".format(e))

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

    async def on_reaction_add(self, reaction, user):
        if reaction.message.author == self.user:
            await self.safe_send_message(user, "I hate you too!")
            return

        # await self.add_reaction (reaction.message, discord.Emoji (name = "Bubo", id = "234022157569490945", server = reaction.message.server))
        # self.log ("***REMOVED******REMOVED*** (***REMOVED******REMOVED***)".format (reaction.emoji.name, reaction.emoji.id))
        # self.log ("***REMOVED******REMOVED***".format (reaction.emoji))

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

        if sum(1 for m in my_voice_channel.voice_members
               if m != after.server.me):
            if player.is_paused:
                self.log("[AUTOPAUSE] Unpausing")
                player.resume()
                self.socket_server.threaded_broadcast_information()
        else:
            if player.is_playing:
                self.log("[AUTOPAUSE] Pausing")
                player.pause()
                self.socket_server.threaded_broadcast_information()

    async def on_server_update(self,
                               before: discord.Server,
                               after: discord.Server):
        if before.region != after.region:
            self.log("[Servers] \"%s\" changed regions: %s -> %s" %
                     (after.name, before.region, after.region))

            await self.reconnect_voice_client(after)

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
            timestamp = "***REMOVED***0.hour:0>2***REMOVED***:***REMOVED***0.minute:0>2***REMOVED***".format(datetime.now())
            notification = None
            mem_name = "\"***REMOVED******REMOVED***\"".format(after.display_name) if len(
                after.display_name.split()) > 1 else after.display_name
            if before.status != after.status:
                notification = "`***REMOVED******REMOVED***` ***REMOVED******REMOVED*** ***REMOVED******REMOVED***".format(timestamp, mem_name, ***REMOVED***
                    discord.Status.online:
                    "came **online**",
                    discord.Status.offline:
                    "went **offline**",
                    discord.Status.idle:
                    "went **away**",
                    discord.Status.dnd:
                    "doesn't want to be disturbed"
                ***REMOVED***[after.status])
            if before.game != after.game:
                text = ""
                if after.game is None:
                    text = "stopped playing *****REMOVED******REMOVED*****".format(before.game.name)
                else:
                    text = "started playing *****REMOVED******REMOVED*****".format(after.game.name)
                if notification is None:
                    notification = "`***REMOVED******REMOVED***` ***REMOVED******REMOVED*** ***REMOVED******REMOVED***".format(timestamp, mem_name,
                                                       text)
                else:
                    notification += "\nand ***REMOVED******REMOVED***".format(text)

            if before.voice.voice_channel != after.voice.voice_channel:
                text = ""
                if after.voice.voice_channel is None:
                    text = "quit *****REMOVED******REMOVED***** (voice channel)".format(
                        before.voice.voice_channel.name)
                else:
                    text = "joined *****REMOVED******REMOVED***** (voice channel)".format(
                        after.voice.voice_channel.name)
                if notification is None:
                    notification = "`***REMOVED******REMOVED***` ***REMOVED******REMOVED*** ***REMOVED******REMOVED***".format(timestamp, mem_name,
                                                       text)
                else:
                    notification += "\nand ***REMOVED******REMOVED***".format(text)

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
