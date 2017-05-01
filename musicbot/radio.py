import json
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup

import asyncio

from .utils import parse_timestamp


class Radio:

    def has_station_data(radio_station):
        radio_station = "_".join(radio_station.lower().split())
        return radio_station in ["energy_bern", "capital_fm"]

    async def get_current_song(loop, radio_station):
        radio_station = "_".join(radio_station.lower().split())
        if radio_station == "energy_bern":
            return await Radio._get_current_song_energy_bern(loop)
        elif radio_station == "capital_fm":
            return await Radio._get_current_song_capital_fm(loop)

        return None

    async def _get_current_song_energy_bern(loop):
        try:
            async with aiohttp.ClientSession(loop=loop) as client:
                async with client.get('http://www.energyzueri.com/legacy-feed-converter/files/json/timeline/timeline_energybern_0.json') as resp:
                    queue = json.loads(await resp.text())
                    entry = queue[0]
                    start_time = datetime.fromtimestamp(
                        int(entry["timestamp"]))
                    progress = datetime.now() - start_time
                    duration = parse_timestamp(entry["duration"])

                    return {"title": entry["title"].strip(), "artist": entry["artist"].strip(), "cover": entry["cover"], "youtube": entry["youtube"], "duration": duration, "progress": progress}
        except:
            raise
            return None

    async def _get_current_song_capital_fm(loop):
        try:
            async with aiohttp.ClientSession(loop=loop) as client:
                async with client.get('http://www.capitalfm.com/dynamic/now-playing-card/digital/') as resp:
                    soup = BeautifulSoup(await resp.text())
                    title = " ".join(soup.find_all("div", attrs={"itemprop": "name", "class": "track"})[
                        0].text.strip().split())
                    artist = " ".join(soup.find_all("div", attrs={"itemprop": "byArtist", "class": "artist"})[
                        0].text.strip().split())
                    cover = soup.find_all("img", itemprop="image")[
                        0]["data-src"]

                    return {"title": title, "artist": artist, "cover": cover, "youtube": "http://www.capitalfm.com", "duration": 0, "progress": 0}
        except:
            raise
            return None


# loop = asyncio.get_event_loop()
# loop.run_until_complete(Radio.get_current_song(loop, "capital_fm"))
