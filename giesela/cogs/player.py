import logging
from functools import partial
from typing import Dict, Optional, Union

from discord import Game, Guild, Member, Message, User, VoiceChannel, VoiceState
from discord.ext import commands
from discord.ext.commands import Context

from giesela import BaseEntry, Downloader, Giesela, MusicPlayer, WebieselaServer, constants, lyrics as lyricsfinder
from giesela.lib.ui import VerticalTextViewer
from giesela.utils import create_bar, parse_timestamp, similarity

log = logging.getLogger(__name__)

LOAD_ORDER = -1
VOICE_CHANNEL_NAMES = ("music", "giesela", "musicbot")


def _seek(player: MusicPlayer, seconds: Union[str, float]):
    if isinstance(seconds, str):
        seconds = parse_timestamp(seconds)

    if seconds is None:
        raise commands.CommandError("Please provide a valid timestamp")

    if player.current_entry is None:
        raise commands.CommandError("Nothing playing!")

    player.seek(seconds)


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

        _similarity = max(*map(partial(similarity, channel.name.lower()), VOICE_CHANNEL_NAMES))
        if _similarity > _max_similarity:
            _max_similarity = _similarity
            _channel = channel

    if _channel:
        return _channel

    return guild.voice_channels[0]


class Player:
    bot: Giesela
    downloader: Downloader

    players: Dict[int, MusicPlayer]
    status_messages: Dict[int, Message]

    def __init__(self, bot: Giesela):
        self.bot = bot

        self.downloader = Downloader(download_folder=constants.AUDIO_CACHE_PATH)

        self.players = {}
        self.status_messages = {}

    async def get_player(self, target: Union[Guild, Context], *,
                         create: bool = True, channel: VoiceChannel = None, member: Union[User, Member] = None) -> Optional[MusicPlayer]:
        if isinstance(target, Context):
            guild = target.guild
            member = member or target.author
        else:
            guild = target

        if guild.id not in self.players:
            if create:
                if not channel:
                    if isinstance(member, Member) and member.voice:
                        channel = member.voice.channel
                    else:
                        channel = await find_giesela_channel(self.bot, guild, user=member)

                player = MusicPlayer(self.bot, self.downloader, channel)
                player.on("play", self.on_player_play) \
                    .on("resume", self.on_player_resume) \
                    .on("pause", self.on_player_pause) \
                    .on("stop", self.on_player_stop) \
                    .on("finished-playing", self.on_player_finished_playing)
                self.players[guild.id] = player
            else:
                return None
        return self.players[guild.id]

    @classmethod
    def auto_pause(cls, player: MusicPlayer, joined: bool = None):
        channel = player.channel
        if not channel:
            return

        # if the first new person joined
        if joined is True and sum(1 for vm in channel.members if not vm.bot) == 1:
            log.info("auto-resuming")
            player.resume()
        elif sum(1 for vm in channel.members if not vm.bot) == 0:
            log.info("auto-pausing")
            player.pause()

    async def on_player_play(self, player: MusicPlayer, entry: BaseEntry):
        self.auto_pause(player)
        WebieselaServer.send_player_information(player.channel.guild.id)
        await self.update_now_playing(entry)

    async def on_player_resume(self, player: MusicPlayer, entry: BaseEntry, **_):
        WebieselaServer.small_update(player.channel.guild.id, state=player.state, progress=player.progress)
        await self.update_now_playing(entry)

    async def on_player_pause(self, player: MusicPlayer, entry: BaseEntry, **_):
        WebieselaServer.small_update(player.channel.guild.id, state=player.state, progress=player.progress)
        await self.update_now_playing(entry, is_paused=True)

    async def on_player_stop(self, **_):
        await self.update_now_playing()

    async def on_player_finished_playing(self, player, **_):
        if not player.queue.entries and not player.current_entry:
            WebieselaServer.send_player_information(player.channel.guild.id)

    async def update_now_playing(self, entry: BaseEntry = None, is_paused: bool = False):
        game = None

        active_players = sum(1 for p in self.players.values() if p.is_playing)

        if active_players > 1:
            game = Game(name="Music")
        elif active_players == 1:
            player = next(player for player in self.players.values() if player.is_playing)
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

        if not self.bot.config.auto_pause:
            return

        if before.channel == after.channel:
            return

        # Ignore other bots
        if member.guild.me != member and member.bot:
            return

        user_joined = False

        if after.channel and not before.channel:
            user_joined = True

        player = await self.get_player(member.guild)

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
        await player.move_to(target)

        if not player.player:
            await player.play()

    @commands.command()
    async def disconnect(self, ctx: Context):
        """Disconnect from the voice channel"""
        player = await self.get_player(ctx.guild, create=False)
        if player:
            await player.disconnect()

    @commands.command()
    async def pause(self, ctx: Context):
        """Pause playback of the current song. If the player is paused, it will unpause."""
        player = await self.get_player(ctx)

        if player.voice_client:
            if player.voice_client.is_playing():
                player.pause()
            else:
                player.resume()
        else:
            raise commands.CommandError("Cannot pause what is not playing")

    @commands.command()
    async def resume(self, ctx: Context):
        """Resumes playback of the current song."""
        player = await self.get_player(ctx)

        if player.voice_client:
            player.resume()
        else:
            raise commands.CommandError("Hard to unpause something that's not paused, amirite?")

    @commands.command()
    async def stop(self, ctx: Context):
        """Stops the player completely and removes all entries from the queue."""
        player = await self.get_player(ctx)
        player.stop()
        player.queue.clear()

    @commands.command()
    async def volume(self, ctx: Context, volume: str = None):
        """Change volume.

        Sets the playback volume. Accepted values are from 1 to 100.
        Putting + or - before the volume will make the volume change relative to the current volume.
        """
        player = await self.get_player(ctx)

        if not volume:
            await ctx.send("Current volume: {}%\n{}".format(int(player.volume * 100), create_bar(player.volume, 20)))
            return

        relative = False
        if volume[0] in "+-":
            relative = True
        elif volume in ("mute", "muted", "silent"):
            volume = 0
        elif volume in ("loud", "full"):
            volume = 100

        try:
            volume = int(volume)

        except ValueError:
            raise commands.CommandError(f"{volume} is not a valid number")

        if relative:
            vol_change = volume
            volume += (player.volume * 100)
        else:
            vol_change = volume - player.volume

        old_volume = int(player.volume * 100)

        if 0 <= volume <= 100:
            player.volume = volume / 100

            await ctx.send(f"updated volume from {old_volume} to {volume}")
            return
        else:
            if relative:
                raise commands.CommandError(f"Unreasonable volume change provided: "
                                            f"{old_volume}{vol_change:+} -> {old_volume + vol_change}%. "
                                            f"Provide a change between {1-old_volume} and {100 - old_volume:+}.")
            else:
                raise commands.CommandError(f"Unreasonable volume provided: {volume}%. Provide a value between 1 and 100.")

    @commands.command()
    async def seek(self, ctx: Context, timestamp: str):
        """Seek to the given timestamp formatted (minutes:seconds)"""
        player = await self.get_player(ctx)
        _seek(player, timestamp)

    @commands.command()
    async def fwd(self, ctx: Context, timestamp: str):
        """Forward <timestamp> into the current entry"""
        player = await self.get_player(ctx)

        secs = parse_timestamp(timestamp)
        if secs:
            secs += player.progress

        _seek(player, secs)

    @commands.command()
    async def rwd(self, ctx: Context, timestamp: str = None):
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

        _seek(player, secs)

    @commands.group(invoke_without_command=True)
    async def lyrics(self, ctx: Context, *query: str):
        """Try to find lyrics for the current entry and display 'em"""
        player = await self.get_player(ctx)

        async with ctx.typing():
            if query:
                query = " ".join(query)
                lyrics = lyricsfinder.search_for_lyrics(query)
            else:
                if not player.current_entry:
                    raise commands.CommandError("There's no way for me to find lyrics for something that doesn't even exist!")
                query = player.current_entry.title
                lyrics = player.current_entry.lyrics

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
        await viewer.display()
        await ctx.message.delete()


def setup(bot: Giesela):
    bot.add_cog(Player(bot))
