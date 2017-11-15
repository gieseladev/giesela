from ..extension import Extension, command


class Player(Extension):
    async def init(self):
        pass

    @command("volume")
    async def volume(self, connection, value):
        pass
