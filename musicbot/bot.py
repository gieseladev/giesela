import datetime
import inspect
import json
import operator
import os
import shlex
import shutil
import sys
import time
import traceback
import urllib
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from random import choice, shuffle
from textwrap import dedent

import aiohttp
import discord
import goslate
import newspaper
import tungsten
import wikipedia
from discord import Embed, utils
from discord.enums import ChannelType
from discord.ext.commands.bot import _get_variable
from discord.object import Object
from discord.voice_client import VoiceClient
from moviepy import editor, video
from openpyxl import Workbook
from pyshorteners import Shortener

import asyncio
import configparser

from . import downloader, exceptions
from .cleverbot import CleverWrap
from .config import Config, ConfigDefaults
from .constants import VERSION as BOTVERSION
from .constants import AUDIO_CACHE_PATH, DISCORD_MSG_CHAR_LIMIT
from .games.game_2048 import Game2048
from .games.game_cah import GameCAH
from .games.game_hangman import GameHangman
from .langid import LanguageIdentifier, model
from .logger import OnlineLogger, log
from .nine_gag import *
from .opus_loader import load_opus_lib
from .papers import Papers
from .permissions import Permissions, PermissionsDefaults
from .player import MusicPlayer
from .playlist import Playlist
from .radios import Radios
from .random_sets import RandomSets
from .reminder import Action, Calendar
from .saved_playlists import Playlists
from .socket_server import SocketServer
from .translate import Translator
from .utils import (escape_dis, format_time, load_file, paginate, prettydate,
                    random_line, sane_round_int, write_file)

load_opus_lib()


class SkipState:

    def __init__(self):
        self.skippers = set()
        self.skip_msgs = set()

    @property
    def skip_count(self):
        return len(self.skippers)

    def reset(self):
        self.skippers.clear()
        self.skip_msgs.clear()

    def add_skipper(self, skipper, msg):
        self.skippers.add(skipper)
        self.skip_msgs.add(msg)
        return self.skip_count


class Response:

    def __init__(self, content, reply=False, delete_after=0):
        self.content = content
        self.reply = reply
        self.delete_after = delete_after


class MusicBot(discord.Client):
    trueStringList = ["true", "1", "t", "y", "yes", "yeah",
                      "yup", "certainly", "uh-huh", "affirmitive", "activate"]
    channelFreeCommands = ["say"]
    privateChatCommands = ["c", "ask", "requestfeature", "random",
                           "translate", "help", "say", "broadcast", "news", "game", "wiki", "cah", "execute"]
    lonelyModeRunning = False

    def __init__(self, config_file=ConfigDefaults.options_file, random_file=ConfigDefaults.random_sets, radios_file=ConfigDefaults.radios_file, papers_file=ConfigDefaults.papers_file, playlists_file=ConfigDefaults.playlists_file, perms_file=PermissionsDefaults.perms_file):
        self.players = {}
        self.the_voice_clients = {}
        self.locks = defaultdict(asyncio.Lock)
        self.voice_client_connect_lock = asyncio.Lock()
        self.voice_client_move_lock = asyncio.Lock()

        self.config = Config(config_file)
        self.papers = Papers(papers_file)
        self.radios = Radios(radios_file)
        self.playlists = Playlists(playlists_file)
        self.random_sets = RandomSets(random_file)
        self.online_loggers = {}
        self.cah = GameCAH(self)
        self.permissions = Permissions(
            perms_file, grant_all=[self.config.owner_id])

        self.blacklist = set(load_file(self.config.blacklist_file))
        self.autoplaylist = load_file(self.config.auto_playlist_file)
        self.downloader = downloader.Downloader(download_folder='audio_cache')
        # self.radio = Radio()
        self.calendar = Calendar(self)
        self.socket_server = SocketServer(self)
        self.shortener = Shortener(
            "Google", api_key="AIzaSyCU67YMHlfTU_PX2ngHeLd-_dUds-m502k")
        self.translator = Translator("en")
        self.lang_identifier = LanguageIdentifier.from_modelstring(
            model, norm_probs=True)

        self.exit_signal = None
        self.init_ok = False
        self.cached_client_id = None
        self.chatters = {}

        if not self.autoplaylist:
            log("Warning: Autoplaylist is empty, disabling.")
            self.config.auto_playlist = False

        # TODO: Do these properly
        ssd_defaults = {'last_np_msg': None, 'auto_paused': False}
        self.server_specific_data = defaultdict(lambda: dict(ssd_defaults))

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += ' MusicBot/%s' % BOTVERSION
        self.instant_translate = False
        self.instant_translate_mode = 1

    # TODO: Add some sort of `denied` argument for a message to send when
    # someone else tries to use it
    def owner_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Only allow the owner to use these commands
            orig_msg = _get_variable('message')

            if not orig_msg or orig_msg.author.id == self.config.owner_id:
                return await func(self, *args, **kwargs)
            else:
                raise exceptions.PermissionsError(
                    "only the owner can use this command", expire_in=30)

        return wrapper

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
            return discord.utils.find(lambda m: m.id == self.config.owner_id, self.get_all_members())

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
            self.log(
                "Found owner in \"%s\", attempting to join..." % owner.voice_channel.name)
            # TODO: Effort
            await self.cmd_summon(owner.voice_channel, owner, None)
            return owner.voice_channel

    async def _autojoin_channels(self, channels):
        joined_servers = []

        for channel in channels:
            if channel.server in joined_servers:
                log("Already joined a channel in %s, skipping" %
                    channel.server.name)
                continue

            if channel and channel.type == discord.ChannelType.voice:
                self.log("Attempting to autojoin %s in %s" %
                         (channel.name, channel.server.name))

                chperms = channel.permissions_for(channel.server.me)

                if not chperms.connect:
                    self.log(
                        "Cannot join channel \"%s\", no permission." % channel.name)
                    continue

                elif not chperms.speak:
                    self.log(
                        "Will not join channel \"%s\", no permission to speak." % channel.name)
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
                    log("Failed to join", channel.name)

            elif channel:
                log("Not joining %s on %s, that's a text channel." %
                    (channel.name, channel.server.name))

            else:
                log("Invalid channel thing: " + channel)

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    # TODO: Check to see if I can just move this to on_message after the
    # response check
    async def _manual_delete_check(self, message, *, quiet=False):
        if self.config.delete_invoking:
            await self.safe_delete_message(message, quiet=quiet)

    async def _check_ignore_non_voice(self, msg):
        vc = msg.server.me.voice_channel

        # If we've connected to a voice chat and we're in the same voice
        # channel
        if not vc or vc == msg.author.voice_channel:
            return True
        else:
            raise exceptions.PermissionsError(
                "you cannot use this command when not in the voice channel (%s)" % vc.name, expire_in=30)

    async def generate_invite_link(self, *, permissions=None, server=None):
        if not self.cached_client_id:
            appinfo = await self.application_info()
            self.cached_client_id = appinfo.id

        return discord.utils.oauth_url(self.cached_client_id, permissions=permissions, server=server)

    async def get_voice_client(self, channel):
        if isinstance(channel, Object):
            channel = self.get_channel(channel.id)

        if getattr(channel, 'type', ChannelType.text) != ChannelType.voice:
            raise AttributeError('Channel passed must be a voice channel')

        with await self.voice_client_connect_lock:
            server = channel.server
            if server.id in self.the_voice_clients:
                return self.the_voice_clients[server.id]

            s_id = self.ws.wait_for(
                'VOICE_STATE_UPDATE', lambda d: d.get('user_id') == self.user.id)
            _voice_data = self.ws.wait_for(
                'VOICE_SERVER_UPDATE', lambda d: True)

            await self.ws.voice_state(server.id, channel.id)

            s_id_data = await asyncio.wait_for(s_id, timeout=10, loop=self.loop)
            voice_data = await asyncio.wait_for(_voice_data, timeout=10, loop=self.loop)
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
                    log("Attempting connection...")
                    await asyncio.wait_for(voice_client.connect(), timeout=10, loop=self.loop)
                    log("Connection established.")
                    break
                except:
                    traceback.print_exc()
                    log("Failed to connect, retrying (%s/%s)..." %
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
            log("Error disconnecting during reconnect")
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

    async def get_player(self, channel, create=False) -> MusicPlayer:
        server = channel.server

        if server.id not in self.players:
            if not create:
                raise exceptions.CommandError(
                    'The bot is not in a voice channel.  '
                    'Use %ssummon to summon it to your voice channel.' % self.config.command_prefix)

            voice_client = await self.get_voice_client(channel)

            playlist = Playlist(self)
            player = MusicPlayer(self, voice_client, playlist) \
                .on('play', self.on_player_play) \
                .on('resume', self.on_player_resume) \
                .on('pause', self.on_player_pause) \
                .on('stop', self.on_player_stop) \
                .on('finished-playing', self.on_player_finished_playing) \
                .on('entry-added', self.on_player_entry_added)

            player.skip_state = SkipState()
            self.players[server.id] = player

        return self.players[server.id]

    async def on_player_play(self, player, entry):
        await self.update_now_playing(entry)
        player.skip_state.reset()

        channel = entry.meta.get('channel', None)
        author = entry.meta.get('author', None)

        if channel and author:
            last_np_msg = self.server_specific_data[
                channel.server]['last_np_msg']
            if last_np_msg and last_np_msg.channel == channel:

                async for lmsg in self.logs_from(channel, limit=1):
                    if lmsg != last_np_msg and last_np_msg:
                        await self.safe_delete_message(last_np_msg)
                        self.server_specific_data[
                            channel.server]['last_np_msg'] = None
                    break  # This is probably redundant

            if self.config.now_playing_mentions:
                newmsg = '%s - your song **%s** is now playing in %s!' % (
                    entry.meta['author'].mention, entry.title, player.voice_client.channel.name)
            else:
                newmsg = 'Now playing in %s: **%s**' % (
                    player.voice_client.channel.name, entry.title)

            if self.server_specific_data[channel.server]['last_np_msg']:
                self.server_specific_data[channel.server]['last_np_msg'] = await self.safe_edit_message(last_np_msg, newmsg, send_if_fail=True)
            else:
                self.server_specific_data[channel.server]['last_np_msg'] = await self.safe_send_message(channel, newmsg)
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
                    info = await self.downloader.safe_extract_info(player.playlist.loop, song_url, download=False, process=False)

                    if not info:
                        self.autoplaylist.remove(song_url)
                        self.log(
                            "[Info] Removing unplayable song from autoplaylist: %s" % song_url)
                        write_file(self.config.auto_playlist_file,
                                   self.autoplaylist)
                        continue

                    if info.get('entries', None):  # or .get('_type', '') == 'playlist'
                        pass  # Wooo playlist
                        # Blarg how do I want to do this

                    # TODO: better checks here
                    try:
                        await player.playlist.add_entry(song_url, channel=None, author=None)
                    except exceptions.ExtractionError as e:
                        log("Error adding song from autoplaylist:", e)
                        continue

                    break

                if not self.autoplaylist:
                    log(
                        "[Warning] No playable songs in the autoplaylist, disabling.")
                    self.config.auto_playlist = False

    async def on_player_entry_added(self, playlist, entry, **_):
        pass

    async def on_server_join(self, server):
        for channel in server.channels:
            if channel.type is not ChannelType.text:
                continue

            msg = await self.safe_send_message(channel, "Hello there,\nMy name is {}!\n\n*Type {}help to find out more.*".format(self.user.mention, self.config.command_prefix))
            if msg is not None:
                return

    async def update_now_playing(self, entry=None, is_paused=False):
        game = None

        if self.user.bot:
            activeplayers = sum(
                1 for p in self.players.values() if p.is_playing)
            if activeplayers > 1:
                game = discord.Game(name="music on %s servers" % activeplayers)
                entry = None

            elif activeplayers == 1:
                player = discord.utils.get(
                    self.players.values(), is_playing=True)
                entry = player.current_entry

        if entry:
            prefix = u'\u275A\u275A ' if is_paused else ''

            if type(entry).__name__ == "StreamPlaylistEntry" and entry.radio_station_data is not None:
                name = u'{}'.format(entry.radio_station_data.name)[:128]
                game = discord.Game(name=name)
            else:
                name = u'{}{}'.format(prefix, entry.title)[:128]
                game = discord.Game(name=name)

        await self.change_presence(game=game)

    async def safe_send_message(self, dest, content, *, max_letters=DISCORD_MSG_CHAR_LIMIT, split_message=True, tts=False, expire_in=0, also_delete=None, quiet=False):
        msg = None
        try:
            if split_message and len(content) > max_letters:
                self.log("Message too long, splitting it up")
                msgs = paginate(content, length=DISCORD_MSG_CHAR_LIMIT)

                for msg in msgs:
                    nmsg = await self.send_message(dest, msg, tts=tts)

                    if nmsg and expire_in:
                        asyncio.ensure_future(
                            self._wait_delete_msg(nmsg, expire_in))

                    if also_delete and isinstance(also_delete, discord.Message):
                        asyncio.ensure_future(
                            self._wait_delete_msg(also_delete, expire_in))
            else:
                msg = await self.send_message(dest, content, tts=tts)

                if msg and expire_in:
                    asyncio.ensure_future(
                        self._wait_delete_msg(msg, expire_in))

                if also_delete and isinstance(also_delete, discord.Message):
                    asyncio.ensure_future(
                        self._wait_delete_msg(also_delete, expire_in))

        except discord.Forbidden:
            if not quiet:
                self.log(
                    "Warning: Cannot send message to %s, no permission" % dest.name)

        except discord.NotFound:
            if not quiet:
                self.log(
                    "Warning: Cannot send message to %s, invalid channel?" % dest.name)

        return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await self.delete_message(message)

        except discord.Forbidden:
            if not quiet:
                self.log(
                    "Warning: Cannot delete message \"%s\", no permission" % message.clean_content)

        except discord.NotFound:
            if not quiet:
                self.log(
                    "Warning: Cannot delete message \"%s\", message not found" % message.clean_content)

    async def safe_edit_message(self, message, new, *, send_if_fail=False, quiet=False):
        try:
            return await self.edit_message(message, new)

        except discord.NotFound:
            if not quiet:
                self.log(
                    "Warning: Cannot edit message \"%s\", message not found" % message.clean_content)
            if send_if_fail:
                if not quiet:
                    log("Sending instead")
                return await self.safe_send_message(message.channel, new)

    def log(self, content, *, end='\n', flush=True):
        sys.stdout.buffer.write((content + end).encode('utf-8', 'replace'))
        if flush:
            sys.stdout.flush()

    async def send_typing(self, destination):
        try:
            return await super().send_typing(destination)
        except discord.Forbidden:
            if self.config.debug_mode:
                log("Could not send typing to %s, no permssion" % destination)

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
                log("Error in cleanup:", e)

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
            log("Exception in", event)
            log(ex.message)

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
        log('\rConnected!  Musicbot v%s\n' % BOTVERSION)

        if self.config.owner_id == self.user.id:
            raise exceptions.HelpfulError(
                "Your OwnerID is incorrect or you've used the wrong credentials.",

                "The bot needs its own account to function.  "
                "The OwnerID is the id of the owner, not the bot.  "
                "Figure out which one is which and use the correct information.")

        self.init_ok = True

        self.log("Bot:   %s/%s#%s" %
                 (self.user.id, self.user.name, self.user.discriminator))

        owner = self._get_owner(voice=True) or self._get_owner()
        if owner and self.servers:
            self.log("Owner: %s/%s#%s\n" %
                     (owner.id, owner.name, owner.discriminator))

            log('Server List:')
            [self.log(' - ' + s.name) for s in self.servers]

        elif self.servers:
            log("Owner could not be found on any server (id: %s)\n" %
                self.config.owner_id)

            log('Server List:')
            [self.log(' - ' + s.name) for s in self.servers]

        else:
            log("Owner unknown, bot is not on any servers.")
            if self.user.bot:
                log(
                    "\nTo make the bot join a server, paste this link in your browser.")
                log("Note: You should be logged into your main account and have \n"
                    "manage server permissions on the server you want the bot to join.\n")
                log("    " + await self.generate_invite_link())

        log()

        if self.config.bound_channels:
            chlist = set(self.get_channel(i)
                         for i in self.config.bound_channels if i)
            chlist.discard(None)
            invalids = set()

            invalids.update(c for c in chlist if c.type ==
                            discord.ChannelType.voice)
            chlist.difference_update(invalids)
            self.config.bound_channels.difference_update(invalids)

            log("Bound to text channels:")
            [self.log(' - %s/%s' % (ch.server.name.strip(),
                                    ch.name.strip())) for ch in chlist if ch]

            if invalids and self.config.debug_mode:
                log("\nNot binding to voice channels:")
                [self.log(
                    ' - %s/%s' % (ch.server.name.strip(), ch.name.strip())) for ch in invalids if ch]

            log()

        else:
            log("Not bound to any text channels")

        if self.config.autojoin_channels:
            chlist = set(self.get_channel(i)
                         for i in self.config.autojoin_channels if i)
            chlist.discard(None)
            invalids = set()

            invalids.update(c for c in chlist if c.type ==
                            discord.ChannelType.text)
            chlist.difference_update(invalids)
            self.config.autojoin_channels.difference_update(invalids)

            log("Autojoining voice chanels:")
            [self.log(' - %s/%s' % (ch.server.name.strip(),
                                    ch.name.strip())) for ch in chlist if ch]

            if invalids and self.config.debug_mode:
                log("\nCannot join text channels:")
                [self.log(
                    ' - %s/%s' % (ch.server.name.strip(), ch.name.strip())) for ch in invalids if ch]

            autojoin_channels = chlist

        else:
            log("Not autojoining any voice channels")
            autojoin_channels = set()

        log()
        log("Options:")

        self.log("  Command prefix: " + self.config.command_prefix)
        log("  Default volume: %s%%" % int(self.config.default_volume * 100))
        log("  Skip threshold: %s votes or %s%%" % (
            self.config.skips_required, self._fixg(self.config.skip_ratio_required * 100)))
        log("  Now Playing @mentions: " +
            ['Disabled', 'Enabled'][self.config.now_playing_mentions])
        log("  Auto-Summon: " + ['Disabled',
                                 'Enabled'][self.config.auto_summon])
        log("  Auto-Playlist: " + ['Disabled',
                                   'Enabled'][self.config.auto_playlist])
        log("  Auto-Pause: " + ['Disabled',
                                'Enabled'][self.config.auto_pause])
        log("  Delete Messages: " +
            ['Disabled', 'Enabled'][self.config.delete_messages])
        if self.config.delete_messages:
            log("    Delete Invoking: " +
                ['Disabled', 'Enabled'][self.config.delete_invoking])
        log("  Debug Mode: " + ['Disabled',
                                'Enabled'][self.config.debug_mode])
        log("  Downloaded songs will be %s" %
            ['deleted', 'saved'][self.config.save_videos])
        log()

        # maybe option to leave the ownerid blank and generate a random command for the owner to use
        # wait_for_message is pretty neato

        if not self.config.save_videos and os.path.isdir(AUDIO_CACHE_PATH):
            if self._delete_old_audiocache():
                log("Deleting old audio cache")
            else:
                log("Could not delete old audio cache, moving on.")

        if self.config.autojoin_channels:
            await self._autojoin_channels(autojoin_channels)

        elif self.config.auto_summon:
            log("Attempting to autosummon...", flush=True)

            # waitfor + get value
            owner_vc = await self._auto_summon()

            if owner_vc:
                # TODO: Change this to "Joined server/channel"
                log("Done!", flush=True)
                if self.config.auto_playlist:
                    log("Starting auto-playlist")
                    await self.on_player_finished_playing(await self.get_player(owner_vc))
            else:
                log("Owner not found in a voice channel, could not autosummon.")

        log()
        # t-t-th-th-that's all folks!

    async def socket_summon(self, server_id):
        server = self.get_server(server_id)
        if server == None:
            return

        channels = server.channels
        target_channel = None
        max_members = 0

        for ch in channels:
            if len(ch.voice_members) > max_members:
                target_channel = ch
                max_members = len(ch.voice_members)
                if any([x.bot for x in ch.voice_members]):
                    max_members -= .5

        if target_channel == None:
            return

        voice_client = self.the_voice_clients.get(server.id, None)
        if voice_client is not None and voice_client.channel.server == server:
            await self.move_voice_client(target_channel)
            return

        chperms = target_channel.permissions_for(server.me)

        if not chperms.connect:
            return
        elif not chperms.speak:
            return

        await self.get_player(target_channel, create=True)
        self.socket_server.threaded_broadcast_information()

    async def cmd_help(self, channel, leftover_args):
        """
        ///|Usage
        `{command_prefix}help [command]`

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
                em = Embed(title="**{}**".format(command.upper()))
                fields = documentation.split("///")
                if len(fields) < 2:  # backward compatibility
                    return Response("```\n{}```".format(dedent(cmd.__doc__).format(command_prefix=self.config.command_prefix)), delete_after=60)

                for field in fields:
                    if field is None or field is "":
                        continue
                    inline = True
                    if field.startswith("(NL)"):
                        inline = False
                        field = field[4:]
                        # print(field)

                    match = re.match("\|(.+)\n((?:.|\n)+)", field)
                    if match is None:
                        continue
                    title, text = match.group(1, 2)

                    em.add_field(name="**{}**".format(title),
                                 value=text, inline=inline)
                await self.send_message(channel, embed=em)
                return
                # return
                # Response("```\n{}```".format(dedent(cmd.__doc__).format(command_prefix=self.config.command_prefix)),delete_after=60)
            else:
                # return Response("No such command", delete_after=10)
                self.log("Didn't find a command like that")
                config = configparser.ConfigParser(interpolation=None)
                if not config.read("config/helper.ini", encoding='utf-8'):
                    await self.safe_send_message(channel, "Something went wrong here. I cannot help you with this")
                    return

                funcs = {}

                for section in config.sections():
                    tags = json.loads(config.get(section, "tags"))
                    funcs[str(section)] = 0
                    for arg in leftover_args:
                        if arg.lower() in tags:
                            funcs[str(section)] += 1

                funcs = {k: v for k, v in funcs.items() if v > 0}

                if len(funcs) <= 0:
                    await self.safe_send_message(channel, "Didn't find anything that may satisfy your wishes")
                    return

                sorted_funcs = sorted(
                    funcs.items(), key=operator.itemgetter(1), reverse=True)

                resp_str = "**You might wanna take a look at these functions:**\n\n"

                for func in sorted_funcs[:3]:
                    cmd = getattr(self, 'cmd_' + func[0], None)
                    helpText = dedent(cmd.__doc__).format(
                        command_prefix=self.config.command_prefix)
                    resp_str += "*{0}:*\n```\n{1}```\n\n".format(
                        func[0], helpText)

                await self.safe_send_message(channel, resp_str, expire_in=60)

        else:
            helpmsg = "**Commands**\n```"
            commands = []

            for att in dir(self):
                if att.startswith('cmd_') and att != 'cmd_help':
                    command_name = att.replace('cmd_', '').lower()
                    commands.append("{}{}".format(
                        self.config.command_prefix, command_name))

            helpmsg += ", ".join(commands)
            helpmsg += "```"
            helpmsg += "A Discord Bot by siku2"

            return Response(helpmsg, reply=True, delete_after=60)

    async def cmd_blacklist(self, message, user_mentions, option, something):
        """
        ///|Usage
        {command_prefix}blacklist [ + | - | add | remove ] @UserName [@UserName2 ...]
        ///|Explanation
        Add or remove users to the blacklist.
        """

        if not user_mentions:
            raise exceptions.CommandError("No users listed.", expire_in=20)

        if option not in ['+', '-', 'add', 'remove']:
            raise exceptions.CommandError(
                'Invalid option "%s" specified, use +, -, add, or remove' % option, expire_in=20
            )

        for user in user_mentions.copy():
            if user.id == self.config.owner_id:
                log("[Commands:Blacklist] The owner cannot be blacklisted.")
                user_mentions.remove(user)

        old_len = len(self.blacklist)

        if option in ['+', 'add']:
            self.blacklist.update(user.id for user in user_mentions)

            write_file(self.config.blacklist_file, self.blacklist)

            return Response(
                '%s users have been added to the blacklist' % (
                    len(self.blacklist) - old_len),
                reply=True, delete_after=10
            )

        else:
            if self.blacklist.isdisjoint(user.id for user in user_mentions):
                return Response('none of those users are in the blacklist.', reply=True, delete_after=10)

            else:
                self.blacklist.difference_update(
                    user.id for user in user_mentions)
                write_file(self.config.blacklist_file, self.blacklist)

                return Response(
                    '%s users have been removed from the blacklist' % (
                        old_len - len(self.blacklist)),
                    reply=True, delete_after=10
                )

    async def cmd_id(self, author, user_mentions):
        """
        ///|Usage
        {command_prefix}id [@user]
        ///|Explanation
        Tells the user their id or the id of another user.
        """
        if not user_mentions:
            return Response('your id is `%s`' % author.id, reply=True, delete_after=35)
        else:
            usr = user_mentions[0]
            return Response("%s's id is `%s`" % (usr.name, usr.id), reply=True, delete_after=35)

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
                "Bot accounts can't use invite links!  Click here to invite me: \n{}".format(
                    url),
                reply=True, delete_after=30
            )

        try:
            if server_link:
                await self.accept_invite(server_link)
                return Response(":+1:")

        except:
            raise exceptions.CommandError(
                'Invalid URL provided:\n{}\n'.format(server_link), expire_in=30)

    async def cmd_play(self, player, channel, author, permissions, leftover_args, song_url):
        """
        Usage:
            {command_prefix}play song_link
            {command_prefix}play text to search for

        Adds the song to the playlist.  If a link is not provided, the first
        result from a youtube search is added to the queue.
        """

        song_url = song_url.strip('<>')

        if permissions.max_songs and player.playlist.count_for_user(author) >= permissions.max_songs:
            raise exceptions.PermissionsError(
                "You have reached your enqueued song limit (%s)" % permissions.max_songs, expire_in=30
            )

        await self.send_typing(channel)

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])

        try:
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=30)

        if not info:
            raise exceptions.CommandError(
                "That video cannot be played.", expire_in=30)

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # log("[Command:play] Searching for \"%s\"" % song_url)
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
                    "You may need to restart the bot if this continues to happen.", expire_in=30
                )

            if not all(info.get('entries', [])):
                # empty list, no data
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
            # Now I could just do: return await self.cmd_play(player, channel, author, song_url)
            # But this is probably fine

        # TODO: Possibly add another check here to see about things like the bandcamp issue
        # TODO: Where ytdl gets the generic extractor version with no
        # processing, but finds two different urls

        if 'entries' in info:
            # I have to do exe extra checks anyways because you can request an
            # arbitrary number of search results
            if not permissions.allow_playlists and ':search' in info['extractor'] and len(info['entries']) > 1:
                raise exceptions.PermissionsError(
                    "You are not allowed to request playlists", expire_in=30)

            # The only reason we would use this over `len(info['entries'])` is
            # if we add `if _` to this one
            num_songs = sum(1 for _ in info['entries'])

            if permissions.max_playlist_length and num_songs > permissions.max_playlist_length:
                raise exceptions.PermissionsError(
                    "Playlist has too many entries (%s > %s)" % (
                        num_songs, permissions.max_playlist_length),
                    expire_in=30
                )

            # This is a little bit weird when it says (x + 0 > y), I might add
            # the other check back in
            if permissions.max_songs and player.playlist.count_for_user(author) + num_songs > permissions.max_songs:
                raise exceptions.PermissionsError(
                    "Playlist entries + your already queued songs reached limit (%s + %s > %s)" % (
                        num_songs, player.playlist.count_for_user(author), permissions.max_songs),
                    expire_in=30
                )

            if info['extractor'].lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
                try:
                    return await self._cmd_play_playlist_async(player, channel, author, permissions, song_url, info['extractor'])
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
                'Gathering playlist information for {} songs{}'.format(
                    num_songs,
                    ', ETA: {} seconds'.format(self._fixg(
                        num_songs * wait_per_song)) if num_songs >= 10 else '.'))

            # We don't have a pretty way of doing this yet.  We need either a loop
            # that sends these every 10 seconds or a nice context manager.
            await self.send_typing(channel)

            # TODO: I can create an event emitter object instead, add event functions, and every play list might be asyncified
            # Also have a "verify_entry" hook with the entry as an arg and
            # returns the entry if its ok

            entry_list, position = await player.playlist.import_from(song_url, channel=channel, author=author)

            tnow = time.time()
            ttime = tnow - t0
            listlen = len(entry_list)
            drop_count = 0

            if permissions.max_song_length:
                for e in entry_list.copy():
                    if e.duration > permissions.max_song_length:
                        player.playlist.entries.remove(e)
                        entry_list.remove(e)
                        drop_count += 1
                        # Im pretty sure there's no situation where this would ever break
                        # Unless the first entry starts being played, which
                        # would make this a race condition
                if drop_count:
                    log("Dropped %s songs" % drop_count)

            log("Processed {} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
                listlen,
                self._fixg(ttime),
                ttime / listlen,
                ttime / listlen - wait_per_song,
                self._fixg(wait_per_song * num_songs))
                )

            await self.safe_delete_message(procmesg)

            if not listlen - drop_count:
                raise exceptions.CommandError(
                    "No songs were added, all songs were over max duration (%ss)" % permissions.max_song_length,
                    expire_in=30
                )

            reply_text = "Enqueued **%s** songs to be played. Position in queue: %s"
            btext = str(listlen - drop_count)

        else:
            if permissions.max_song_length and info.get('duration', 0) > permissions.max_song_length:
                raise exceptions.PermissionsError(
                    "Song duration exceeds limit (%s > %s)" % (
                        info['duration'], permissions.max_song_length),
                    expire_in=30
                )

            try:
                entry, position = await player.playlist.add_entry(song_url, channel=channel, author=author)

            except exceptions.WrongEntryTypeError as e:
                if e.use_url == song_url:
                    log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help.")

                if self.config.debug_mode:
                    log(
                        "[Info] Assumed url \"%s\" was a single entry, was actually a playlist" % song_url)
                    log("[Info] Using \"%s\" instead" % e.use_url)

                return await self.cmd_play(player, channel, author, permissions, leftover_args, e.use_url)

            reply_text = "Enqueued **%s** to be played. Position in queue: %s"
            btext = entry.title

        if position == 1 and player.is_stopped:
            position = 'Up next!'
            reply_text %= (btext, position)

        else:
            try:
                time_until = await player.playlist.estimate_time_until(position, player)
                reply_text += ' - estimated time until playing: %s'
            except:
                traceback.print_exc()
                time_until = ''

            reply_text %= (btext, position, time_until)

        return Response(reply_text, delete_after=30)

    async def cmd_stream(self, player, channel, author, permissions, song_url):
        """
        Usage:
            {command_prefix}stream media_link

        Enqueue a media stream.
        This could mean an actual stream like Twitch, Youtube Gaming or even a radio stream, or simply streaming
        media without predownloading it.
        """

        song_url = song_url.strip('<>')

        if permissions.max_songs and player.playlist.count_for_user(author) >= permissions.max_songs:
            raise exceptions.PermissionsError(
                "You have reached your enqueued song limit (%s)" % permissions.max_songs, expire_in=30
            )

        await self.send_typing(channel)
        await player.playlist.add_stream_entry(song_url, channel=channel, author=author)

        return Response(":+1:", delete_after=6)

    async def forceplay(self, player, leftover_args, song_url):
        song_url = song_url.strip('<>')

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])

        try:
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=30)

        if not info:
            raise exceptions.CommandError(
                "That video cannot be played.", expire_in=30)

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # log("[Command:play] Searching for \"%s\"" % song_url)
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
                    "You may need to restart the bot if this continues to happen.", expire_in=30
                )

            if not all(info.get('entries', [])):
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)

        if 'entries' in info:
            if info['extractor'].lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
                try:
                    return await self._cmd_play_playlist_async(player, channel, author, permissions, song_url, info['extractor'])
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
                    log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help.")

                return await self.forceplay(player, leftover_args, e.use_url)

    async def get_play_entry(self, player, channel, author, leftover_args, song_url):
        song_url = song_url.strip('<>')

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])

        try:
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=30)

        if not info:
            raise exceptions.CommandError(
                "That video cannot be played.", expire_in=30)

        # abstract the search handling away from the user
        # our ytdl options allow us to use search strings as input urls
        if info.get('url', '').startswith('ytsearch'):
            # log("[Command:play] Searching for \"%s\"" % song_url)
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
                    "You may need to restart the bot if this continues to happen.", expire_in=30
                )

            if not all(info.get('entries', [])):
                # empty list, no data
                return

            song_url = info['entries'][0]['webpage_url']
            info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
            # Now I could just do: return await self.cmd_play(player, channel, author, song_url)
            # But this is probably fine

        if 'entries' in info:
            # The only reason we would use this over `len(info['entries'])` is
            # if we add `if _` to this one
            num_songs = sum(1 for _ in info['entries'])

            if info['extractor'].lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
                try:
                    # MAGIC
                    return await self._get_play_playlist_async_entries(player, channel, author, song_url, info['extractor'])
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

            entry_list = await player.playlist.entries_import_from(song_url, channel=channel, author=author)

            tnow = time.time()
            ttime = tnow - t0
            listlen = len(entry_list)
            drop_count = 0

            log("Processed {} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
                listlen,
                self._fixg(ttime),
                ttime / listlen,
                ttime / listlen - wait_per_song,
                self._fixg(wait_per_song * num_songs))
                )

            reply_text = "Enqueued **%s** songs to be played. Position in queue: %s"
            btext = str(listlen - drop_count)
            return entry_list

        else:
            try:
                return [await player.playlist.get_entry(song_url, channel=channel, author=author)]

            except exceptions.WrongEntryTypeError as e:
                if e.use_url == song_url:
                    log(
                        "[Warning] Determined incorrect entry type, but suggested url is the same.  Help.")

                if self.config.debug_mode:
                    log(
                        "[Info] Assumed url \"%s\" was a single entry, was actually a playlist" % song_url)
                    log("[Info] Using \"%s\" instead" % e.use_url)

                return await self.cmd_play(player, channel, author, permissions, leftover_args, e.use_url)

        self.log("I reached code which I shouldn't have...")

    async def _get_play_playlist_async_entries(self, player, channel, author, playlist_url, extractor_type):
        info = await self.downloader.extract_info(player.playlist.loop, playlist_url, download=False, process=False)

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
                    'Error handling playlist %s queuing.' % playlist_url, expire_in=30)

        elif extractor_type.lower() in ['soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.entries_async_process_sc_bc_playlist(
                    playlist_url, channel=channel, author=author)
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url, expire_in=30)

        songs_processed = len(entries_added)
        drop_count = 0
        skipped = False

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2

        # This is technically inaccurate since bad songs are ignored but still
        # take up time
        log("Processed {}/{} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
            songs_processed,
            num_songs,
            self._fixg(ttime),
            ttime / num_songs,
            ttime / num_songs - wait_per_song,
            self._fixg(wait_per_song * num_songs))
            )

        if not songs_added:
            basetext = "No songs were added, all songs were over max duration (%ss)" % permissions.max_song_length
            if skipped:
                basetext += "\nAdditionally, the current song was skipped for being too long."

            raise exceptions.CommandError(basetext, expire_in=30)

        return entries_added

    async def _cmd_play_playlist_async(self, player, channel, author, permissions, playlist_url, extractor_type):
        """
        Secret handler to use the async wizardry to make playlist queuing non-"blocking"
        """

        await self.send_typing(channel)
        info = await self.downloader.extract_info(player.playlist.loop, playlist_url, download=False, process=False)

        if not info:
            raise exceptions.CommandError("That playlist cannot be played.")

        num_songs = sum(1 for _ in info['entries'])
        t0 = time.time()

        busymsg = await self.safe_send_message(
            channel, "Processing %s songs..." % num_songs)  # TODO: From playlist_title
        await self.send_typing(channel)

        entries_added = 0
        if extractor_type == 'youtube:playlist':
            try:
                entries_added = await player.playlist.async_process_youtube_playlist(
                    playlist_url, channel=channel, author=author)
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url, expire_in=30)

        elif extractor_type.lower() in ['soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.async_process_sc_bc_playlist(
                    playlist_url, channel=channel, author=author)
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                traceback.print_exc()
                raise exceptions.CommandError(
                    'Error handling playlist %s queuing.' % playlist_url, expire_in=30)

        songs_processed = len(entries_added)
        drop_count = 0
        skipped = False

        if permissions.max_song_length:
            for e in entries_added.copy():
                if e.duration > permissions.max_song_length:
                    try:
                        player.playlist.entries.remove(e)
                        entries_added.remove(e)
                        drop_count += 1
                    except:
                        pass

            if drop_count:
                log("Dropped %s songs" % drop_count)

            if player.current_entry and player.current_entry.duration > permissions.max_song_length:
                await self.safe_delete_message(self.server_specific_data[channel.server]['last_np_msg'])
                self.server_specific_data[channel.server]['last_np_msg'] = None
                skipped = True
                player.skip()
                entries_added.pop()

        await self.safe_delete_message(busymsg)

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2
        # TODO: actually calculate wait per song in the process function and
        # return that too

        # This is technically inaccurate since bad songs are ignored but still
        # take up time
        log("Processed {}/{} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
            songs_processed,
            num_songs,
            self._fixg(ttime),
            ttime / num_songs,
            ttime / num_songs - wait_per_song,
            self._fixg(wait_per_song * num_songs))
            )

        if not songs_added:
            basetext = "No songs were added, all songs were over max duration (%ss)" % permissions.max_song_length
            if skipped:
                basetext += "\nAdditionally, the current song was skipped for being too long."

            raise exceptions.CommandError(basetext, expire_in=30)

        return Response("Enqueued {} songs to be played in {} seconds".format(
            songs_added, self._fixg(ttime, 1)), delete_after=30)

    async def cmd_search(self, player, channel, author, permissions, leftover_args):
        """
        Usage:
            {command_prefix}search [service] [number] query

        Searches a service for a video and adds it to the queue.
        - service: any one of the following services:
            - youtube (yt) (default if unspecified)
            - soundcloud (sc)
            - yahoo (yh)
        - number: return a number of video results and waits for user to choose one
          - defaults to 1 if unspecified
          - note: If your search query starts with a number,
                  you must put your query in quotes
            - ex: {command_prefix}search 2 "I ran seagulls"
        """

        if permissions.max_songs and player.playlist.count_for_user(author) > permissions.max_songs:
            raise exceptions.PermissionsError(
                "You have reached your playlist item limit (%s)" % permissions.max_songs,
                expire_in=30
            )

        def argcheck():
            if not leftover_args:
                raise exceptions.CommandError(
                    "Please specify a search query.\n%s" % dedent(
                        self.cmd_search.__doc__.format(command_prefix=self.config.command_prefix)),
                    expire_in=60
                )

        argcheck()

        try:
            leftover_args = shlex.split(' '.join(leftover_args))
        except ValueError:
            raise exceptions.CommandError(
                "Please quote your search query properly.", expire_in=30)

        service = 'youtube'
        items_requested = 5
        max_items = 10  # this can be whatever, but since ytdl uses about 1000, a small number might be better
        services = {
            'youtube': 'ytsearch',
            'soundcloud': 'scsearch',
            'yahoo': 'yvsearch',
            'yt': 'ytsearch',
            'sc': 'scsearch',
            'yh': 'yvsearch'
        }

        if leftover_args[0] in services:
            service = leftover_args.pop(0)
            argcheck()

        if leftover_args[0].isdigit():
            items_requested = int(leftover_args.pop(0))
            argcheck()

            if items_requested > max_items:
                raise exceptions.CommandError(
                    "You cannot search for more than %s videos" % max_items)

        # Look jake, if you see this and go "what the fuck are you doing"
        # and have a better idea on how to do this, i'd be delighted to know.
        # I don't want to just do ' '.join(leftover_args).strip("\"'")
        # Because that eats both quotes if they're there
        # where I only want to eat the outermost ones
        if leftover_args[0][0] in '\'"':
            lchar = leftover_args[0][0]
            leftover_args[0] = leftover_args[0].lstrip(lchar)
            leftover_args[-1] = leftover_args[-1].rstrip(lchar)

        search_query = '%s%s:%s' % (
            services[service], items_requested, ' '.join(leftover_args))

        search_msg = await self.send_message(channel, "Searching for videos...")
        await self.send_typing(channel)

        try:
            info = await self.downloader.extract_info(player.playlist.loop, search_query, download=False, process=True)

        except Exception as e:
            await self.safe_edit_message(search_msg, str(e), send_if_fail=True)
            return
        else:
            await self.safe_delete_message(search_msg)

        if not info:
            return Response("No videos found.", delete_after=30)

        def check(m):
            return (
                m.content.lower()[0] in 'yn' or
                # hardcoded function name weeee
                m.content.lower().startswith('{}{}'.format(self.config.command_prefix, 'search')) or
                m.content.lower().startswith('exit'))

        for e in info['entries']:
            result_message = await self.safe_send_message(channel, "Result %s/%s: %s" % (
                info['entries'].index(e) + 1, len(info['entries']), e['webpage_url']))

            confirm_message = await self.safe_send_message(channel, "Is this ok? Type `y`, `n` or `exit`")
            response_message = await self.wait_for_message(30, author=author, channel=channel, check=check)

            if not response_message:
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(confirm_message)
                return Response("Ok nevermind.", delete_after=30)

            # They started a new search query so lets clean up and bugger off
            elif response_message.content.startswith(self.config.command_prefix) or \
                    response_message.content.lower().startswith('exit'):

                await self.safe_delete_message(result_message)
                await self.safe_delete_message(confirm_message)
                return

            if response_message.content.lower().startswith('y'):
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(confirm_message)
                await self.safe_delete_message(response_message)

                await self.cmd_play(player, channel, author, permissions, [], e['webpage_url'])

                return Response("Alright, coming right up!", delete_after=30)
            else:
                await self.safe_delete_message(result_message)
                await self.safe_delete_message(confirm_message)
                await self.safe_delete_message(response_message)

        return Response("Oh well :frowning:", delete_after=30)

    async def cmd_np(self, player, channel, server, message):
        """
        ///|Usage
        {command_prefix}np
        ///|Explanation
        Displays the current song in chat.
        """

        if player.current_entry:
            if type(player.current_entry).__name__ == "StreamPlaylistEntry":
                if player.current_entry.radio_station_data is not None:
                    return Response("Playing *radio* **{}** for {}".format(player.current_entry.radio_station_data.name, format_time(player.progress)))
                else:
                    return Response(
                        'Playing live stream: {} for {}'.format(
                            player.current_entry.title, format_time(player.progress)),
                        delete_after=30
                    )

            if self.server_specific_data[server]['last_np_msg']:
                await self.safe_delete_message(self.server_specific_data[server]['last_np_msg'])
                self.server_specific_data[server]['last_np_msg'] = None

            song_progress = str(
                timedelta(seconds=player.progress)).lstrip('0').lstrip(':')
            end_seconds = player.current_entry.end_seconds if player.current_entry.end_seconds is not None else player.current_entry.duration
            song_total = str(timedelta(seconds=end_seconds)).lstrip(
                '0').lstrip(':')
            prog_str = '`[%s/%s]`' % (song_progress, song_total)

            prog_bar_len = 20
            prog_full_char = "■"
            prog_empty_char = "□"
            progress_perc = (player.progress /
                             end_seconds) if end_seconds > 0 else 0
            prog_bar_str = ""

            for i in range(prog_bar_len):
                if i < prog_bar_len * progress_perc:
                    prog_bar_str += prog_full_char
                else:
                    prog_bar_str += prog_empty_char

            if player.current_entry.meta.get('channel', False) and player.current_entry.meta.get('author', False):
                np_text = "Now Playing: **%s** added by **%s** %s\n%s" % (
                    player.current_entry.title, player.current_entry.meta['author'].name, prog_str, prog_bar_str)
            else:
                np_text = "Now Playing: **%s** %s\n%s" % (
                    player.current_entry.title, prog_str, prog_bar_str)

            self.server_specific_data[server]['last_np_msg'] = await self.safe_send_message(channel, np_text)
            await self._manual_delete_check(message)
        else:
            return Response(
                'There are no songs queued! Queue something with {}play.'.format(
                    self.config.command_prefix),
                delete_after=30
            )

    async def cmd_summon(self, channel, author, voice_channel):
        """
        Usage:
            {command_prefix}summon

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
            self.log(
                "Cannot join channel \"%s\", no permission." % author.voice_channel.name)
            return Response(
                "```Cannot join channel \"%s\", no permission.```" % author.voice_channel.name,
                delete_after=25
            )

        elif not chperms.speak:
            self.log(
                "Will not join channel \"%s\", no permission to speak." % author.voice_channel.name)
            return Response(
                "```Will not join channel \"%s\", no permission to speak.```" % author.voice_channel.name,
                delete_after=25
            )

        player = await self.get_player(author.voice_channel, create=True)

        if player.is_stopped:
            player.play()

        if self.config.auto_playlist:
            await self.on_player_finished_playing(player)

    async def cmd_pause(self, player):
        """
        Usage:
            {command_prefix}pause

        Pauses playback of the current song.
        """

        if player.is_playing:
            player.pause()

        else:
            raise exceptions.CommandError(
                'Player is not playing.', expire_in=30)

    async def cmd_resume(self, player):
        """
        Usage:
            {command_prefix}resume

        Resumes playback of a paused song.
        """

        if player.is_paused:
            player.resume()

        else:
            raise exceptions.CommandError(
                'Player is not paused.', expire_in=30)

    async def cmd_shuffle(self, channel, player):
        """
        Usage:
            {command_prefix}shuffle

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

    async def cmd_clear(self, player, author):
        """
        Usage:
            {command_prefix}clear

        Clears the playlist.
        """

        player.playlist.clear()
        return Response(':put_litter_in_its_place:', delete_after=20)

    async def cmd_skip(self, player, channel, author, message, permissions, voice_channel):
        """
        Usage:
            {command_prefix}skip

        Skips the current song when enough votes are cast, or by the bot owner.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't skip! The player is not playing!", expire_in=20)

        if not player.current_entry:
            if player.playlist.peek():
                if player.playlist.peek()._is_downloading:
                    # log(player.playlist.peek()._waiting_futures[0].__dict__)
                    return Response("The next song (%s) is downloading, please wait." % player.playlist.peek().title)

                elif player.playlist.peek().is_downloaded:
                    log("The next song will be played shortly.  Please wait.")
                else:
                    log("Something odd is happening.  "
                        "You might want to restart the bot if it doesn't start working.")
            else:
                log("Something strange is happening.  "
                    "You might want to restart the bot if it doesn't start working.")

        if author.id == self.config.owner_id \
                or permissions.instaskip \
                or author == player.current_entry.meta.get('author', None):

            player.skip()  # check autopause stuff here
            await self._manual_delete_check(message)
            return

        # TODO: ignore person if they're deaf or take them out of the list or something?
        # Currently is recounted if they vote, deafen, then vote

        num_voice = sum(1 for m in voice_channel.voice_members if not (
            m.deaf or m.self_deaf or m.id in [self.config.owner_id, self.user.id]))

        num_skips = player.skip_state.add_skipper(author.id, message)

        skips_remaining = min(self.config.skips_required,
                              sane_round_int(num_voice * self.config.skip_ratio_required)) - num_skips

        if skips_remaining <= 0:
            player.skip()  # check autopause stuff here
            return Response(
                'your skip for **{}** was acknowledged.'
                '\nThe vote to skip has been passed.{}'.format(
                    player.current_entry.title,
                    ' Next song coming up!' if player.playlist.peek() else ''
                ),
                reply=True,
                delete_after=20
            )

        else:
            # TODO: When a song gets skipped, delete the old x needed to skip
            # messages
            return Response(
                'your skip for **{}** was acknowledged.'
                '\n**{}** more {} required to vote to skip this song.'.format(
                    player.current_entry.title,
                    skips_remaining,
                    'person is' if skips_remaining == 1 else 'people are'
                ),
                reply=True,
                delete_after=20
            )

    async def cmd_volume(self, message, player, leftover_args):
        """
        Usage:
            {command_prefix}volume (+/-)[volume]

        Sets the playback volume. Accepted values are from 1 to 100.
        Putting + or - before the volume will make the volume change relative to the current volume.
        """

        new_volume = "".join(leftover_args)

        if not new_volume:
            bar_len = 20
            return Response("Current volume: {}%\n{}".format(int(player.volume * 100), "".join(["■" if (x / bar_len) < player.volume else "□" for x in range(bar_len)])), reply=True, delete_after=20)

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
                '{} is not a valid number'.format(new_volume), expire_in=20)

        if relative:
            vol_change = new_volume
            new_volume += (player.volume * 100)

        if special_operation is not None:
            operations = {"*": lambda x, y: x * y, "/": lambda x,
                          y: x / y, "%": lambda x, y: x % y, }
            op = operations[special_operation]
            new_volume = op(player.volume * 100, new_volume)

        old_volume = int(player.volume * 100)

        if 0 < new_volume <= 100:
            player.volume = new_volume / 100.0

            return Response('updated volume from %d to %d' % (old_volume, new_volume), reply=True, delete_after=20)

        else:
            if relative:
                raise exceptions.CommandError(
                    'Unreasonable volume change provided: {}{:+} -> {}%.  Provide a change between {} and {:+}.'.format(
                        old_volume, vol_change, old_volume + vol_change, 1 - old_volume, 100 - old_volume), expire_in=20)
            else:
                raise exceptions.CommandError(
                    'Unreasonable volume provided: {}%. Provide a value between 1 and 100.'.format(new_volume), expire_in=20)

    async def cmd_queue(self, channel, player):
        """
        Usage:
            {command_prefix}queue

        logs the current song queue.
        """

        lines = []
        unlisted = 0
        andmoretext = '* ... and %s more*' % ('x' *
                                              len(player.playlist.entries))

        if player.current_entry:
            song_progress = str(
                timedelta(seconds=player.progress)).lstrip('0').lstrip(':')
            song_total = str(timedelta(seconds=player.current_entry.duration)).lstrip(
                '0').lstrip(':')
            prog_str = '`[%s/%s]`' % (song_progress, song_total)

            if player.current_entry.meta.get('channel', False) and player.current_entry.meta.get('author', False):
                lines.append("Now Playing: **%s** added by **%s** %s\n" % (
                    player.current_entry.title, player.current_entry.meta['author'].name, prog_str))
            else:
                lines.append("Now Playing: **%s** %s\n" %
                             (player.current_entry.title, prog_str))

        for i, item in enumerate(player.playlist, 1):
            if item.meta.get('channel', False) and item.meta.get('author', False):
                nextline = '`{}.` **{}** added by **{}**'.format(
                    i, item.title, item.meta['author'].name).strip()
            else:
                nextline = '`{}.` **{}**'.format(i, item.title).strip()

            # +1 is for newline char
            currentlinesum = sum(len(x) + 1 for x in lines)

            if currentlinesum + len(nextline) + len(andmoretext) > DISCORD_MSG_CHAR_LIMIT:
                if currentlinesum + len(andmoretext):
                    unlisted += 1
                    continue

            lines.append(nextline)

        if unlisted:
            lines.append('\n*... and %s more*' % unlisted)

        if not lines:
            lines.append(
                'There are no songs queued! Queue something with {}play.'.format(self.config.command_prefix))

        message = '\n'.join(lines)
        return Response(message, delete_after=30)

    async def cmd_clean(self, message, channel, server, author, search_range=50):
        """
        Usage:
            {command_prefix}clean [range]

        Removes up to [range] messages the bot has posted in chat. Default: 50, Max: 1000
        """

        try:
            float(search_range)  # lazy check
            search_range = min(int(search_range) + 1, 1000)
        except:
            return Response("enter a number.  NUMBER.  That means digits.  `15`.  Etc.", reply=True, delete_after=8)

        await self.safe_delete_message(message, quiet=True)

        def is_possible_command_invoke(entry):
            valid_call = any(
                entry.content.startswith(prefix) for prefix in [self.config.command_prefix])  # can be expanded
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
                deleted = await self.purge_from(channel, check=check, limit=search_range, before=message)
                return Response('Cleaned up {} message{}.'.format(len(deleted), 's' * bool(deleted)), delete_after=15)

        deleted = 0
        async for entry in self.logs_from(channel, search_range, before=message):
            if entry == self.server_specific_data[channel.server]['last_np_msg']:
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

        return Response('Cleaned up {} message{}.'.format(deleted, 's' * bool(deleted)), delete_after=15)

    async def cmd_pldump(self, channel, song_url):
        """
        Usage:
            {command_prefix}pldump url

        Dumps the individual urls of a playlist
        """

        try:
            info = await self.downloader.extract_info(self.loop, song_url.strip('<>'), download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError(
                "Could not extract info from input url\n%s\n" % e, expire_in=25)

        if not info:
            raise exceptions.CommandError(
                "Could not extract info from input url, no data.", expire_in=25)

        if not info.get('entries', None):
            # TODO: Retarded playlist checking
            # set(url, webpageurl).difference(set(url))

            if info.get('url', None) != info.get('webpage_url', info.get('url', None)):
                raise exceptions.CommandError(
                    "This does not seem to be a playlist.", expire_in=25)
            else:
                return await self.cmd_pldump(channel, info.get(''))

        linegens = defaultdict(lambda: None, **{
            "youtube": lambda d: 'https://www.youtube.com/watch?v=%s' % d['id'],
            "soundcloud": lambda d: d['url'],
            "bandcamp": lambda d: d['url']
        })

        exfunc = linegens[info['extractor'].split(':')[0]]

        if not exfunc:
            raise exceptions.CommandError(
                "Could not extract info from input url, unsupported playlist type.", expire_in=25)

        with BytesIO() as fcontent:
            for item in info['entries']:
                fcontent.write(exfunc(item).encode('utf8') + b'\n')

            fcontent.seek(0)
            await self.send_file(channel, fcontent, filename='playlist.txt', content="Here's the url dump for <%s>" % song_url)

        return Response(":mailbox_with_mail:", delete_after=20)

    async def cmd_listids(self, server, author, leftover_args, cat='all'):
        """
        Usage:
            {command_prefix}listids [categories]

        Lists the ids for various things.  Categories are:
           all, users, roles, channels
        """

        cats = ['channels', 'roles', 'users']

        if cat not in cats and cat != 'all':
            return Response(
                "Valid categories: " + ' '.join(['`%s`' % c for c in cats]),
                reply=True,
                delete_after=25
            )

        if cat == 'all':
            requested_cats = cats
        else:
            requested_cats = [cat] + [c.strip(',') for c in leftover_args]

        data = ['Your ID: %s' % author.id]

        for cur_cat in requested_cats:
            rawudata = None

            if cur_cat == 'users':
                data.append("\nUser IDs:")
                rawudata = ['%s #%s: %s' % (
                    m.name, m.discriminator, m.id) for m in server.members]

            elif cur_cat == 'roles':
                data.append("\nRole IDs:")
                rawudata = ['%s: %s' % (r.name, r.id) for r in server.roles]

            elif cur_cat == 'channels':
                data.append("\nText Channel IDs:")
                tchans = [c for c in server.channels if c.type ==
                          discord.ChannelType.text]
                rawudata = ['%s: %s' % (c.name, c.id) for c in tchans]

                rawudata.append("\nVoice Channel IDs:")
                vchans = [c for c in server.channels if c.type ==
                          discord.ChannelType.voice]
                rawudata.extend('%s: %s' % (c.name, c.id) for c in vchans)

            if rawudata:
                data.extend(rawudata)

        with BytesIO() as sdata:
            sdata.writelines(d.encode('utf8') + b'\n' for d in data)
            sdata.seek(0)

            await self.send_file(author, sdata, filename='%s-ids-%s.txt' % (server.name.replace(' ', '_'), cat))

        return Response(":mailbox_with_mail:", delete_after=20)

    async def cmd_perms(self, author, channel, server, permissions):
        """
        Usage:
            {command_prefix}perms

        Sends the user a list of their permissions.
        """

        lines = ['Command permissions in %s\n' % server.name, '```', '```']

        for perm in permissions.__dict__:
            if perm in ['user_list'] or permissions.__dict__[perm] == set():
                continue

            lines.insert(len(lines) - 1, "%s: %s" %
                         (perm, permissions.__dict__[perm]))

        await self.send_message(author, '\n'.join(lines))
        return Response(":mailbox_with_mail:", delete_after=20)

    @owner_only
    async def cmd_setname(self, leftover_args, name):
        """
        Usage:
            {command_prefix}setname name

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
            {command_prefix}setnick nick

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
            {command_prefix}setavatar [url]

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
            {command_prefix}autoplay
        Play from the autoplaylist.
        """

        if not self.config.auto_playlist:
            self.config.auto_playlist = True
            await self.on_player_finished_playing(player)
            return Response("Playing from the autoplaylist", delete_after=20)
        else:
            self.config.auto_playlist = False
            return Response("Won't play from the autoplaylist anymore", delete_after=20)

        # await self.safe_send_message (channel, msgState)

    async def cmd_radio(self, player, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}radio [station name]
            {command_prefix}radio random
        Play live radio.
        You can leave the parameters blank in order to get a tour around all the channels,
        you can specify the station you want to listen to or you can let the bot choose for you by entering \"random\"
        """
        if len(leftover_args) > 0 and leftover_args[0].lower().strip() == "random":
            station = self.radios.get_random_station()
            await player.playlist.add_stream_entry(station.url, play_now=True, player=player, channel=channel, author=author, station=station)
            return Response("I choose\n**{.name}**".format(station), delete_after=5)
        elif len(leftover_args) > 0:
            # try to find the radio station
            search_name = " ".join(leftover_args)
            station = self.radios.get_station(search_name.lower().strip())
            if station is not None:
                await player.playlist.add_stream_entry(station.url, play_now=True, player=player, channel=channel, author=author, station=station)
                return Response("Your favourite:\n**{.name}**".format(station), delete_after=5)

        # help the user find the right station

        def check(m):
            true = ["y", "yes", "yeah", "yep", "sure"]
            false = ["n", "no", "nope", "never"]

            return m.content.lower().strip() in true or m.content.lower().strip() in false

        possible_stations = self.radios.get_all_stations()
        shuffle(possible_stations)

        interface_string = "**{0.name}**\n*language:* {0.language}\n\n`Type \"yes\" or \"no\"`"

        for station in possible_stations:
            msg = await self.safe_send_message(channel, interface_string.format(station))
            response = await self.wait_for_message(author=author, channel=channel, check=check)
            await self.safe_delete_message(msg)
            play_station = response.content.lower().strip() in [
                "y", "yes", "yeah", "yep", "sure"]
            await self.safe_delete_message(response)

            if play_station:
                await player.playlist.add_stream_entry(station.url, play_now=True, player=player, channel=channel, author=author, station=station)
                return Response("There you go fam!\n**{.name}**".format(station), delete_after=5)
            else:
                continue

    async def socket_radio(self, player, radio_station_name):
        if radio_station_name.lower().strip() == "random":
            station = self.radios.get_random_station()
            await player.playlist.add_stream_entry(station.url, play_now=True, player=player, station=station)
            return True

        station = self.radios.get_station(radio_station_name.lower().strip())
        if station is not None:
            await player.playlist.add_stream_entry(station.url, play_now=True, player=player, station=station)
            return True

        return False

    async def cmd_say(self, channel, message, leftover_args):
        """
        Usage:
            {command_prefix}say <message>
        Make the bot say something
        """

        await self.safe_delete_message(message)
        await self.safe_send_message(channel, " ".join(leftover_args))
        self.log(message.author.name +
                 " made me say: \"" + " ".join(leftover_args) + "\"")

    async def cmd_c(self, author, channel, leftover_args):
        """
        Usage:
            {command_prefix}c <message>

        have a chat
        """
        if len(leftover_args) < 1:
            return Response("You need to actually say something...")

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
            base_answer = re.sub("[^a-z| ]+|\s{2,}", "", answer.lower())
            if base_answer not in "whats your name".split(";") and not any(q in base_answer for q in "whats your name".split(";")):
                break
        # await self.safe_edit_message (message, msgContent)
        self.log("<" + str(author.name) + "> " +
                 msgContent + "\n<Bot> " + answer + "\n")
        return Response(answer)

    async def cmd_ask(self, author, channel, message, leftover_args):
        """
        Usage:
            {command_prefix}ask <question>
        ask something
        """

        await self.send_typing(channel)
        msgContent = " ".join(leftover_args)

        col = choice([9699539, 4915330, 255, 65280,
                      16776960, 16744192, 16711680])

        if msgContent.lower() == "simon berger" or msgContent.lower() == "simon jonas berger":
            already_used = load_file("data/simon_berger_asked.txt")

            if author.id in already_used:
                return Response("I mustn't betray my master twice for you!")
            else:
                already_used.append(author.id)
                write_file("data/simon_berger_asked.txt", already_used)

            conv = "okay...|4.5;;so you've finally figured out that you could just ask Giesela...|3;;great.|1;;well uh...|5;;I programmed this in exactly for this reason...|2;;good on you!|3"
            prev_msg = None
            for part in conv.split(";;"):
                # if prev_msg is not None:
                    # await self.safe_delete_message(prev_msg)
                msg, delay = part.split("|")
                prev_msg = await self.safe_send_message(channel, msg)
                await self.send_typing(channel)
                await asyncio.sleep(float(delay))

            if not channel.is_private:
                await self.safe_send_message(channel, "Can I at least send it in private Chat...?")
                msg = await self.wait_for_message(timeout=12, author=author, channel=channel)
                if msg is None:
                    await self.send_typing(channel)
                    await asyncio.sleep(3)
                    await self.safe_send_message(channel, "I'm gonna assume that's a no... sighs")
                if any(x in msg.content.strip().lower() for x in ["yes", "ye", "ja", "why not", "ok", "okay", "sure", "yeah", "sighs"]):
                    channel = author
                    await self.send_typing(channel)
                    await asyncio.sleep(2)
                    await self.safe_send_message(channel, "Thank you so much <3!")
                else:
                    await self.send_typing(channel)
                    await asyncio.sleep(1.6)
                    await self.safe_send_message(channel, "Thanks for nothing.......")

            await self.send_typing(channel)
            await asyncio.sleep(1.2)
            await self.safe_send_message(channel, "Here goes nuthin'")
            await asyncio.sleep(4)

            simon_info = "Input Interpretation\;simon_berger_input_interpretation.png\;Simon Berger (Google Employee, Huge Dork, Creator of Giesela)\nBasic Information\;simon_berger_basic_information.png\;full name | Simon Jonas Berger date of birth | Saturday, March 28, 1992 (age: 25 years) place of birth | Wattenwil, Switzerland\nImage\;simon_berger_image.png\;\nPhysical Characteristics\;simon_berger_physical_characteristics.png\;height | 6\' 01\'\'"
            for pod in simon_info.split("\n"):
                title, img, foot = pod.split("\;")
                em = Embed(title=title, colour=col)
                em.set_image(
                    url="https://raw.githubusercontent.com/siku2/MusicBot/master/data/pictures/custom%20ask/simon%20berger/" + img)
                em.set_footer(text=foot)
                await self.send_message(channel, embed=em)
                await asyncio.sleep(1)
            return

        client = tungsten.Tungsten("EH8PUT-67PJ967LG8")
        res = client.query(msgContent)
        if not res.success:
            await self.safe_send_message(channel, "Couldn't find anything useful on that subject, sorry.\n**I'm now including Wikipedia!**", expire_in=15)
            self.log("Didn't find an answer to: " + msgContent)
            return await self.cmd_wiki(channel, message, ["en", "summarize", "5", msgContent])

        for pod in res.pods:
            em = Embed(title=pod.title, colour=col)
            em.set_image(url=pod.format["img"][0]["url"])
            em.set_footer(text=pod.format["img"][0]["alt"])
            await self.send_message(channel, embed=em)
        # return

        # await self.safe_send_message(channel, "\n".join(["**{}** {}".format(pod.title, self.shortener.short(pod.format["img"][0]["url"])) for pod in res.pods]), expire_in=100)
        # await self.safe_send_message(channel, answer)
        self.log("Answered " + message.author.name +
                 "'s question with: " + msgContent)

    async def cmd_translate(self, channel, message, targetLanguage, leftover_args):
        """
        Usage:
            {command_prefix}translate <targetLanguage> <message>
        translate something from any language to the target language
        """

        await self.send_typing(channel)

        gs = goslate.Goslate()
        languages = gs.get_languages()

        if len(targetLanguage) == 2 and (targetLanguage not in list(languages.keys())):
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

    async def cmd_goto(self, server, channel, user_mentions, author, leftover_args):
        """
        Usage:
            {command_prefix}goto id/name

        Call the bot to a channel.
        """

        channelID = " ".join(leftover_args)
        if channelID.lower() == "home":
            channelID = "MusicBot's reign"

        if channelID.lower() in ["bed", "sleep", "hell", "church", "school", "work", "666"]:
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
                            "Cannot find *{}* in any voice channel".format(
                                ", ".join([x.mention for x in user_mentions])),
                            delete_after=25
                        )
                else:
                    self.log("Cannot find channel \"%s\"" % channelID)
                    return Response(
                        "```Cannot find channel \"%s\"```" % channelID,
                        delete_after=25
                    )

        voice_client = await self.get_voice_client(targetChannel)
        self.log("Will join channel \"%s\"" % targetChannel.name)
        await self.safe_send_message(channel, "Joined the channel *{}*".format(targetChannel.name), expire_in=8)
        await self.move_voice_client(targetChannel)
        # return

        # move to _verify_vc_perms?
        chperms = targetChannel.permissions_for(targetChannel.server.me)

        if not chperms.connect:
            self.log(
                "Cannot join channel \"%s\", no permission." % targetChannel.name)
            return Response(
                "```Cannot join channel \"%s\", no permission.```" % targetChannel.name,
                delete_after=25
            )

        elif not chperms.speak:
            self.log(
                "Will not join channel \"%s\", no permission to speak." % targetChannel.name)
            return Response(
                "```Will not join channel \"%s\", no permission to speak.```" % targetChannel.name,
                delete_after=25
            )

        player = await self.get_player(targetChannel, create=True)

        if player.is_stopped:
            player.play()

        if self.config.auto_playlist:
            await self.on_player_finished_playing(player)

    async def cmd_replay(self, player, channel, author):
        """
        Usage:
            {command_prefix}replay

        Replay the current song
        """
        if not player.current_entry:
            await self.safe_send_message(channel, "There's nothing for me to replay")

        try:
            player.playlist._add_entry_next(player.current_entry)
            await self.safe_send_message(channel, "Replaying the current song")
            self.log("Will replay " + player.current_entry.title)

        except Exception as e:
            self.log("Something went wrong: " + str(e))
            await self.safe_send_message(channel, "Can't replay " + player.current_entry.title)

    async def cmd_lonelymode(self, channel, author, msgState=None):
        """
        Usage:
            {command_prefix}lonelymode [bool]

        Let the bot talk to itself
        """
        self.newLonelyState = (msgState.lower(
        ) in self.trueStringList) if msgState is not None else not self.lonelyModeRunning
        if self.newLonelyState and not self.lonelyModeRunning:
            await self.lonelymodeloop(channel)
        else:
            self.lonelyModeRunning = False

    async def lonelymodeloop(self, channel):
        self.lonelyModeRunning = True
        cbOne = CleverWrap("CCC8n_IXK43aOV38rcWUILmYUBQ")
        cbTwo = CleverWrap("CCC8n_IXK43aOV38rcWUILmYUBQ")
        answer = cbOne.say(
            choice(["hey", "salut", "hallo", "hello", "hi there", "hello there", "good evening"]))
        await self.safe_send_message(channel, "Regi: Hello there")

        while self.newLonelyState:
            await self.send_typing(channel)
            await asyncio.sleep(1.8)
            await self.safe_send_message(channel, 'Giesela: {}'.format(answer))
            answer = cbOne.say(answer)
            await self.send_typing(channel)
            await asyncio.sleep(1.8)
            await self.safe_send_message(channel, 'Regi: {}'.format(answer))
            answer = cbTwo.say(answer)

    async def cmd_random(self, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}random <item1>, <item2>, [item3], [item4]...
            {command_prefix}random <name of the set>
            {command_prefix}random create <name>, <option1>, <option2>, [option3], [option4]...
            {command_prefix}random edit <name>, [add | remove | replace], <item> [, item2, item3]
            {command_prefix}random remove <name>
            {command_prefix}random list

        Choose a random item out of a list or use a pre-defined list.
        Use `list` to see all the different lists out there or create your own.
        """

        items = [x.strip()
                 for x in " ".join(leftover_args).split(",") if x is not ""]

        if items[0].split()[0].lower().strip() == "create":
            if len(items) < 2:
                return Response("Can't create a set with the given arguments", delete_after=20)

            set_name = "_".join(items[0].split()[1:]).lower().strip()
            set_items = items[1:]
            if self.random_sets.create_set(set_name, set_items):
                return Response("Created set *{0}*\nUse `{1}random {0}` to use it!".format(set_name, self.config.command_prefix), delete_after=60)
            else:
                return Response("OMG, shit went bad quickly! Everything's burning!\nDUCK there he goes again, the dragon's coming. Eat HIM not me. PLEEEEEEEEEEEEEASE!")
        elif items[0].split()[0].lower().strip() == "list":
            return_string = ""
            for s in self.random_sets.get_sets():
                return_string += "**{}**\n```\n{}```\n\n".format(
                    s[0], ", ".join(s[1]))

            return Response(return_string)
        elif items[0].split()[0].lower().strip() == "edit":
            if len(items[0].split()) < 2:
                return Response("Please provide the name of the list you wish to edit!", delete_after=20)

            set_name = "_".join(items[0].split()[1:]).lower().strip()

            existing_items = self.random_sets.get_set(set_name)
            if existing_items is None:
                return Response("This set does not exist!", delete_after=30)

            edit_mode = items[1].strip().lower() if len(items) > 1 else None
            if edit_mode is None:
                return Response("You need to provide the way you want to edit the list", delete_after=20)

            if len(items) < 3:
                return Response("You have to specify the items you want to add/remove or set as the new items")

            if edit_mode == "add":
                for option in items[2:]:
                    self.random_sets.add_option(set_name, option)
            elif edit_mode == "remove":
                for option in items[2:]:
                    self.random_sets.remove_option(set_name, option)
            elif edit_mode == "replace":
                self.random_sets.replace_options(set_name, items[2:])
            else:
                return Response("This is not a valid edit mode!", delete_after=20)

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
                return Response("OMG, shit went bad quickly! Everything's burning!\nDUCK there he goes again, the dragon's coming. Eat HIM not me. PLEEEEEEEEEEEEEASE!")

        if len(items) <= 0 or items is None:
            return Response("Is your name \"{0}\" by any chance?\n(This is not how this command works. Use `{1}help random` to find out how not to be a stupid *{0}* anymore)".format(author.name, self.config.command_prefix), delete_after=30)

        if len(items) <= 1:
            # return Response("Only you could use `{1}random` for one item...
            # Well done, {0}!".format(author.name, self.config.command_prefix),
            # delete_after=30)

            query = "_".join(items[0].split())
            items = self.random_sets.get_set(query.lower().strip())
            if items is None:
                return Response("Something went wrong", delete_after=30)

        await self.safe_send_message(channel, "I choose **" + choice(items) + "**")

    async def cmd_requestfeature(self, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}requestfeature description

        Request a feature to be added to the bot
        """

        await self.send_typing(channel)

        if os.path.isfile("data/request.txt"):
            with open("data/request.txt", "r") as orgFile:
                orgContent = orgFile.read()
        else:
            orgContent = ""

        with open("data/request.txt", "w") as newFile:
            newContent = datetime.datetime.strftime(datetime.datetime.now(
            ), "%Y-%m-%d %H:%M:%S") + " <" + str(author) + ">\n" + "\"" + " ".join(leftover_args) + "\"" + 2 * "\n"
            newFile.write(newContent + orgContent)

        await self.safe_send_message(self._get_owner(), "You have a new feature request: " + 2 * "\n" + newContent)
        await self.safe_send_message(channel, "Successfully received your request!")

    async def cmd_broadcast(self, server, message, leftover_args):
        """
        Usage:
            {command_prefix}broadcast message

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
                        if member not in targetMembers and (mRole.name == leftover_args[0] or mRole.id == leftover_args[0]):
                            self.log(
                                "User " + str(member) + " added to recipients")
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

    async def cmd_playfile(self, player, message, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}playfile

        Play the attached file
        """

        if len(message.attachments) < 1:
            return Response("You didn't attach anything, idiot.", delete_after=15)
            return

        await player.playlist.add_entry(message.attachments[0]["url"])

    # async def cmd_halloween (self, player, message, channel, permissions, author):
    #     """
    #     Usage:
    #         {command_prefix}halloween
    #
    #     Activate the mighty spirit of the halloween festival.
    #     """
    #     await self.safe_send_message (channel, "Halloween is upon you! :jack_o_lantern:")
    #     await self.cmd_ask (channel, message, ["Halloween"])
    #     player.volume = .15
    # await self.cmd_play (player, channel, author, permissions,
    # ["https://www.youtube.com/playlist?list=PLOz0HiZO93naR5dcZqJ-r9Ul0LA2Tpt7g"],
    # "https://www.youtube.com/playlist?list=PLOz0HiZO93naR5dcZqJ-r9Ul0LA2Tpt7g")

    # async def cmd_christmas(self, player, message, channel, permissions, author):
    #     """
    #     Usage:
    #         {command_prefix}christmas
    #
    #     Activate the mighty spirit of the christmas festival.
    #     """
    #     await self.safe_send_message(channel, "Christmas is upon you! :christmas_tree:")
    #     await self.cmd_ask(channel, message, ["Christmas"])
    #     player.volume = .15
    # await self.cmd_play(player, channel, author, permissions,
    # ["https://www.youtube.com/playlist?list=PLOz0HiZO93nae_euTdaeQwnVq0P01U_vw"],
    # "https://www.youtube.com/playlist?list=PLOz0HiZO93nae_euTdaeQwnVq0P01U_vw")

    async def cmd_getvideolink(self, player, message, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}getvideolink (optional: pause video)

        Sends the video link that gets you to the current location of the bot. Use "pause video" as argument to help you sync up the video.
        """

        if not player.current_entry:
            await self.safe_send_message(channel, "Can't give you a link for FUCKING NOTHING", expire_in=15)
            return

        if "pause video" in " ".join(leftover_args).lower():
            player.pause()
            minutes, seconds = divmod(player.progress, 60)
            await self.safe_send_message(channel, player.current_entry.url + "#t={0}m{1}s".format(minutes, seconds))
            msg = await self.safe_send_message(channel, "Resuming video in a few seconds!")
            await asyncio.sleep(1.5)

            for i in range(5, 0, -1):
                newMsg = "** %s **" if i <= 3 else "%s"
                newMsg %= str(i)

                msg = await self.safe_edit_message(msg, newMsg, send_if_fail=True)
                await asyncio.sleep(1)

            msg = await self.safe_edit_message(msg, "Let's continue!", send_if_fail=True)
            player.resume()

        else:
            minutes, seconds = divmod(player.progress + 3, 60)
            await self.safe_send_message(channel, player.current_entry.url + "#t={0}m{1}s".format(minutes, seconds))

    async def cmd_remove(self, player, message, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}remove <index | start index | url> [end index]

        Remove a index or a url from the playlist.
        """

        if len(leftover_args) < 1:
            leftover_args = ["0"]

        if len(player.playlist.entries) < 0:
            await self.safe_send_message(channel, "There are no entries in the playlist!", expire_in=15)
            return

        if len(leftover_args) >= 2:
            try:
                start_index = int(leftover_args[0]) - 1
                end_index = int(leftover_args[1]) - 1

                if start_index > end_index:
                    return Response("Your start index shouldn't be bigger than the end index", delete_after=15)

                if start_index > len(player.playlist.entries) - 1 or start_index < 0:
                    await self.safe_send_message(channel, "The start index is out of bounds", expire_in=15)
                    return
                if end_index > len(player.playlist.entries) - 1 or end_index < 0:
                    await self.safe_send_message(channel, "The end index is out of bounds", expire_in=15)
                    return

                for i in range(end_index, start_index - 1, -1):
                    del player.playlist.entries[i]

                return Response("Removed {} entries from the playlist".format(end_index - start_index + 1), delete_after=30)
            except:
                raise
                pass

        try:
            index = int(leftover_args[0]) - 1

            if index > len(player.playlist.entries) - 1 or index < 0:
                await self.safe_send_message(channel, "This index cannot be found in the playlist", expire_in=15)
                return

            video = player.playlist.entries[index].title
            del player.playlist.entries[index]
            await self.safe_send_message(channel, "Removed *{0}* from the playlist".format(video))
            return

        except:
            strindex = leftover_args[0]
            iteration = 1

            for entry in player.playlist.entries:
                self.log("Looking at {0}. [{1}]".format(
                    entry.title, entry.url))

                if entry.title == strindex or entry.url == strindex:
                    self.log(
                        "Found {0} and will remove it".format(leftover_args[0]))
                    await self.cmd_remove(player, message, channel, author, [iteration])
                    return
                iteration += 1

        await self.safe_send_message(channel, "Didn't find anything that goes by {0}".format(leftover_args[0]), expire_in=15)

    async def cmd_news(self, message, channel, author, paper=None):
        """
        Usage:
            {command_prefix}news (if you already now what you want to read: url or name)

        Get the latest news with this function!
        """

        await self.send_typing(channel)

        if not paper:
            def check(m):
                return (
                    m.content.lower()[0] in 'yn' or
                    # hardcoded function name weeee
                    m.content.lower().startswith('{}{}'.format(self.config.command_prefix, 'news')) or
                    m.content.lower().startswith('exit'))

            for section in self.papers.config.sections():
                await self.send_typing(channel)
                paperinfo = self.papers.get_paper(section)
                paper_message = await self.send_file(channel, str(paperinfo.cover), content="**" + str(paperinfo.name) + "**")

                confirm_message = await self.safe_send_message(channel, "Do you want to read these papers? Type `y`, `n` or `exit`")
                response_message = await self.wait_for_message(300, author=author, channel=channel, check=check)

                if not response_message:
                    await self.safe_delete_message(paper_message)
                    await self.safe_delete_message(confirm_message)
                    return Response("Ok nevermind.", delete_after=30)

                elif response_message.content.startswith(self.config.command_prefix) or \
                        response_message.content.lower().startswith('exit'):

                    await self.safe_delete_message(paper_message)
                    await self.safe_delete_message(confirm_message)
                    return

                if response_message.content.lower().startswith('y'):
                    await self.safe_delete_message(paper_message)
                    await self.safe_delete_message(confirm_message)
                    await self.safe_delete_message(response_message)

                    return Response((await self.cmd_news(message, channel, author, paper=section)).content)
                else:
                    await self.safe_delete_message(paper_message)
                    await self.safe_delete_message(confirm_message)
                    await self.safe_delete_message(response_message)

            return Response("I don't have any more papers :frowning:", delete_after=30)

        if not self.papers.get_paper(paper):
            try:
                npaper = newspaper.build(paper, memoize_articles=False)
                await self.safe_send_message(channel, "**" + npaper.brand + "**")
            except:
                self.safe_send_message(
                    channel, "Something went wrong while looking at the url")
                return
        else:
            paperinfo = self.papers.get_paper(paper)
            npaper = newspaper.build(
                paperinfo.url, language=paperinfo.language, memoize_articles=False)
            await self.send_file(channel, str(paperinfo.cover), content="**" + str(paperinfo.name) + "**")

        await self.safe_send_message(channel, npaper.description + "\n*Found " + str(len(npaper.articles)) + " articles*\n=========================\n\n")

        def check(m):
            return (
                m.content.lower()[0] in 'yn' or
                # hardcoded function name weeee
                m.content.lower().startswith('{}{}'.format(self.config.command_prefix, 'news')) or
                m.content.lower().startswith('exit'))

        for article in npaper.articles:
            await self.send_typing(channel)
            try:
                article.download()
                article.parse()
                article.nlp()
            except:
                self.log(
                    "Something went wrong while parsing \"" + str(article) + "\", skipping it")
                continue

            if len(article.authors) > 0:
                article_author = "Written by: {0}".format(
                    ", ".join(article.authors))
            else:
                article_author = "Couldn't determine the author of this article."

            if len(article.keywords) > 0:
                article_keyword = "Keywords: {0}".format(
                    ", ".join(article.keywords))
            else:
                article_keyword = "Couldn't make out any keywords"

            article_title = article.title
            article_summary = article.summary
            article_image = article.top_image

            article_text = "\n\n**{}**\n*{}*\n```\n\n{}\n```\n{}\n".format(
                article_title, article_keyword, article_summary, article_author)

            article_message = await self.safe_send_message(channel, article_text)

            confirm_message = await self.safe_send_message(channel, "Do you want to read this? Type `y`, `n` or `exit`")
            response_message = await self.wait_for_message(300, author=author, channel=channel, check=check)

            if not response_message:
                await self.safe_delete_message(article_message)
                await self.safe_delete_message(confirm_message)
                return Response("Ok nevermind.", delete_after=30)

            elif response_message.content.startswith(self.config.command_prefix) or \
                    response_message.content.lower().startswith('exit'):

                await self.safe_delete_message(article_message)
                await self.safe_delete_message(confirm_message)
                return

            if response_message.content.lower().startswith('y'):
                await self.safe_delete_message(article_message)
                await self.safe_delete_message(confirm_message)
                await self.safe_delete_message(response_message)

                if len(article.text) > 1500:
                    fullarticle_text = "**{}**\n*{}*\n\n<{}>\n\n*{}*".format(
                        article_title, article_author, article.url, "The full article exceeds the limits of Discord so I can only provide you with this link")
                else:
                    fullarticle_text = "**{}**\n*{}*\n\n{}".format(
                        article_title, article_author, article.text)

                return Response(fullarticle_text)
            else:
                await self.safe_delete_message(article_message)
                await self.safe_delete_message(confirm_message)
                await self.safe_delete_message(response_message)

        return Response("Can't find any more articles :frowning:", delete_after=30)

    async def cmd_cah(self, message, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}cah create
            {command_prefix}cah join <token>
            {command_prefix}cah leave <token>

            {command_prefix}cah start <token>
            {command_prefix}cah stop <token>

        Play a cards against humanity game

        References:
            {command_prefix}help cards
                -learn about how to create/edit cards
            {command_prefix}help qcards
                -learn about how to create/edit question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "create":
            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game(author.id)
                return Response("You can't host a game if you're already in one\nUse `{}cah leave {}` to leave your current game".format(self.config.command_prefix, g.token), delete_after=15)

            token = self.cah.new_game(author.id)
            return Response("Created a new game.\nUse `{0}cah join {1}` to join this game and\nwhen everyone's in use `{0}cah start {1}`".format(self.config.command_prefix, token), delete_after=1000)
        elif argument == "join":
            token = leftover_args[1].lower() if len(
                leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game_from_user_id(author.id)
                return Response("You can only be part of one game at a time!\nUse `{}cah leave {}` to leave your current game".format(self.config.command_prefix, g.token), delete_after=15)

            g = self.cah.get_game(token)

            if g is None:
                return Response("This game does not exist *shrugs*", delete_after=15)

            if g.in_game(author.id):
                return Response("You're already in this game!", delete_after=15)

            if self.cah.user_join_game(author.id, token):
                return Response("Successfully joined the game **{}**".format(token.upper()))
            else:
                return Response("Failed to join game **{}**".format(token.upper()))
        elif argument == "leave":
            token = leftover_args[1].lower() if len(
                leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            g = self.cah.get_game(token)

            if g is None:
                return Response("This game does not exist *shrugs*", delete_after=15)

            if not g.in_game(author.id):
                return Response("You're not part of this game!", delete_after=15)

            if self.cah.player_leave_game(author.id, token):
                return Response("Successfully left the game **{}**".format(token.upper()))
            else:
                return Response("Failed to leave game **{}**".format(token.upper()))
        elif argument == "start":
            token = leftover_args[1].lower() if len(
                leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token", delete_after=15)

            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!", delete_after=15)

            if not g.is_owner(author.id):
                return Response("Only the owner may start a game!", delete_after=15)

            if not g.enough_players():
                return Response("There are not enough players to start this game.\nUse `{}cah join {}` to join a game".format(self.config.command_prefix, g.token), delete_after=15)

            if not g.start_game():
                return Response("This game has already started!", delete_after=15)
        elif argument == "stop":
            token = leftover_args[1].lower() if len(
                leftover_args) > 1 else None
            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!", delete_after=15)

            if not g.is_owner(author.id):
                return Response("Only the owner may stop a game!", delete_after=15)

            self.cah.stop_game(g.token)
            return Response("Stopped the game **{}**".format(token), delete_after=15)

    async def cmd_cards(self, server, channel, author, message, leftover_args):
        """
        Usage:
            {command_prefix}cards list [@mention] [text | likes | occurences | date | random | id | author | none]
                -list all the available cards
            {command_prefix}cards create <text>
                -create a new card with text
            {command_prefix}cards edit <id> <new_text>
                -edit a card by its id
            {command_prefix}cards info <id>
                -Get more detailed information about a card
            {command_prefix}cards search <query>
                -Search for a card
            {command_prefix}cards delete <id>
                -Delete a question card

        Here you manage the non question cards
        """

        argument = leftover_args[0].lower() if len(
            leftover_args) > 0 else None

        if argument == "list":
            sort_modes = {"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (
                lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "{}%".format(int(entry.like_dislike_ratio * 100)))}

            cards = self.cah.cards.cards.copy() if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.cards.copy() if x.creator_id in [u.id for u in message.mentions]]
            sort_mode = leftover_args[1].lower() if len(leftover_args) > 1 and leftover_args[
                1].lower() in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(cards, key=sort_modes[sort_mode][
                               0], reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.card_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(leftover_args[1:]) if len(
                leftover_args) > 1 else None

            if search_query is None:
                return Response("You need to provide a query to search for!", delete_after=15)

            results = self.cah.cards.search_card(search_query, 3)

            if len(results) < 1:
                return Response("**Didn't find any cards!**", delete_after=15)

            card_string = "{0.id}. \"*{1}*\""
            cards = []
            for card in results:
                cards.append(card_string.format(
                    card, card.text.replace("$", "_____")))

            return Response("**I found the following cards:**\n\n" + "\n".join(cards), delete_after=40)
        elif argument == "info":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            card = self.cah.cards.get_card(card_id)
            if card is not None:
                info = "Card **{0.id}** by {1}\n```\n\"{0.text}\"\nused {0.occurences} time{2}\ndrawn {0.picked_up_count} time{5}\nliked by {6}% of players\ncreated {3}```\nUse `{4}cards edit {0.id}` to edit this card"
                return Response(info.format(card, self.get_global_user(card.creator_id).mention, "s" if card.occurences != 1 else "", prettydate(card.creation_date), self.config.command_prefix, "s" if card.picked_up_count != 1 else "", int(card.like_dislike_ratio * 100)))

            return Response("There's no card with that id. Use `{}cards list` to list all the possible cards".format(self.config.command_prefix))
        elif argument == "create":
            text = " ".join(leftover_args[1:]) if len(
                leftover_args) > 1 else None
            if text is None:
                return Response("You might want to actually add some text to your card", delete_after=20)
            if len(text) < 3:
                return Response("I think that's a bit too short...", delete_after=20)
            if len(text) > 140:
                return Response("Maybe a bit too long?", delete_after=20)

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card:
                return Response("There's already a card with a fairly similar content. <{0}>\nUse `{1}cards info {0}` to find out more about this card".format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_card(text, author.id)
            return Response("Successfully created card **{}**".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number", delete_after=20)

            if card_id is None:
                return Response("You need to provide the card's id!", delete_after=20)

            text = " ".join(leftover_args[2:]) if len(
                leftover_args) > 1 else None
            if text is None:
                return Response("You might want to actually add some text to your card", delete_after=20)
            if len(text) < 3:
                return Response("I think that's a bit too short...", delete_after=20)
            if len(text) > 140:
                return Response("Maybe a bit too long?", delete_after=20)

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card and card.id != card_id_value:
                return Response("There's already a card with a fairly similar content. <{0}>\nUse `{1}cards info {0}` to find out more about this card".format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_card(card_id, text):
                return Response("Edited card <**{}**>".format(card_id), delete_after=15)
            else:
                return Response("There's no card with that id", delete_after=15)
        elif argument == "delete":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            if card_id is None:
                return Response("You must specify the card id", delete_after=15)

            if self.cah.cards.remove_card(card_id):
                return Response("Deleted card <**{}**>".format(card_id), delete_after=15)
            else:
                return Response("Could not remove card <**{}**>".format(card_id), delete_after=15)
        else:
            return await self.cmd_help(channel, ["cards"])

    async def card_viewer(self, channel, author, cards, display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Cards | Page {0} of {1}**\n```\n{2}\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<{}> [{}]{}"

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
                page_cards_texts.append(card_string.format(p_c.id, p_c.text, "" if display_additional is None or display_additional(
                    p_c) is None else " | {}".format(display_additional(p_c))))

            interface_msg = await self.safe_send_message(channel, site_interface.format(current_page + 1, total_pages + 1, "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(timeout, author=author, channel=channel, check=msg_check)

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

        await self.safe_send_message(channel, "Closed the card viewer!", expire_in=20)

    async def cmd_qcards(self, server, channel, author, message, leftover_args):
        """
        Usage:
            {command_prefix}qcards list [@mention] [text | likes | occurences | date | author | id | blanks | random | none]
                -list all the available question cards
            {command_prefix}qcards create <text (use $ for blanks)>
                -create a new question card with text and if you want the number of cards to draw
            {command_prefix}qcards edit <id> <new_text>
                -edit a question card by its id
            {command_prefix}qcards info <id>
                -Get more detailed information about a question card
            {command_prefix}qcards search <query>
                -Search for a question card
            {command_prefix}qcards delete <id>
                -Delete a question card

        Here you manage the question cards
        """

        argument = leftover_args[0].lower() if len(
            leftover_args) > 0 else None

        if argument == "list":
            sort_modes = {"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(
                entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "blanks": (lambda entry: entry.number_of_blanks, True, lambda entry: entry.number_of_blanks), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "{}%".format(int(entry.like_dislike_ratio * 100)))}

            cards = self.cah.cards.question_cards.copy() if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.question_cards.copy() if x.creator_id in [u.id for u in message.mentions]]
            sort_mode = leftover_args[1].lower() if len(leftover_args) > 1 and leftover_args[
                1].lower() in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(cards, key=sort_modes[sort_mode][
                               0], reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.qcard_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(leftover_args[1:]) if len(
                leftover_args) > 1 else None

            if search_query is None:
                return Response("You need to provide a query to search for!", delete_after=15)

            results = self.cah.cards.search_question_card(search_query, 3)

            if len(results) < 1:
                return Response("**Didn't find any question cards!**", delete_after=15)

            card_string = "{0.id}. \"*{1}*\""
            cards = []
            for card in results:
                cards.append(card_string.format(
                    card, card.text.replace("$", "\_\_\_\_\_")))

            return Response("**I found the following question cards:**\n\n" + "\n".join(cards), delete_after=40)
        elif argument == "info":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            card = self.cah.cards.get_question_card(card_id)
            if card is not None:
                info = "Question Card **{0.id}** by {1}\n```\n\"{0.text}\"\nused {0.occurences} time{2}\ncreated {3}```\nUse `{4}cards edit {0.id}` to edit this card`"
                return Response(info.format(card, self.get_global_user(card.creator_id).mention, "s" if card.occurences != 1 else "", prettydate(card.creation_date), self.config.command_prefix))
        elif argument == "create":
            text = " ".join(leftover_args[1:]) if len(
                leftover_args) > 1 else None
            if text is None:
                return Response("You might want to actually add some text to your card", delete_after=20)
            if len(text) < 3:
                return Response("I think that's a bit too short...", delete_after=20)
            if len(text) > 500:
                return Response("Maybe a bit too long?", delete_after=20)

            if text.count("$") < 1:
                return Response("You need to have at least one blank ($) space", delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card:
                return Response("There's already a question card with a fairly similar content. <{0}>\nUse `{1}qcards info {0}` to find out more about this card".format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_question_card(text, author.id)
            return Response("Successfully created question card **{}**".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number", delete_after=20)

            if card_id is None:
                return Response("You need to provide the question card's id!", delete_after=20)

            text = " ".join(leftover_args[2:]) if len(
                leftover_args) > 2 else None
            if text is None:
                return Response("You might want to actually add some text to your question card", delete_after=20)
            if len(text) < 3:
                return Response("I think that's a bit too short...", delete_after=20)
            if len(text) > 500:
                return Response("Maybe a bit too long?", delete_after=20)

            if text.count("$") < 1:
                return Response("You need to have at least one blank ($) space", delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card and card.id != card_id_value:
                return Response("There's already a question card with a fairly similar content. <{0}>\nUse `{1}qcards info {0}` to find out more about this question card".format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_question_card(card_id, text):
                return Response("Edited question card <**{}**>".format(card_id), delete_after=15)
            else:
                return Response("There's no question card with that id", delete_after=15)
        elif argument == "delete":
            card_id = leftover_args[1].lower().strip() if len(
                leftover_args) > 1 else None

            if card_id is None:
                return Response("You must specify the question card id", delete_after=15)

            if self.cah.cards.remove_question_card(card_id):
                return Response("Deleted question card <**{}**>".format(card_id), delete_after=15)
            else:
                return Response("Could not remove question card <**{}**>".format(card_id), delete_after=15)
        else:
            return await self.cmd_help(channel, ["qcards"])

    async def qcard_viewer(self, channel, author, cards, display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Question Cards | Page {0} of {1}**\n```\n{2}\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<{}> \"{}\"{}"

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
                page_cards_texts.append(card_string.format(
                    p_c.id, p_c.text.replace("$", "_____"), "" if display_additional is None or display_additional(p_c) is None else " | {}".format(display_additional(p_c))))

            interface_msg = await self.safe_send_message(channel, site_interface.format(current_page + 1, total_pages + 1, "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(timeout, author=author, channel=channel, check=msg_check)

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

        await self.safe_send_message(channel, "Closed the question card viewer!", expire_in=20)

    async def cmd_game(self, message, channel, author, leftover_args, game=None):
        """
        Usage:
            {command_prefix}game [name]

        Play a game I guess... Whaddya expect?
        """

        all_funcs = dir(self)
        all_games = list(filter(lambda x: re.search("^g_\w+", x), all_funcs))
        all_game_names = [x[2:] for x in all_games]
        game_list = [{"name": x[2:], "handler": getattr(self, x, None), "description": getattr(
            self, x, None).__doc__.strip(' \t\n\r')} for x in all_games]

        if message.mentions is not None and len(message.mentions) > 0:
            author = message.mentions[0]

        if game is None:
            shuffle(game_list)

            def check(m):
                return (m.content.lower() in ["y", "n", "exit"])

            for current_game in game_list:
                msg = await self.safe_send_message(channel, "*How about this game:*\n\n**{}**\n{}\n\nType *y*, *n* or *exit*".format(current_game["name"], current_game["description"]))
                response = await self.wait_for_message(100, author=author, channel=channel, check=check)

                if not response or response.content.startswith(self.config.command_prefix) or response.content.lower().startswith('exit'):
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
                await self.safe_send_message(channel, "That was all of them.", expire_in=20)
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
                # log("Ignoring my own reaction")
                return False

            if (str(reaction.emoji) in ("⬇", "➡", "⬆", "⬅") or str(reaction.emoji).startswith("📽") or str(reaction.emoji).startswith("💾")) and reaction.count > 1 and user == author:
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
                msg = await self.send_file(channel, game.getImage(cache_location) + ".png", content="**2048**\n{} turn {}".format(str(turn_index) + ("th" if 4 <= turn_index % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(turn_index % 10, "th")), turn_information))
                turn_information = ""
                await self.add_reaction(msg, "⬅")
                await self.add_reaction(msg, "⬆")
                await self.add_reaction(msg, "➡")
                await self.add_reaction(msg, "⬇")
                await self.add_reaction(msg, "📽")
                await self.add_reaction(msg, "💾")

                reaction, user = await self.wait_for_reaction(check=check, message=msg)
                msg = reaction.message  # for some reason this has to be like this
                # self.log ("User accepted. There are " + str (len
                # (msg.reactions)) + " reactions. [" + ", ".join ([str
                # (r.count) for r in msg.reactions]) + "]")

                for reaction in msg.reactions:
                    if str(reaction.emoji) == "📽" and reaction.count > 1:
                        await self.send_file(user, game.getImage(cache_location) + ".gif", content="**2048**\nYour replay:")
                        turn_information = "| *replay has been sent*"

                    if str(reaction.emoji) == "💾" and reaction.count > 1:
                        await self.safe_send_message(user, "The save code is: *{0}*\nUse `{1}game 2048 {2}` to continue your current game".format(escape_dis(game.get_save()), self.config.command_prefix, game.get_save()))
                        turn_information = "| *save code has been sent*"

                    if str(reaction.emoji) in ("⬇", "➡", "⬆", "⬅") and reaction.count > 1:
                        direction = ("⬇", "➡", "⬆", "⬅").index(
                            str(reaction.emoji))

                    # self.log ("This did not match a direction: " + str
                    # (reaction.emoji))

                if direction is None:
                    await self.safe_delete_message(msg)
                    turn_information = "| *You didn't specifiy the direction*" if turn_information is not "" else turn_information

            # self.log ("Chose the direction " + str (direction))
            game.move(direction)
            turn_index += 1
            await self.safe_delete_message(msg)

            if game.won():
                await self.safe_send_message(channel, "**2048**\nCongratulations, you won after {} turns".format(str(turn_index)))
                game_running = False

            if game.lost():
                await self.safe_send_message(channel, "**2048**\nYou lost after {} turns".format(str(turn_index)))
                game_running = False

        await self.send_file(channel, game.getImage(cache_location) + ".gif", content="**2048**\nYour replay:")
        await self.safe_delete_message(msg)

    async def g_Hangman(self, author, channel, additional_args):
        """
        Guess a word by guessing each and every letter
        """

        tries = additional_args[0] if len(additional_args) > 0 else 10

        word = additional_args[1] if len(additional_args) > 1 else re.sub('[^a-zA-Z]', '',
                                                                          random_line(ConfigDefaults.hangman_wordlist))

        alphabet = list("abcdefghijklmnopqrstuvwxyz")
        log("Started a Hangman game with \"" + word + "\"")

        game = GameHangman(word, tries)
        running = True

        def check(m):
            return (m.content.lower() in alphabet or m.content.lower() == word or m.content.lower() == "exit")

        while running:
            current_status = game.get_beautified_string()
            msg = await self.safe_send_message(channel, "**Hangman**\n*{} trie{} left*\n\n{}\n\n`Send the letter you want to guess or type \"exit\" to exit.`".format(game.tries_left, "s" if game.tries_left != 1 else "", current_status))
            response = await self.wait_for_message(300, author=author, channel=channel, check=check)

            if not response or response.content.lower().startswith(self.config.command_prefix) or response.content.lower().startswith('exit'):
                await self.safe_delete_message(msg)
                await self.safe_send_message(channel, "Aborting this Hangman game. Thanks for playing!")
                running = False

            if response.content.lower() == word:
                await self.safe_send_message(channel, "Congratulations, you got it!\nThe word is: *{}*".format(word))
                return

            letter = response.content[0]
            game.guess(letter)

            if game.won:
                await self.safe_send_message(channel, "Congratulations, you got it!\nThe word is: *{}*".format(word))
                running = False

            if game.lost:
                await self.safe_send_message(channel, "You lost!")
                running = False

            await self.safe_delete_message(msg)
            await self.safe_delete_message(response)

    @owner_only
    async def cmd_getemojicode(self, channel, message, emoji):
        """
        Usage:
            {command_prefix}getemojicode emoji

        logs the emoji to the console so that you can retrieve the unicode symbol.
        """

        self.log(emoji)
        await self.safe_delete_message(message)

    # async def cmd_9gag(self, channel, message, leftover_args):
    #     """
    #     Usage:
    #         {command_prefix}9gag
    #
    #     WIP
    #     """
    #     await self.safe_send_message(channel, "Hello there, unworthy peasent.\nThe development of this function has been put on halt. This is due to the following:\n  -9gag currently provides it's animations in a *.webm* format which is not supported by discord.\n   -The conversion of a file to a *.gif* format takes at least 5 seconds which is not acceptable.\n     Also the filesize blows away all of my f\*cking drive space so f\*ck off, kthx.\n  -The 9gag html code has not been formatted in a *MusicBot certified* reading matter. This means\n    that I cannot tell the differences between the website logo and the actual post.\n\n<www.9gag.com>")
    #     # return
    #     current_post = get_posts_from_page(number_of_pages=1)[0]
    #
    #     cached_file = urllib.request.URLopener()
    #     saveloc = "cache/pictures/9gag" + current_post["file_format"]
    #     cached_file.retrieve(current_post["media_url"], saveloc)
    #
    #     if current_post["file_format"] == ".mp4":
    #         clip = editor.VideoFileClip(saveloc)
    #         clip = video.fx.all.resize(clip, newsize=.3)
    #         clip.write_gif("cache/pictures/9gag.gif")
    #         if os.path.exists(saveloc):
    #             os.remove(saveloc)
    #         saveloc = "cache/pictures/9gag.gif"
    #
    #     await self.send_file(channel, saveloc, content="**{}**\nUpvotes: *{}*\nComments: *{}*".format(re.sub("\*", "\*", current_post["title"]), current_post["votes"], current_post["comments"]))
    #
    #     if os.path.exists(saveloc):
    #         os.remove(saveloc)

    # async def nine_gag_get_section(self, channel, message):
        # category_dict = {"🔥": "hot", "📈": "trending", "🆕": "new"}
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

    async def cmd_repeat(self, player):
        """
        Usage:
            {command_prefix}repeat

        Cycles through the repeat options. Default is no repeat, switchable to repeat all or repeat current song.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't change repeat mode! The player is not playing!", expire_in=20)

        player.repeat()

        if player.is_repeatNone:
            return Response(":play_pause: Repeat mode: None", delete_after=20)
        if player.is_repeatAll:
            return Response(":repeat: Repeat mode: All", delete_after=20)
        if player.is_repeatSingle:
            return Response(":repeat_one: Repeat mode: Single", delete_after=20)

    async def cmd_promote(self, player, position=None):
        """
        Usage:
            {command_prefix}promote
            {command_prefix}promote [song position]

        Promotes the last song in the queue to the front.
        If you specify a position, it promotes the song at that position to the front.
        """

        if player.is_stopped:
            raise exceptions.CommandError(
                "Can't modify the queue! The player is not playing!", expire_in=20)

        length = len(player.playlist.entries)

        if length < 2:
            raise exceptions.CommandError(
                "Can't promote! Please add at least 2 songs to the queue!", expire_in=20)

        if not position:
            entry = player.playlist.promote_last()
        else:
            try:
                position = int(position)
            except ValueError:
                raise exceptions.CommandError("This is not a valid song number! Please choose a song \
                    number between 2 and %s!" % length, expire_in=20)

            if position == 1:
                raise exceptions.CommandError(
                    "This song is already at the top of the queue!", expire_in=20)
            if position < 1 or position > length:
                raise exceptions.CommandError("Can't promote a song not in the queue! Please choose a song \
                    number between 2 and %s!" % length, expire_in=20)

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

    async def cmd_playlist(self, channel, author, server, player, leftover_args):
        """
        ///|Load
        `{command_prefix}playlist load <savename> [add | replace] [none | alphabetical | length | random] [startindex | endindex (inclusive)]`
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

        forbidden_savenames = ["showall", "savename", "save", "load", "delete",
                               "builder", "extras", "add", "remove", "save", "exit", "clone", "rename", "extras", "alphabetical", "author", "entries", "playtime", "random"]

        if argument == "save":
            if savename in self.playlists.saved_playlists:
                return Response("Can't save this playlist, there's already a playlist with this name.", delete_after=20)
            if len(savename) < 3:
                return Response("Can't save this playlist, the name must be longer than 3 characters", delete_after=20)
            if savename in forbidden_savenames:
                return Response("Can't save this playlist, this name is forbidden!", delete_after=20)
            if len(player.playlist.entries) < 1:
                return Response("Can't save this playlist, there are no entries in the queue!", delete_after=20)

            if self.playlists.set_playlist([player.current_entry] + list(player.playlist.entries), savename, author.id):
                return Response("Saved your playlist...", delete_after=20)

            return Response("Uhm, something went wrong I guess :D", delete_after=20)

        elif argument == "load":
            if savename not in self.playlists.saved_playlists:
                return Response("Can't load this playlist, there's no playlist with this name.", delete_after=20)

            clone_entries = self.playlists.get_playlist(
                savename, player.playlist)["entries"]

            if load_mode == "replace":
                player.playlist.clear()
                if player.current_entry is not None:
                    player.skip()

            from_index = int(additional_args[2]) - \
                1 if len(additional_args) > 2 else 0
            if from_index >= len(clone_entries) or from_index < 0:
                return Response("Can't load the playlist starting from entry {}. This entry is out of bounds.".format(from_index), delete_after=20)

            to_index = int(additional_args[3]) if len(
                additional_args) > 3 else len(clone_entries)
            if to_index > len(clone_entries) or to_index < 0:
                return Response("Can't load the playlist from the {}. to the {}. entry. These values are out of bounds.".format(from_index, to_index), delete_after=20)

            if to_index - from_index <= 0:
                return Response("No songs to play. RIP.", delete_after=20)

            clone_entries = clone_entries[from_index:to_index]

            sort_modes = {"alphabetical": (lambda entry: entry.title, False), "random": None, "length": (
                lambda entry: entry.duration, True)}

            sort_mode = additional_args[1].lower() if len(
                additional_args) > 1 and additional_args[1].lower() in sort_modes.keys() else "none"

            if sort_mode == "random":
                shuffle(clone_entries)
            elif sort_mode != "none":
                clone_entries = sorted(clone_entries, key=sort_modes[sort_mode][
                                       0], reverse=sort_modes[sort_mode][1])

            await player.playlist.add_entries(clone_entries)
            self.playlists.bump_replay_count(savename)

            return Response("Done. Enjoy your music!", delete_after=10)

        elif argument == "delete":
            if savename not in self.playlists.saved_playlists:
                return Response("Can't delete this playlist, there's no playlist with this name.", delete_after=20)

            self.playlists.remove_playlist(savename)
            return Response("*{}* has been deleted".format(savename), delete_after=20)

        elif argument == "clone":
            if savename not in self.playlists.saved_playlists:
                return Response("Can't clone this playlist, there's no playlist with this name.", delete_after=20)
            clone_playlist = self.playlists.get_playlist(
                savename, player.playlist)
            clone_entries = clone_playlist["entries"]
            extend_existing = False

            if additional_args is None:
                return Response("Please provide a name to save the playlist to", delete_after=20)

            if additional_args[0].lower() in self.playlists.saved_playlists:
                extend_existing = True
            if len(additional_args[0]) < 3:
                return Response("This is not a valid playlist name, the name must be longer than 3 characters", delete_after=20)
            if additional_args[0].lower() in forbidden_savenames:
                return Response("This is not a valid playlist name, this name is forbidden!", delete_after=20)

            from_index = int(additional_args[1]) - \
                1 if len(additional_args) > 1 else 0
            if from_index >= len(clone_entries) or from_index < 0:
                return Response("Can't clone the playlist starting from entry {}. This entry is out of bounds.".format(from_index), delete_after=20)

            to_index = int(additional_args[2]) if len(
                additional_args) > 2 else len(clone_entries)
            if to_index > len(clone_entries) or to_index < 0:
                return Response("Can't clone the playlist from the {}. to the {}. entry. These values are out of bounds.".format(from_index, to_index), delete_after=20)

            if to_index - from_index <= 0:
                return Response("That's not enough entries to create a new playlist.", delete_after=20)

            clone_entries = clone_entries[from_index:to_index]
            if extend_existing:
                self.playlists.edit_playlist(additional_args[0].lower(
                ), player.playlist, new_entries=clone_entries)
            else:
                self.playlists.set_playlist(
                    clone_entries, additional_args[0].lower(), author.id)

            return Response("*{}* {}has been cloned to *{}*".format(savename, "(from the {}. to the {}. index) ".format(str(from_index + 1), str(to_index + 1)) if from_index is not 0 or to_index is not len(clone_entries) else "", additional_args[0].lower()), delete_after=20)

        elif argument == "showall":
            if len(self.playlists.saved_playlists) < 1:
                return Response("There are no saved playlists.\n**You** could add one though. Type *!help playlist* to see how!", delete_after=40)

            response_text = "**Found the following playlists:**\n\n"
            iteration = 1

            sort_modes = {"alphabetical": (lambda playlist: playlist, False), "entries": (lambda playlist: int(
                self.playlists.get_playlist(playlist, player.playlist)["entry_count"]), True), "author": (lambda playlist: self.get_global_user(self.playlists.get_playlist(playlist, player.playlist)["author"]).name, False), "random": None, "playtime": (lambda playlist: sum([x.duration for x in self.playlists.get_playlist(playlist, player.playlist)["entries"]]), True), "replays": (lambda playlist: self.playlists.get_playlist(playlist, player.playlist)["replay_count"], True)}

            sort_mode = leftover_args[1].lower() if len(
                leftover_args) > 1 and leftover_args[1].lower() in sort_modes.keys() else "random"

            if sort_mode == "random":
                sorted_saved_playlists = self.playlists.saved_playlists
                shuffle(sorted_saved_playlists)
            else:
                sorted_saved_playlists = sorted(self.playlists.saved_playlists, key=sort_modes[
                                                sort_mode][0], reverse=sort_modes[sort_mode][1])

            for pl in sorted_saved_playlists:
                infos = self.playlists.get_playlist(pl, player.playlist)
                response_text += "**{}.** **\"{}\"** *by {}*\n```\n  {} entr{}\n  played {} time{}\n  {}```\n\n".format(iteration, pl.replace("_", " ").title(), self.get_global_user(infos["author"]).mention, str(
                    infos["entry_count"]), "ies" if int(infos["entry_count"]) is not 1 else "y", infos["replay_count"], "s" if int(infos["replay_count"]) != 1 else "", format_time(sum([x.duration for x in infos["entries"]]), round_seconds=True, max_specifications=2))
                iteration += 1

            # self.log (response_text)
            return Response(response_text, delete_after=100)

        elif argument == "builder":
            if len(savename) < 3:
                return Response("Can't build on this playlist, the name must be longer than 3 characters", delete_after=20)
            if savename in forbidden_savenames:
                return Response("Can't build on this playlist, this name is forbidden!", delete_after=20)

            self.log("Starting the playlist builder")
            response = await self.playlist_builder(channel, author, server, player, savename)
            return response

        elif argument in self.playlists.saved_playlists:
            infos = self.playlists.get_playlist(
                argument.lower(), player.playlist)

            entries_text = ""
            entries = infos["entries"]
            for i in range(len(entries)):
                entries_text += str(i + 1) + ". " + entries[i].title + " | " + format_time(
                    entries[i].duration, round_seconds=True, max_specifications=2) + "\n"

            response_text = "\"{}\" added by *{}* with {} entr{}\n*playtime: {}*\n\n{}\n```\nTo edit this playlist type \"{}playlist builder {}\"```".format(argument.replace("_", " ").title(), self.get_global_user(
                infos["author"]).mention, str(infos["entry_count"]), "ies" if int(infos["entry_count"]) is not 1 else "y", format_time(sum([x.duration for x in entries])), entries_text, self.config.command_prefix, argument)
            return Response(response_text, reply=True, delete_after=40)

        return await self.cmd_help(channel, ["playlist"])

    async def socket_playlist_load(self, player, playlist_name):
        playlist_name = playlist_name.lower().strip()
        if playlist_name not in self.playlists.saved_playlists:
            return False

        clone_entries = self.playlists.get_playlist(
            playlist_name, player.playlist)["entries"]

        player.playlist.clear()
        if player.current_entry is not None:
            player.skip()

        await player.playlist.add_entries(clone_entries)
        self.playlists.bump_replay_count(playlist_name)

    async def playlist_builder(self, channel, author, server, player, _savename):
        if _savename not in self.playlists.saved_playlists:
            self.playlists.set_playlist([], _savename, author.id)

        def check(m):
            return (
                m.content.split()[0].lower() in [
                    "add", "remove", "rename", "exit", "p", "n", "save", "extras"]
            )

        abort = False
        save = False
        entries_page = 0
        pl_changes = {"remove_entries_indexes": [],
                      "new_entries": [], "new_name": None}
        savename = _savename
        user_savename = savename

        interface_string = "**{}** by *{}* ({} song{} with a total length of {})\n\n{}\n\n**You can use the following commands:**\n`add`: Add a video to the playlist (this command works like the normal `{}play` command)\n`remove index (index2 index3 index4)`: Remove a song from the playlist by it's index\n`rename newname`: rename the current playlist\n`extras`: see the special functions\n\n`p`: previous page\n`n`: next page\n`save`: save and close the builder\n`exit`: leave the builder without saving"

        extras_string = "**{}** by *{}* ({} song{} with a total length of {})\n\n**Extra functions:**\n`sort [alphabetical, length, random]`: sort the playlist (default is alphabetical)\n`removeduplicates`: remove all duplicates from the playlist\n\n`abort`: return to main screen"

        edit_string = "**{}** by *{}* ({} song{} with a total length of {})\n```\nentry_information\n```\n\n**Edit functions:**\n`rename <newname>`: rename the entry\n`setstart <timestamp>`: set the starting time of the song\n`setend <timestamp>`: set the ending time of the song\n\n`abort`: return to main screen"

        playlist = self.playlists.get_playlist(_savename, player.playlist)

        while (not abort) and (not save):
            entries = playlist["entries"]
            entries_text = ""

            items_per_page = 20
            iterations, overflow = divmod(len(entries), items_per_page)

            if iterations > 0 and overflow == 0:
                iterations -= 1

            start = (entries_page * items_per_page)
            end = (start + (overflow if entries_page >=
                            iterations else items_per_page)) if len(entries) > 0 else 0
            # this_page_entries = entries [start : end]

            # self.log ("I have {} entries in the whole list and now I'm
            # viewing from {} to {} ({} entries)".format (str (len (entries)),
            # str (start), str (end), str (end - start)))

            for i in range(start, end):
                entries_text += str(i + 1) + ". " + entries[i].title + "\n"
            entries_text += "\nPage {} of {}".format(
                entries_page + 1, iterations + 1)

            interface_message = await self.safe_send_message(channel, interface_string.format(user_savename.replace("_", " ").title(), self.get_global_user(playlist["author"]).mention, playlist["entry_count"], "s" if int(playlist["entry_count"]) is not 1 else "", format_time(sum([x.duration for x in entries])), entries_text, self.config.command_prefix))
            response_message = await self.wait_for_message(author=author, channel=channel, check=check)

            if not response_message:
                await self.safe_delete_message(interface_message)
                abort = True
                break

            elif response_message.content.lower ().startswith(self.config.command_prefix) or \
                    response_message.content.lower().startswith('exit'):
                abort = True

            elif response_message.content.lower().startswith("save"):
                save = True

            split_message = response_message.content.split()
            arguments = split_message[1:] if len(split_message) > 1 else None

            if split_message[0].lower() == "add":
                if arguments is not None:
                    msg = await self.safe_send_message(channel, "I'm working on it.")
                    query = arguments[1:]
                    try:
                        start_time = datetime.now()
                        entries = await self.get_play_entry(player, channel, author, query, arguments[0])
                        if (datetime.now() - start_time).total_seconds() > 40:
                            await self.safe_send_message(author, "Wow, that took quite a while.\nI'm done now though so come check it out!", expire_in=70)

                        pl_changes["new_entries"].extend(entries)
                        playlist["entries"].extend(entries)
                        playlist["entry_count"] = str(
                            int(playlist["entry_count"]) + len(entries))
                        it, ov = divmod(
                            int(playlist["entry_count"]), items_per_page)
                        entries_page = it
                    except:
                        await self.safe_send_message(channel, "Something went terribly wrong there.", expire_in=20)
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
                    playlist["entry_count"] = str(
                        int(playlist["entry_count"]) - len(indieces))
                    playlist["entries"] = [playlist["entries"][x] for x in range(
                        len(playlist["entries"])) if x not in indieces]

            elif split_message[0].lower() == "rename":
                if arguments is not None and len(arguments[0]) >= 3 and arguments[0] not in self.playlists.saved_playlists:
                    pl_changes["new_name"] = re.sub(
                        "\W", "", arguments[0].lower())
                    user_savename = pl_changes["new_name"]

            elif split_message[0].lower() == "extras":
                def extras_check(m):
                    return (m.content.split()[0].lower() in ["abort", "sort", "removeduplicates"])

                extras_message = await self.safe_send_message(channel, extras_string.format(user_savename.replace("_", " ").title(), self.get_global_user(playlist["author"]).mention, playlist["entry_count"], "s" if int(playlist["entry_count"]) is not 1 else "", format_time(sum([x.duration for x in entries]))))
                resp = await self.wait_for_message(author=author, channel=channel, check=extras_check)

                if not resp.content.lower().startswith(self.config.command_prefix) and not resp.content.lower().startswith('abort'):
                    _cmd = resp.content.split()
                    cmd = _cmd[0].lower()
                    args = _cmd[1:] if len(_cmd) > 1 else None

                    if cmd == "sort":
                        sort_method = args[0].lower() if args is not None and args[0].lower() in [
                            "alphabetical", "length", "random"] else "alphabetical"
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

                await self.safe_delete_message(extras_message)
                await self.safe_delete_message(resp)

            elif split_message[0].lower() == "p":
                entries_page = (entries_page - 1) % (iterations + 1)

            elif split_message[0].lower() == "n":
                entries_page = (entries_page + 1) % (iterations + 1)

            await self.safe_delete_message(response_message)
            await self.safe_delete_message(interface_message)

        if abort:
            return Response("Closed *{}* without saving".format(savename))
            self.log("Closed the playlist builder")

        if save:
            # self.log ("Going to remove the following entries: {} |
            # Adding these entries: {} | Changing the name to: {}".format
            # (pl_changes ["remove_entries_indexes"], ", ".join ([x.title for x
            # in pl_changes ["new_entries"]]), pl_changes ["new_name"]))
            self.playlists.edit_playlist(savename, player.playlist, new_entries=pl_changes[
                                         "new_entries"], remove_entries_indexes=pl_changes["remove_entries_indexes"], new_name=pl_changes["new_name"])
            self.log(
                "Closed the playlist builder and saved the playlist")
            return Response("Successfully saved *{}*".format(user_savename.replace("_", " ").title()))

    async def cmd_addplayingtoplaylist(self, channel, author, player, playlistname):
        """
        Usage:
            {command_prefix}addplayingtoplaylist <playlistname>

        Add the current entry to a playlist
        """

        if playlistname is None:
            return Response("Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response("There's nothing playing right now so I can't add it to your playlist...")

        if playlistname not in self.playlists.saved_playlists:
            if len(playlistname) < 3:
                return Response("Your name is too short. Please choose one with at least three letters.")
            self.playlists.set_playlist(
                [player.current_entry], playlistname, author.id)
            return Response("Created a new playlist and added the currently playing song.")

        self.playlists.edit_playlist(
            playlistname, player.playlist, new_entries=[player.current_entry])
        return Response("Added the current song to the playlist.")

    async def cmd_removeplayingfromplaylist(self, channel, author, player, playlistname):
        """
        Usage:
            {command_prefix}removeplayingfromplaylist <playlistname>

        Remove the current entry from a playlist
        """

        if playlistname is None:
            return Response("Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response("There's nothing playing right now so I can't add it to your playlist...")

        if playlistname not in self.playlists.saved_playlists:
            return Response("There's no playlist with this name.")

        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[player.current_entry])
        return Response("Removed the current song from the playlist.")

    async def cmd_setentrystart(self, player, playlistname):
        """
        Usage:
            {command_prefix}setentrystart <playlistname>

        Set the start time for the current entry in the playlist to the current time
        """

        if playlistname is None:
            return Response("Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response("There's nothing playing right now...", delete_after=20)

        new_start = player.progress
        new_entry = player.current_entry
        new_entry.set_start(new_start)
        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[player.current_entry], new_entries=[new_entry])

        return Response("Set the starting point to {} seconds.".format(new_start), delete_after=20)

    async def cmd_setentryend(self, player, playlistname):
        """
        Usage:
            {command_prefix}setentryend <playlistname>

        Set the end time for the current entry in the playlist to the current time
        """

        if playlistname is None:
            return Response("Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response("There's nothing playing right now...", delete_after=20)

        new_end = player.progress
        new_entry = player.current_entry
        new_entry.set_end(new_end)
        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[player.current_entry], new_entries=[new_entry])

        return Response("Set the ending point to {} seconds.".format(new_start), delete_after=20)

    async def cmd_setplayingname(self, player, playlistname, new_name, leftover_args):
        """
        Usage:
            {command_prefix}setplayingname <playlistname> <new name>

        Set the name of the current song
        """
        new_title = new_name + " " + " ".join(leftover_args)

        if playlistname is None:
            return Response("Please specify the playlist's name!", delete_after=20)

        playlistname = playlistname.lower()

        if not player.current_entry:
            return Response("There's nothing playing right now...", delete_after=20)

        if len(new_title) > 500 or len(new_title) < 3:
            return Response("The new title has to be at least 3 characters long", delete_after=20)

        new_entry = player.current_entry
        new_entry.set_title(new_title)
        self.playlists.edit_playlist(
            playlistname, player.playlist, remove_entries=[player.current_entry], new_entries=[new_entry])

        return Response("The new title is \"{}\"".format(new_title), delete_after=20)

    async def cmd_wiki(self, channel, message, leftover_args):
        """
        Usage:
            {command_prefix}wiki [language] summarize [number of sentences] <query>
                -This function summarizes the content of a Wikipedia page

            {command_prefix}wiki [language] <query>
                -This function provides the full Wikipedia article.
        """

        wikipedia_page = None
        wikipedia_page_title = None
        wikipedia.set_lang("en")

        if leftover_args[0].lower() in wikipedia.languages().keys():
            wikipedia.set_lang(leftover_args[0].lower())
            del (leftover_args[0])
        elif leftover_args[0].lower() in wikipedia.languages().values():
            wikipedia.set_lang(list(mydict.keys())[list(
                mydict.values()).index(leftover_args[0].lower())])
            del (leftover_args[0])

        search_query = " ".join(leftover_args)

        if "simon berger" in search_query.lower() or "simon jonas berger" in search_query.lower():
            already_used = load_file("data/simon_berger_wikied.txt")

            if author.id in already_used:
                return Response("I mustn't betray my master twice for you!")
            else:
                already_used.append(author.id)
                write_file("data/simon_berger_wikied.txt", already_used)

            return Response("**Simon Berger**\nSimon Jonas Berger (born March 28, 1992) is a computer scientist and works at Google London as head of the Technical Solutions team.\nI didn't actually expect anyone to read this far, but apparently you are...\nLet me tell you something about my past then. I went to Kindergarten one year earlier than normal. This is due to the fact, that one Doctor\nthought that I was a genius (of course that turned out to be wrong). I skipped 4th grade, not because I wanted, but because my teacher\npersuaded my parents to do so. I especially loved that teacher and was sincerely upset about that. I went to the gymnasium after 8th grade.Shortly after, at the age of 15, my parents passed away in a car accident so I went to live with my grandparents but 2 months later\nI lived in a flat in Zurich to study at ETH. Because I practically skipped 2 years of education I was merely 16 while everyone around me was already 18. With the age of 20 I got my Bachelor's degree and at the age of 22 I finished my Master's degree. While I was studying at ETH I got the chance to take part in a Google Interview. After 2 interviews they offered me a job as a Technical Solutions Consultant. June 25th 2016 they promoted me to head of Technical Solutions.\n\nWhy am I telling you this? Well... If you went ahead and looked me up I'm sure you were just a little bit interested.")

        # self.log (search_query)

        if leftover_args[0] == "summarize":
            sent_num = int(leftover_args[1]) if str(
                type(leftover_args[1])) == "int" else 5
            search = leftover_args[2:] if str(
                type(leftover_args[1])) == "int" else leftover_args[1:]
            title = wikipedia.search(search, results=1, suggestion=True)[0]
            return Response("**{}**\n{}".format(title[0], wikipedia.summary(title, sentences=sent_num)))
        else:
            title = wikipedia.search(
                search_query, results=1, suggestion=True)[0]
            if title:
                wikipedia_page = wikipedia.page(title=title)
                wikipedia_page_title = title[0]

        if not wikipedia_page:
            return Response("I didn't find anything called *{}*.".format(search_query), delete_after=20)

        return Response("**{}**\n{}".format(wikipedia_page_title, wikipedia.summary(wikipedia_page_title, sentences=3)))

    async def cmd_getmusicfile(self, channel, author, player, index=0):
        """
        Usage:
            {command_prefix}getmusicfile
            {command_prefix}getmusicfile index

        Get the music file of the current song.
        You may provide an index to get that file.
        """

        try:
            index = int(index) - 1
        except:
            return Response("Please provide a valid index", delete_after=30)

        if index == -1:
            entry = player.current_entry
        else:
            if index < 0 or index >= len(player.playlist.entries):
                return Response("Your index is out of range", delete_after=15)
            entry = player.playlist.entries[index]

        if not entry:
            return Response("This entry is currently being worked on. Please retry again later", delete_after=15)

        if type(entry).__name__ == "StreamPlaylistEntry":
            return Response("Can't send you this because it's a live stream", delete_after=15)

        if not entry.is_downloaded:
            try:
                await entry._download()
            except:
                return Response("Could not download the file. This really shouldn't happen")

        await self.safe_send_message(author, "The file is being uploaded. Please wait a second.", delete_after=15)
        await self.send_file(author, entry.filename, content="Here you go:")

    async def cmd_reminder(self, channel, author, player, server, leftover_args):
        """
        Usage:
            {command_prefix}reminder create
            {command_prefix}reminder list

        Create a reminder!
        """

        if len(leftover_args) < 1:
            return Response("Please git gud!")

        command = leftover_args[0].lower().strip()

        if(command == "create"):
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

            msg = await self.safe_send_message(channel, "How do you want to call your reminder?")
            response = await self.wait_for_message(author=author, channel=channel, check=check)
            reminder_name = response.content
            await self.safe_delete_message(msg)
            await self.safe_delete_message(response)

            # find out the due date
            while True:
                msg = await self.safe_send_message(channel, "When is it due?")
                response = await self.wait_for_message(author=author, channel=channel)

                reminder_due = datetime(
                    *cal.parse(response.content.strip().lower())[0][:6])
                await self.safe_delete_message(msg)
                if reminder_due is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # repeated reminder
            while True:
                msg = await self.safe_send_message(channel, "When should this reminder be repeated? (\"never\" if not at all)")
                response = await self.wait_for_message(author=author, channel=channel)
                await self.safe_delete_message(msg)
                if(response.content.lower().strip() in ("n", "no", "nope", "never")):
                    await self.safe_delete_message(response)
                    reminder_repeat = None
                    break

                reminder_repeat = datetime(
                    *cal.parse(response.content.strip().lower())[0][:6]) - datetime.now()
                if reminder_repeat is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # reminder end
            if reminder_repeat is not None:
                while True:
                    msg = await self.safe_send_message(channel, "When should this reminder stop being repeated? (\"never\" if not at all)")
                    response = await self.wait_for_message(author=author, channel=channel)
                    await self.safe_delete_message(msg)
                    if(response.content.lower().strip() in ("n", "no", "nope", "never")):
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
                msg = await self.safe_send_message(channel, "**Select one:**\n```\n1: Send a message\n2: Play a video\n3: Play an alarm sound```")
                response = await self.wait_for_message(author=author, channel=channel)
                await self.safe_delete_message(msg)
                selected_action = int(response.content)

                if selected_action is not None:
                    await self.safe_delete_message(response)
                    break

                await self.safe_delete_message(response)

            # action 1 (message)
            if selected_action == 1:
                action_message = "Your reminder *{reminder.name}* is due"
                action_channel = None
                action_delete_after = 0
                action_delete_previous = False

                # find message
                msg = await self.safe_send_message(channel, "What should the message say?")
                response = await self.wait_for_message(author=author, channel=channel)
                action_message = response.content
                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find channel
                while action_channel is None:
                    msg = await self.safe_send_message(channel, "To which channel should the message be sent?\n*Possible inputs:*\n\n:white_small_square: Channel id or channel name\n:white_small_square: \"me\" for a private message\n:white_small_square: \"this\" to select the current channel\n:white_small_square: You can also @mention people or #mention a channel")
                    response = await self.wait_for_message(author=author, channel=channel)

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
                        if m.content.lower().strip() in ["never", "no"] or int(m.content.strip()) >= 0:
                            return True
                        else:
                            return False
                    except:
                        return False

                msg = await self.safe_send_message(channel, "After how many seconds should the message be deleted? (\"never\" for not at all)")
                response = await self.wait_for_message(author=author, channel=channel, check=check)
                if response.content.lower().strip() in ["never", "no"]:
                    action_delete_after = 0
                else:
                    action_delete_after = int(response.content.strip())

                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find if delete old message
                if reminder_repeat is not None:
                    msg = await self.safe_send_message(channel, "Before sending a new message, should the old one be deleted?")
                    response = await self.wait_for_message(author=author, channel=channel)
                    if response.content.lower().strip() in ["y", "yes"]:
                        action_delete_previous = True

                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)

                reminder_action = Action(channel=action_channel, msg_content=action_message,
                                         delete_msg_after=action_delete_after, delete_old_message=action_delete_previous)

            # action 2 (play url)
            elif selected_action == 2:
                action_source_url = ""
                action_voice_channel = None

                # find video url
                msg = await self.safe_send_message(channel, "What's the url of the video you want to play?")
                response = await self.wait_for_message(author=author, channel=channel)
                action_source_url = response.content
                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

                # find playback channel
                msg = await self.safe_send_message(channel, "To which channel should the video be played?\n*Possible inputs:*\n\n:white_small_square: Channel id or channel name\n:white_small_square: \"this\" to select your current channel")
                response = await self.wait_for_message(author=author, channel=channel)

                if response.content.lower().strip() == "this":
                    return Response("not yet implemented :P")
                else:
                    return Response("not yet implemented :P")

            # action 3 (play predefined)
            elif selected_action == 3:
                pass

            # finalizing
            self.calendar.create_reminder(
                reminder_name, reminder_due, reminder_action, repeat_every=reminder_repeat, repeat_end=reminder_end)
            return Response("Created a reminder called *{}*\ndue: {}\nrepeat: {}\nrepeat end: {}\naction: {}".format(reminder_name, reminder_due, reminder_repeat, reminder_end, reminder_action))

        elif(command == "list"):
            if len(self.calendar.reminders) < 1:
                return Response("There are no reminders")

            text = ""
            for reminder in self.calendar.reminders:
                text += "*{.name}*\n".format(reminder)

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
        # log("\n{}\nin: {};\nevery: {};\nuntil: {}".format(reminder_name, due_date, repeat_every, repeat_end))
        #
        # action = Action(
        #     channel=channel, msg_content="**Reminder {reminder.name} is due!**", delete_msg_after=5)
        #
        # self.calendar.create_reminder(reminder_name, due_date, action, repeat_every=repeat_every, repeat_end=repeat_end)
        # return Response("Got it, I'll remind you!")

    async def cmd_moveus(self, channel, server, author, message, leftover_args):
        """
        Usage:
            {command_prefix}moveus channel name

        Move everyone in your current channel to another one!
        """

        if len(leftover_args) < 1:
            return Response("You need to provide a target channel")

        search_channel = " ".join(leftover_args)
        if search_channel.lower().strip() == "home":
            search_channel = "MusicBot's reign"

        if author.voice.voice_channel is None:
            return Response("You're incredibly incompetent to do such a thing!")

        author_channel = author.voice.voice_channel.id

        target_channel = self.get_channel(search_channel)
        if target_channel is None:
            for chnl in server.channels:
                if chnl.name == search_channel and chnl.type == ChannelType.voice:
                    target_channel = chnl
                    break

        if target_channel is None:
            return Response("Can't resolve the target channel!", delete_after=20)

        log("there are {} members in this voice chat".format(
            len(self.get_channel(author_channel).voice_members)))

        s = 0
        for voice_member in self.get_channel(author_channel).voice_members:
            await self.move_member(voice_member, target_channel)
            s += 1

        log("moved {} users from {} to {}".format(
            s, author.voice.voice_channel, target_channel))

        if server.me.voice.voice_channel.id == self.get_channel(author_channel).id:
            log("moving myself")
            await self.get_voice_client(target_channel)

    async def cmd_mobile(self, channel, player, server):
        """
        Usage:
            {command_prefix}mobile

        WIP
        """

        count = len(self.socket_server.connections)
        return Response("There {} currently {} mobile user{}".format("is" if count == 1 else "are", count, "s" if count != 1 else ""))

    @owner_only
    async def cmd_execute(self, player, channel, author, server, leftover_args):
        statement = " ".join(leftover_args)
        statement = statement.replace("/n/", "\n")
        statement = statement.replace("/t/", "\t")

        await self.safe_send_message(channel, "```python\n{}\n```".format(statement))
        try:
            result = eval(statement)
            return Response(str(result))
        except Exception as e:
            try:
                result = exec(statement)
                return Response(str(result))
            except Exception as a:
                if str(a) == str(e):
                    return Response("Le Error:\n```\n{}\n```".format(str(e)))
                else:
                    return Response("Les Errors:\n```\n{}\n```\n```\n{}\n```".format(str(e), str(a)))

    async def cmd_skipto(self, player, timestamp):
        """
        Usage:
            {command_prefix}skipto <timestamp>

        Go to the given timestamp formatted (minutes:seconds)
        """

        parts = timestamp.split(":")
        if len(parts) < 1:  # Shouldn't occur, but who knows?
            return Response("Please provide a valid timestamp", delete_after=20)

        # seconds, minutes, hours, days
        values = (1, 60, 60 * 60, 60 * 60 * 24)

        secs = 0
        for i in range(len(parts)):
            try:
                v = int(parts[i])
            except:
                continue

            j = len(parts) - i - 1
            if j >= len(values):  # If I don't have a conversion from this to seconds
                continue
            secs += v * values[j]

        if player.current_entry is None:
            return Response("Nothing playing!", delete_after=20)

        if not player.goto_seconds(secs):
            return Response("Timestamp exceeds song duration!", delete_after=20)

    async def cmd_register(self, author, server, token):
        """
        Usage:
            {command_prefix}register <token>

        Use this function to register your phone in order to control the musicbot
        """

        if await self.socket_server.register_handler(token, server.id, author.id):
            return Response("Successful")
        else:
            return Response("Something went wrong there")

    async def cmd_disconnect(self, server):
        """
        Usage:
            {command_prefix}disconnect

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
            return index_to_alphabet(ind - remainder) + alphabet[remainder].upper()

        msgs_by_member = {}
        msgs_by_date = OrderedDict()
        answers_by_date = OrderedDict()
        channel = server.get_channel(channel_id)
        last_msg = None
        last_answer = None
        spam = 0

        async for msg in self.logs_from(channel, limit=int(number)):
            increment = 1
            if last_msg is not None and msg.author.id == last_msg.author.id and abs((last_msg.timestamp - msg.timestamp).total_seconds()) < 10:
                spam += 1
                last_msg = msg
                increment = 0

            if last_answer is None or last_answer.author != msg.author:
                dt = answers_by_date.get(
                    "{0.day:0>2}/{0.month:0>2}/{0.year:0>4}".format(msg.timestamp), {})
                dt[msg.author.id] = dt.get(msg.author.id, 0) + increment
                answers_by_date[
                    "{0.day:0>2}/{0.month:0>2}/{0.year:0>4}".format(msg.timestamp)] = dt
                last_answer = msg

            existing_msgs = msgs_by_member.get(msg.author.id, [0, 0])
            existing_msgs[0] += increment
            existing_msgs[1] += len(re.sub(r"\W", r"", msg.content))
            msgs_by_member[msg.author.id] = existing_msgs
            dt = msgs_by_date.get(
                "{0.day:0>2}/{0.month:0>2}/{0.year:0>4}".format(msg.timestamp), {})
            dt[msg.author.id] = dt.get(msg.author.id, 0) + increment
            msgs_by_date[
                "{0.day:0>2}/{0.month:0>2}/{0.year:0>4}".format(msg.timestamp)] = dt
            last_msg = msg

        wb = Workbook()
        ws = wb.active
        ws.title = "Messages"
        ws2 = wb.create_sheet("Answers")
        ws["A2"] = "TOTAL"
        sorted_user_index = {}
        i = 1
        for member in sorted(msgs_by_member):
            data = msgs_by_member[member]
            ws["{}{}".format("A", i)] = server.get_member(
                member).name if server.get_member(member) is not None else "Unknown"
            ws["{}{}".format("B", i)] = data[0]
            ws["{}{}".format("C", i)] = data[1]
            sorted_user_index[member] = index_to_alphabet(i)
            i += 1

        i += 1
        for date in reversed(msgs_by_date.keys()):
            ws["A" + str(i)] = date
            for mem in msgs_by_date[date]:
                ws["{}{}".format(sorted_user_index.get(mem), i)
                   ] = msgs_by_date[date][mem]
            i += 1

        i = 1
        for date in reversed(answers_by_date.keys()):
            ws2["A" + str(i)] = date
            for mem in answers_by_date[date]:
                ws2["{}{}".format(sorted_user_index.get(mem), i)
                    ] = answers_by_date[date][mem]
            i += 1

        wb.save("cache/last_data.xlsx")

        await self.send_file(author, open("cache/last_data.xlsx", "rb"), filename='%s-msgs.xlsx' % (server.name.replace(' ', '_')))

    @owner_only
    async def cmd_surveyserver(self, server):
        if self.online_loggers.get(server.id, None) is not None:
            return Response("I'm already looking at this server")
        else:
            asyncio.ensure_future(self.online_member_checker(server))
            return Response("okay, okay!")

    @owner_only
    async def cmd_evalsurvey(self, server, author):
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        online_logger.create_output()
        await self.send_file(author, open("cache/last_survey_data.xlsx", "rb"), filename='%s-survey.xlsx' % (server.name.replace(' ', '_')))
        return Response("There you go, fam", delete_after=10)

    @owner_only
    async def cmd_resetsurvey(self, server):
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        online_logger.reset()
        return Response("Well then")

    async def online_member_checker(self, server):
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            online_logger = OnlineLogger(self)
            self.online_loggers[server.id] = online_logger

        next_autosave = datetime.now() + timedelta(minutes=5)

        while True:
            for member in server.members:
                online_logger.update_stats(
                    member.id, member.status == discord.Status.online, member.game)
                if datetime.now() > next_autosave:
                    next_autosave = datetime.now() + timedelta(minutes=5)
                    online_logger.create_output()
                await asyncio.sleep(1)
                notification = online_logger.get_notification()
                if notification is not None:
                    game_name, user_id, receiver_ids = notification
                    user_name = self.get_global_user(user_id).name
                    message_text = "{} started playing {} at {0.hour:0>2}:{0.minute:0>2}".format(
                        user_name, game_name, datetime.now())
                    for recv in receiver_ids:
                        if recv == user_id:
                            continue

                        await self.safe_send_message(self.get_global_user(recv), message_text)

            await asyncio.sleep(65)

    async def cmd_notifyme(self, server, author):
        """
        Usage:
            {command_prefix}notifyme

        Get notified when someone starts playing
        """
        online_logger = self.online_loggers.get(server.id, None)
        if online_logger is None:
            return Response("I'm not even spying here")
        online_logger.add_listener(author.id)
        return Response("Got'cha!")

    async def cmd_livetranslator(self, target_language=None, mode="1"):
        """
        Usage:
            {command_prefix}livetranslator [language code] [mode]

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
                return Response("You should provide the language code you want me to translate to in order for me to work")
        if target_language in ['af', 'ar', 'bg', 'bn', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'es', 'et', 'fa', 'fi', 'fr', 'gu', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml', 'mr', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'so', 'sq', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur', 'vi', 'zh-cn', 'zh-tw']:
            self.instant_translate = True
            self.translator.to_lang = target_language
            try:
                mode = int(mode)
            except:
                mode = 1
            if not (0 <= mode <= 2):
                mode = 1
            self.instant_translate_mode = mode

            return Response("Starting now!")
        else:
            return Response("Please provide the iso format language code")

    async def cmd_translatehistory(self, author, message, leftover_args):
        """
        ///|Usage
        `{command_prefix}translatehistory <channel> <start date | number of messages> <target language>`
        ///|Explanation
        Request messages in a channel to be translated.\nYou can specify the amount of messages either by number or by a starting point formated like `DAY/MONTH/YEAR HOUR:MINUTE`
        """
        starting_point = " ".join(leftover_args[1:-1])
        target_language = leftover_args[-1].lower()

        if target_language not in ['af', 'ar', 'bg', 'bn', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'es', 'et', 'fa', 'fi', 'fr', 'gu', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml', 'mr', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'so', 'sq', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur', 'vi', 'zh-cn', 'zh-tw']:
            return Response("Please provide the target language")

        if message.channel_mentions is None or len(message.channel_mentions) < 1:
            return Response("Please provide a channel to take the messages from", delete_after=20)
        channel = message.channel_mentions[0]

        limit = 500
        start_point = None
        try:
            limit = int(starting_point)
        except:
            match = re.match(
                "(\d{1,2})\/(\d{1,2})\/(\d{4}).{1}(\d{1,2}):(\d{1,2})", starting_point)
            if match is None:
                return Response("I don't understand your starting point...\nBe sure to format it like `DAY/MONTH/YEAR HOUR:MINUTE`", delete_after=20)
            day, month, year, hour, minute = match.group(1, 2, 3, 4, 5)
            start_point = datetime(year, month, day, hour, minute)

        em = Embed(title="TRANSLATION")
        translator = Translator(target_language)
        async for message in self.logs_from(channel, limit=limit, after=start_point):
            n = "**{0}** - {1.year:0>4}/{1.month:0>2}/{1.day:0>2} {1.hour:0>2}:{1.minute:0>2}".format(
                message.author.display_name, message.timestamp)

            message_content = message.content.strip()
            msg_language, probability = self.lang_identifier.classify(
                message_content)
            self.translator.from_lang = msg_language
            try:
                v = "`{}`".format(translator.translate(message_content))
            except:
                continue
            em.add_field(name=n, value=v, inline=False)
        em._fields = em._fields[::-1]
        await self.send_message(author, embed=em)
        return Response("Done!")

    @owner_only
    async def cmd_shutdown(self, channel):
        await self.safe_send_message(channel, ":wave:")
        await self.disconnect_all_voice_clients()
        raise exceptions.TerminateSignal

    async def on_message(self, message):
        await self.wait_until_ready()

        message_content = message.content.strip()

        if not message_content.startswith(self.config.command_prefix):
            # if message.channel.id in self.config.bound_channels and message.author != self.user and not message.author.bot:
            # await self.cmd_c(message.author, message.channel,
            # message_content.split())
            try:
                msg_language, probability = self.lang_identifier.classify(
                    message_content)

                if probability > .7 and self.instant_translate and msg_language != self.translator.to_lang and message.author != self.user:
                    self.translator.from_lang = msg_language
                    if self.instant_translate_mode == 1:
                        await self.safe_send_message(message.channel, "Translation: `{}`".format(self.translator.translate(message_content)))
                    elif self.instant_translate_mode == 2:
                        em = Embed(colour=message.author.colour)
                        em.set_author(name=message.author.display_name,
                                      icon_url=message.author.avatar_url)
                        em.add_field(
                            value=self.translator.translate(message_content), name="Translated")
                        # em.set_footer(text=message.content)
                        await self.send_message(message.channel, embed=em)
                        await self.safe_delete_message(message)
                        return
            except:
                raise
                print("couldn't translate the message")

            return

        if message.author == self.user:
            self.log("Ignoring command from myself (%s)" %
                     message.content)
            return

        if self.config.bound_channels and message.channel.id not in self.config.bound_channels and not message.channel.is_private:
            if message_content.split()[0][len(self.config.command_prefix):].lower().strip() not in self.channelFreeCommands:
                return  # if I want to log this I just move it under the prefix check

        # Uh, doesn't this break prefixes with spaces in them (it doesn't,
        # config parser already breaks them)
        command, *args = message_content.split()
        command = command[len(self.config.command_prefix):].lower().strip()

        handler = getattr(self, 'cmd_%s' % command, None)
        if not handler:
            return

        if message.channel.is_private:
            if not (message.author.id == self.config.owner_id and command == 'joinserver') and not command in self.privateChatCommands:
                await self.send_message(message.channel, 'You cannot use this command in private messages.')
                return

        if message.author.id in self.blacklist and message.author.id != self.config.owner_id:
            self.log(
                "[User blacklisted] {0.id}/{0.name} ({1})".format(message.author, message_content))
            return

        else:
            self.log(
                "[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))

        user_permissions = self.permissions.for_user(message.author)

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()

        # noinspection PyBroadException
        try:
            if user_permissions.ignore_non_voice and command in user_permissions.ignore_non_voice:
                await self._check_ignore_non_voice(message)

            handler_kwargs = {}
            if params.pop('message', None):
                handler_kwargs['message'] = message

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('server', None):
                handler_kwargs['server'] = message.server

            if params.pop('player', None):
                handler_kwargs['player'] = await self.get_player(message.channel)

            if params.pop('permissions', None):
                handler_kwargs['permissions'] = user_permissions

            if params.pop('user_mentions', None):
                handler_kwargs['user_mentions'] = list(
                    map(message.server.get_member, message.raw_mentions))

            if params.pop('channel_mentions', None):
                handler_kwargs['channel_mentions'] = list(
                    map(message.server.get_channel, message.raw_channel_mentions))

            if params.pop('voice_channel', None):
                handler_kwargs[
                    'voice_channel'] = message.server.me.voice_channel

            if params.pop('leftover_args', None):
                handler_kwargs['leftover_args'] = args

            args_expected = []
            for key, param in list(params.items()):
                doc_key = '[%s=%s]' % (
                    key, param.default) if param.default is not inspect.Parameter.empty else key
                args_expected.append(doc_key)

                if not args and param.default is not inspect.Parameter.empty:
                    params.pop(key)
                    continue

                if args:
                    arg_value = args.pop(0)
                    handler_kwargs[key] = arg_value
                    params.pop(key)

            if message.author.id != self.config.owner_id:
                if user_permissions.command_whitelist and command not in user_permissions.command_whitelist:
                    raise exceptions.PermissionsError(
                        "This command is not enabled for your group (%s)." % user_permissions.name,
                        expire_in=20)

                elif user_permissions.command_blacklist and command in user_permissions.command_blacklist:
                    raise exceptions.PermissionsError(
                        "This command is disabled for your group (%s)." % user_permissions.name,
                        expire_in=20)

            if params:
                docs = getattr(handler, '__doc__', None)
                if not docs:
                    docs = 'Usage: {}{} {}'.format(
                        self.config.command_prefix,
                        command,
                        ' '.join(args_expected)
                    )

                docs = '\n'.join(l.strip() for l in docs.split('\n'))
                await self.safe_send_message(
                    message.channel,
                    '```\n%s\n```' % docs.format(
                        command_prefix=self.config.command_prefix),
                    expire_in=60
                )
                return

            response = await handler(**handler_kwargs)
            if response and isinstance(response, Response):
                content = response.content
                if response.reply:
                    content = '%s, %s' % (message.author.mention, content)

                sentmsg = await self.safe_send_message(
                    message.channel, content,
                    expire_in=response.delete_after if self.config.delete_messages else 0,
                    also_delete=message if self.config.delete_invoking else None
                )

        except (exceptions.CommandError, exceptions.HelpfulError, exceptions.ExtractionError) as e:
            log("{0.__class__}: {0.message}".format(e))

            expirein = e.expire_in if self.config.delete_messages else None
            alsodelete = message if self.config.delete_invoking else None

            await self.safe_send_message(
                message.channel,
                '```\n%s\n```' % e.message,
                expire_in=expirein,
                also_delete=alsodelete
            )

        except exceptions.Signal:
            raise

        except Exception:
            traceback.print_exc()
            if self.config.debug_mode:
                await self.safe_send_message(message.channel, '```\n%s\n```' % traceback.format_exc())

    async def on_reaction_add(self, reaction, user):
        if reaction.me:
            return

        # await self.add_reaction (reaction.message, discord.Emoji (name = "Bubo", id = "234022157569490945", server = reaction.message.server))
        # self.log ("{} ({})".format (reaction.emoji.name, reaction.emoji.id))
        # self.log ("{}".format (reaction.emoji))

    async def on_voice_state_update(self, before, after):
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

        auto_paused = self.server_specific_data[after.server]['auto_paused']
        player = await self.get_player(my_voice_channel)

        if after == after.server.me and after.voice_channel:
            player.voice_client.channel = after.voice_channel

        if not self.config.auto_pause:
            return

        if sum(1 for m in my_voice_channel.voice_members if m != after.server.me):
            if auto_paused and player.is_paused:
                log("[config:autopause] Unpausing")
                self.server_specific_data[after.server]['auto_paused'] = False
                player.resume()
                self.socket_server.threaded_broadcast_information()
        else:
            if not auto_paused and player.is_playing:
                log("[config:autopause] Pausing")
                self.server_specific_data[after.server]['auto_paused'] = True
                player.pause()
                self.socket_server.threaded_broadcast_information()

    async def on_server_update(self, before: discord.Server, after: discord.Server):
        if before.region != after.region:
            self.log("[Servers] \"%s\" changed regions: %s -> %s" %
                     (after.name, before.region, after.region))

            await self.reconnect_voice_client(after)

if __name__ == '__main__':
    bot = MusicBot()
    bot.run()
