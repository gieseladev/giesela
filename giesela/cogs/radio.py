import random
from typing import Optional

from discord import Embed
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, MusicPlayer, RadioStation, RadioStationManager
from giesela.ui import ItemPicker
from .player import Player

LOAD_ORDER = 1


def get_station_embed(station: RadioStation) -> Embed:
    em = Embed(title=station.name, url=station.website or Embed.Empty)
    em.set_thumbnail(url=station.logo)
    return em


async def play_station(ctx: Context, player: MusicPlayer, station: RadioStation, *, now: bool = True):
    await player.queue.add_radio_entry(station, author=ctx.author, now=now)
    embed = get_station_embed(station)
    await ctx.send("Now playing", embed=embed)


class Radio:
    bot: Giesela
    player_cog: Player
    station_manager: RadioStationManager

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.player_cog = bot.cogs["Player"]
        self.station_manager = RadioStationManager.load(bot, bot.config.radio_stations_config)

    async def get_player(self, *args, **kwargs):
        return await self.player_cog.get_player(*args, **kwargs)

    def find_station(self, station: str) -> RadioStation:
        _station = self.station_manager.find_station(station)
        if not _station:
            raise commands.CommandError(f"Couldn't find a radio station called \"{station}\"")
        return _station

    async def pick_station(self, ctx: Context) -> Optional[RadioStation]:
        stations = self.station_manager.stations.copy()
        random.shuffle(stations)

        async def get_station(index: int) -> Embed:
            _station = stations[index % len(stations)]

            em = get_station_embed(_station)

            if _station.has_song_data:
                song_data = await _station.get_song_data()
                em.add_field(name="Currently playing", value=str(song_data))
                em.set_footer(text=song_data.album or "Unknown Album", icon_url=song_data.cover or Embed.Empty)
            return em

        item_picker = ItemPicker(ctx.channel, ctx.author, embed_callback=get_station)
        result = await item_picker.choose()

        if result:
            return stations[result % len(stations)]

    @commands.group(invoke_without_command=True)
    async def radio(self, ctx: Context, station: str = None):
        """Play a radio station.

        You can leave the parameters blank in order to get a tour around all the channels,
        you can specify the station you want to listen to or you can let the bot choose for you by entering \"random\"
        """
        player = await self.get_player(ctx)

        if station:
            station = self.find_station(station)
        else:
            station = await self.pick_station(ctx)
            if not station:
                await ctx.message.delete()
                return

        await play_station(ctx, player, station)

    @radio.command("random")
    async def radio_random(self, ctx: Context):
        """Play a random radio station."""
        player = await self.get_player(ctx)
        station = random.choice(self.station_manager.stations)
        await play_station(ctx, player, station)


def setup(bot: Giesela):
    bot.add_cog(Radio(bot))
