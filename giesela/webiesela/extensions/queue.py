"""Extension module for queue operations."""

from ..extension import Extension, command, request
from ..models.exceptions import ParamError


class Queue(Extension):
    """Queue extension."""

    async def get_player(self, server):
        """Return the player for a server."""
        return await self.bot.get_player(server)

    @command()
    async def shuffle(self, message, server):
        """Shuffle the queue."""
        queue = (await self.get_player(server)).queue

        queue.shuffle()
        await message.answer(success=True)

    @command()
    async def clear(self, message, server):
        """Clear the queue."""
        queue = (await self.get_player(server)).queue

        queue.clear()
        await message.answer(success=True)

    @command()
    async def move(self, message, server, from_index, to_index):
        """Move an entry in the queue."""
        assert (isinstance(from_index, int)), ParamError("must be valid number (int)", "from_index")
        assert (isinstance(to_index, int)), ParamError("must be valid number (int)", "to_index")

        queue = (await self.get_player(server)).queue

        success = queue.move(from_index, to_index)
        await message.answer(success=success)

    @command()
    async def replay(self, message, server, index):
        """Move an entry in the queue."""
        assert (isinstance(index, int)), ParamError("must be valid number (int)", "index")

        queue = (await self.get_player(server)).queue

        success = queue.replay(index)
        await message.answer(success=success)

    @command()
    async def play_entry(self, message, server):
        """Play an entry."""
        queue = (await self.get_player(server)).queue

    @request()
    async def get_queue(self, message, server):
        """Get the current queue."""
        player = await self.get_player(server)

        await message.answer(player.queue.to_web_dict())
