import json

import aiohttp
from bs4 import BeautifulSoup

import asyncio


class Radio:

    def has_station_data(radio_station):
        radio_station = "_".join(radio_station.lower().split())
        return radio_station in ["energy_bern"]

    async def get_current_song(loop, radio_station):
        radio_station = "_".join(radio_station.lower().split())
        if radio_station == "energy_bern":
            return await Radio._get_current_song_energy_bern(loop)

        return None

    async def _get_current_song_energy_bern(loop):
        try:
            async with aiohttp.ClientSession(loop=loop) as client:
                async with client.get('http://www.energyzueri.com/legacy-feed-converter/files/json/timeline/timeline_energybern_0.json') as resp:
                    queue = json.loads(await resp.text())
                    return queue[0]
        except:
            raise
            return None


# loop = asyncio.get_event_loop()
# loop.run_until_complete(Radio.get_current_song(loop, "energy_bern"))
