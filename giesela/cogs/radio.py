import random
from contextlib import suppress
from typing import Optional

from discord import Embed, Forbidden
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, GieselaPlayer, RadioStation, RadioStationManager
from giesela.ui import ItemPicker
from .player import Player

LOAD_ORDER = 1


def get_station_embed(station: RadioStation) -> Embed:
    em = Embed(title=station.name, url=station.website or Embed.Empty)
    em.set_thumbnail(url=station.logo)
    return em


async def play_station(ctx: Context, player: GieselaPlayer, station: RadioStation):
    async with ctx.typing():
        entry = await player.extractor.get_radio_entry(station)
    player.queue.add_entry(entry, ctx.author)
    embed = get_station_embed(station)
    await ctx.send(f"Added **{entry}** to the queue!", embed=embed)


class Radio:
    bot: Giesela
    station_manager: RadioStationManager

    get_player: Player.get_player

    def __init__(self, bot: Giesela):
        self.bot = bot
        self.station_manager = RadioStationManager.load(bot, bot.config.app.files.radio_stations)
        self.bot.store_reference("radio_station_manager", self.station_manager)

        self.get_player = self.bot.get_player

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

        item_picker = ItemPicker(ctx.channel, bot=self.bot, user=ctx.author, embed_callback=get_station)
        result = await item_picker.choose()

        if result is not None:
            return stations[result % len(stations)]

    @commands.guild_only()
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
                with suppress(Forbidden):
                    await ctx.message.delete()
                return

        await play_station(ctx, player, station)

    @commands.guild_only()
    @radio.command("random")
    async def radio_random(self, ctx: Context):
        """Play a random radio station."""
        player = await self.get_player(ctx)
        station = random.choice(self.station_manager.stations)
        await play_station(ctx, player, station)


def setup(bot: Giesela):
    bot.add_cog(Radio(bot))
