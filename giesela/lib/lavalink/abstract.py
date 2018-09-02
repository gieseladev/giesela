import asyncio

from discord import Client


class AbstractLavalinkClient:
    bot: Client
    loop: asyncio.AbstractEventLoop

    _password: str

    def __init__(self, *, bot: Client, password: str, **kwargs):
        self.bot = bot
        self.loop = bot.loop
        self._password = password

        super().__init__(**kwargs)
