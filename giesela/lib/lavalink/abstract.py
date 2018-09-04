import asyncio
from typing import Union

from discord.ext.commands import AutoShardedBot, Bot

BotType = Union[Bot, AutoShardedBot]


class AbstractLavalinkClient:
    loop: asyncio.AbstractEventLoop

    def __init__(self, *, bot: BotType, password: str, lavalink_address: str, lavalink_secure: bool, **kwargs):
        self.bot = bot
        self.loop = bot.loop
        self._password = password

        lavalink_address = lavalink_address.rstrip("/")
        ws_scheme = "wss" if lavalink_secure else "ws"
        http_scheme = "https" if lavalink_secure else "http"
        self._ws_url = f"{ws_scheme}://{lavalink_address}"
        self._rest_url = f"{http_scheme}://{lavalink_address}"

        super().__init__(**kwargs)
