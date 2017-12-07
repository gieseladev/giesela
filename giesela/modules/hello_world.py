"""Testing stuff."""

from giesela.lib import GieselaModule, command


class HelloWorld(GieselaModule):
    @command(r"^hello\b")
    async def hello(self, channel):
        await self.bot.send_message(channel, "hey")
