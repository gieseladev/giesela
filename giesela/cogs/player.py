import asyncio
import logging
import operator
from typing import Dict, Optional, Union

from discord import Game, Guild, Member, User, VoiceChannel, VoiceState
from discord.ext import commands
from discord.ext.commands import Context

from giesela import BaseEntry, Giesela, GieselaPlayer, PlayerManager, WebieselaServer, lyrics as lyricsfinder
from giesela.ui import VerticalTextViewer
from giesela.ui.custom import EntryEditor
from giesela.utils import create_bar, parse_timestamp, similarity

log = logging.getLogger(__name__)

LOAD_ORDER = -1


async def _seek(player: GieselaPlayer, seconds: Union[str, float]):
    if isinstance(seconds, str):
        seconds = parse_timestamp(seconds)

    if seconds is None:
        raise commands.CommandError("Please provide a valid timestamp")

    if player.current_entry is None:
        raise commands.CommandError("Nothing playing!")

    await player.seek(seconds)


VOICE_CHANNEL_NAMES = ("music", "giesela", "musicbot")


async def find_giesela_channel(bot: Giesela, guild: Guild, user: User = None) -> VoiceChannel:
    if not guild.voice_channels:
        raise EnvironmentError("HOW EVEN?!? There are no voice channels... WHAT")
    if bot.config.voice_channel_home:
        return await bot.get_channel(bot.config.voice_channel_home)

    _max_similarity = 0
    _channel = None
    for channel in guild.voice_channels:
        if user and user in channel.members:
            return channel

        _similarity = max(similarity(channel.name.lower(), name) for name in VOICE_CHANNEL_NAMES)
        if _similarity > _max_similarity:
            _max_similarity = _similarity
            _channel = channel

    if _channel:
        return _channel

    return guild.voice_channels[0]


async def _delayed_disconnect(player: GieselaPlayer, delay: int):
    await asyncio.sleep(delay)
    if player.is_connected:
        await player.disconnect()


class Player:
    _disconnects: Dict[int, asyncio.Task]

    def __init__(self, bot: Giesela):
        self.bot = bot
        config = bot.config
        self.player_manager = PlayerManager(bot, config.lavalink_password, config.lavalink_rest_url, config.lavalink_ws_url)

        self._disconnects = {}

    async def get_player(self, target: Union[Guild, Context, int], *,
                         create: bool = True, channel: VoiceChannel = None, member: Union[User, Member] = None) -> Optional[GieselaPlayer]:
        if isinstance(target, Context):
            guild_id = target.guild.id
            member = member or target.author
        elif isinstance(target, int):
            guild_id = target
        elif isinstance(target, Guild):
            guild_id = target.id
        else:
            raise TypeError(f"Unknown target: {target}")

        player = self.player_manager.players.get(guild_id)
        if not player:
            if not create:
                return None

            if not channel:
                if isinstance(member, Member) and member.voice:
                    channel = member.voice.channel
                else:
                    guild = self.bot.get_guild(guild_id)
                    channel = await find_giesela_channel(self.bot, guild, user=member)

            player = self.player_manager.get_player(guild_id, channel.id)
        return player

    def start_disconnect(self, player: GieselaPlayer):
        guild_id = player.channel.guild.id
        task = self._disconnects.get(guild_id)
        if task and not task.done():
            return

        delay = self.bot.config.vc_disconnect_delay
        if delay is not None:
            log.debug(f"auto disconnect {player} in {delay} seconds")
            self._disconnects[guild_id] = asyncio.ensure_future(_delayed_disconnect(player, delay))

    def stop_disconnect(self, player: GieselaPlayer):
        guild_id = player.channel.guild.id
        task = self._disconnects.pop(guild_id, None)
        if task:
            log.debug(f"cancelled disconnect for {player}")
            task.cancel()

    def auto_pause(self, player: GieselaPlayer, joined: bool = False):
        channel = player.voice_channel
        if not channel:
            return

        non_bot_vm = sum(1 for vm in channel.members if not vm.bot)

        # if the first new person joined
        if joined is True and non_bot_vm == 1:
            self.stop_disconnect(player)
            if self.bot.config.auto_pause:
                log.info(f"auto-resuming {player}")
                player.resume()

        elif non_bot_vm == 0:
            self.start_disconnect(player)
            if self.bot.config.auto_pause:
                log.info(f"auto-pausing {player}")
                player.pause()

    async def on_player_play(self, player: GieselaPlayer, entry: BaseEntry):
        self.auto_pause(player)
        WebieselaServer.send_player_information(player.channel.guild.id)
        await self.update_now_playing(entry)

    async def on_player_resume(self, player: GieselaPlayer):
        WebieselaServer.small_update(player.channel.guild.id, state=player.state, progress=player.progress)
        await self.update_now_playing(player.current_entry)

    async def on_player_pause(self, player: GieselaPlayer):
        WebieselaServer.small_update(player.channel.guild.id, state=player.state, progress=player.progress)
        await self.update_now_playing(player.current_entry, is_paused=True)

    async def on_player_stop(self, **_):
        await self.update_now_playing()

    @classmethod
    async def on_player_volume_change(cls, player: GieselaPlayer, new_volume: float):
        WebieselaServer.small_update(player.guild.id, volume=new_volume)

    @classmethod
    async def on_player_finished_playing(cls, player: GieselaPlayer, **_):
        if not player.queue.entries and not player.current_entry:
            WebieselaServer.send_player_information(player.channel.guild.id)

    async def update_now_playing(self, entry: BaseEntry = None, is_paused: bool = False):
        game = None

        active_players = sum(1 for p in self.player_manager.players.values() if p.is_playing)

        if active_players > 1:
            game = Game(name="Music")
        elif active_players == 1:
            player = self.player_manager.find_player(operator.attrgetter("is_playing"))
            entry = player.current_entry
        else:
            game = Game(name=self.bot.config.idle_game)

        if entry:
            prefix = "❚❚ " if is_paused else ""

            name = entry.title

            name = f"{prefix}{name}"[:128]
            game = Game(name=name)

        await self.bot.change_presence(activity=game)

    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        giesela_voice = member.guild.me.voice
        if not giesela_voice:
            return

        if before.channel == after.channel:
            return

        # Ignore other bots
        if member.guild.me != member and member.bot:
            return

        player = await self.get_player(member.guild)

        user_joined = after.channel != before.channel
        self.auto_pause(player, joined=user_joined)

    @commands.command()
    async def summon(self, ctx: Context):
        """Call the bot to the summoner's voice channel."""
        target = ctx.author.voice
        if target:
            target = target.channel
        else:
            raise commands.CommandError("Couldn't find voice channel")

        player = await self.get_player(ctx.guild, channel=target)
        await player.connect(target)

        if not player.is_playing:
            await player.play()

    @commands.command()
    async def disconnect(self, ctx: Context):
        """Disconnect from the voice channel"""
        player = await self.get_player(ctx.guild, create=False)
        if player:
            await player.disconnect()

    @commands.command()
    async def pause(self, ctx: Context):
        """Pause playback of the current song

        If the player is paused, it will resume.
        """
        player = await self.get_player(ctx)

        if player.is_playing:
            await player.pause()
        elif player.is_paused:
            await player.resume()
        else:
            raise commands.CommandError("Cannot pause what is not playing")

    @commands.command()
    async def resume(self, ctx: Context):
        """Resumes playback of the current song."""
        player = await self.get_player(ctx)

        if player.is_paused:
            await player.resume()
        else:
            raise commands.CommandError("Hard to unpause something that's not paused, amirite?")

    @commands.command()
    async def stop(self, ctx: Context):
        """Stops the player completely and removes all entries from the queue."""
        player = await self.get_player(ctx)
        await player.stop()
        player.queue.clear()

    @commands.command()
    async def volume(self, ctx: Context, volume: str = None):
        """Change volume.

        Sets the playback volume. Accepted values are from 1 to 100.
        Putting + or - before the volume will make the volume change relative to the current volume.
        """
        player = await self.get_player(ctx)

        old_volume = round(player.volume * 100)

        if not volume:
            bar = create_bar(player.volume, 20)
            await ctx.send(f"Current volume: {old_volume}%\n{bar}")
            return

        relative = False
        if volume.startswith(("+", "-")):
            relative = True
            volume = volume[1:]

        try:
            volume = int(volume)
        except ValueError:
            raise commands.CommandError(f"{volume} is not a valid number")

        if relative:
            vol_change = volume
            volume += round(player.volume * 100)
        else:
            vol_change = volume - player.volume

        if not 0 <= volume <= 100:
            if relative:
                raise commands.CommandError(f"Unreasonable volume change provided: "
                                            f"{old_volume}{vol_change:+} -> {old_volume + vol_change}%. "
                                            f"Provide a change between {-old_volume} and {100 - old_volume}.")
            else:
                raise commands.CommandError(f"Unreasonable volume provided: {volume}%. Provide a value between 0 and 100.")

        player.volume = volume / 100

        await ctx.send(f"updated volume from {old_volume} to {volume}")

    @commands.command()
    async def seek(self, ctx: Context, timestamp: str):
        """Seek to the given timestamp formatted (minutes:seconds)"""
        player = await self.get_player(ctx)
        await _seek(player, timestamp)

    @commands.command(aliases=["fwd", "fw"])
    async def forward(self, ctx: Context, timestamp: str):
        """Forward <timestamp> into the current entry"""
        player = await self.get_player(ctx)

        secs = parse_timestamp(timestamp)
        if secs:
            secs += player.progress

        await _seek(player, secs)

    @commands.command(aliases=["rwd", "rw"])
    async def rewind(self, ctx: Context, timestamp: str = None):
        """Rewind <timestamp> into the current entry.

        If the current entry is a timestamp-entry, rewind to the previous song
        """
        player = await self.get_player(ctx)
        secs = parse_timestamp(timestamp)
        if secs:
            secs = player.progress - secs

        if not secs:
            if not player.queue.history:
                raise commands.CommandError("Please provide a valid timestamp (no history to rewind into)")
            else:
                player.replay()
                return

        await _seek(player, secs)

    @commands.command("editentry", aliases=["editnp"])
    async def edit_entry(self, ctx: Context):
        """Edit the current entry"""
        player = await self.get_player(ctx)
        if not player.current_entry:
            raise commands.CommandError("There's nothing playing right now")
        editor = EntryEditor(ctx.channel, ctx.author, bot=self.bot, entry=player.current_entry)
        new_entry = await editor.display()

        if not new_entry:
            await ctx.message.delete()
            return

        if player.current_entry is editor.original_entry:
            player.modify_current_entry(new_entry)
            await ctx.send(f"Saved changes to **{new_entry.title}**")

        playlist_entry = player.current_entry.meta.get("playlist_entry")
        if playlist_entry:
            playlist_entry.replace(new_entry)

    @commands.command()
    async def lyrics(self, ctx: Context, *query: str):
        """Try to find lyrics for the current entry and display 'em"""
        player = await self.get_player(ctx)

        _progress_guess = None

        async with ctx.typing():
            if query:
                query = " ".join(query)
                lyrics = lyricsfinder.search_for_lyrics(query)
            else:
                if not player.current_entry:
                    raise commands.CommandError("There's no way for me to find lyrics for something that doesn't even exist!")
                query = player.current_entry.lyrics_search_query
                lyrics = player.current_entry.lyrics
                _progress_guess = player.progress / player.current_entry.duration

        if not lyrics:
            raise commands.CommandError("Couldn't find any lyrics for **{}**".format(query))

        frame = {
            "title": lyrics.title,
            "url": lyrics.origin.url,
            "author": {
                "name": "{progress_bar}"
            },
            "footer": {
                "text": f"Lyrics from {lyrics.origin.source_name}"
            }
        }
        viewer = VerticalTextViewer(ctx.channel, ctx.author, embed_frame=frame, content=lyrics.lyrics)
        if _progress_guess:
            line = round(_progress_guess * viewer.total_lines)
            viewer.set_focus_line(line)
        await viewer.display()
        await ctx.message.delete()


def setup(bot: Giesela):
    bot.add_cog(Player(bot))
