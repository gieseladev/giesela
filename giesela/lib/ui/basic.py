import asyncio
import time
from typing import Any, Callable, List, Optional

from discord import Embed, Message, TextChannel

from giesela import utils


class EditableEmbed:
    """
    Args:
        channel: Channel to send the message in
        message: Optional message to use
    """
    channel: TextChannel
    _message: Optional[Message]

    def __init__(self, channel: TextChannel, message: Message = None):
        self.channel = channel

        self._message = message

    @property
    def message(self) -> Optional[Message]:
        return self._message

    async def delete(self):
        if self.message:
            await self.message.delete()

    async def edit(self, embed: Embed, on_new: Callable[[Message], Any] = None):
        if not self.message:
            self._message = await self.channel.send(embed=embed)

            if callable(on_new):
                res = on_new(self.message)

                if asyncio.iscoroutine(res):
                    await res
        else:
            await self._message.edit(embed=embed)


class LoadingBar(EditableEmbed):
    """
        Keyword Args:
            header: Embed's title
            colour: custom colour for the Embed
            total_items: display the amount of items to parse
            show_time_left: whether to display "time_left" (requires total_items to be set)
            show_ipm: whether to the amount of items per minute
            item_name_plural: item name put into plural form
            show_percentage: whether to show the current percentage

            custom_embed_data: data to pass over to the Embed
    """
    header: str
    colour: int
    total_items: Optional[int]
    show_time_left: bool
    show_ipm: bool
    item_name_plural: str
    show_percentage: bool
    custom_embed_data: dict

    progress: int
    times: List[float]

    _current_time: int
    _current_embed: Embed
    _message_future: asyncio.Future

    def __init__(self, channel: TextChannel, **options):
        super().__init__(channel)

        self.header = options.get("header", "Please Wait")
        self.colour = options.get("colour", 0xf90a7d)
        self.total_items = options.get("total_items", None)
        self.show_time_left = options.get("show_time_left", True)
        self.show_ipm = options.get("show_ipm", True)
        self.item_name_plural = options.get("item_name_plural", "items")
        self.show_percentage = options.get("show_percentage", True)

        self.custom_embed_data = options.get("custom_embed_data", {})

        self.progress = 0
        self.times = []

        self._current_time = time.time()
        self._current_embed = None
        self._message_future = None

    @property
    def avg_time(self) -> Optional[float]:
        return (sum(self.times) / len(self.times)) if self.times else None

    def time_it(self):
        this_time = time.time() - self._current_time
        self.times.append(this_time)

        self._current_time = time.time()

    def build_next_embed(self) -> Embed:
        if not self._current_embed:
            self._current_embed = Embed(title=self.header, colour=self.colour, **self.custom_embed_data)

        description = utils.create_bar(self.progress, length=15)
        footer = ""

        if self.show_percentage:
            description += " `{}%`".format(round(100 * self.progress))

        if self.total_items:
            items_done = round(self.progress * self.total_items)
            footer += " {}/{}".format(items_done, self.total_items)

            if self.show_time_left and self.avg_time:
                time_left = (sum(self.times) / self.progress) if self.progress else 0
                description += "\n{} left".format(utils.format_time(time_left, max_specifications=2, combine_with_and=True))

        if self.show_ipm and self.avg_time:
            footer += " at {} {} per minute".format(round(60 / self.avg_time, 1), self.item_name_plural)

        self._current_embed.description = description.strip()
        self._current_embed.set_footer(text=footer.strip())

        return self._current_embed

    async def set_progress(self, percentage: float):
        self.time_it()

        self.progress = percentage

        next_embed = self.build_next_embed()

        if self._message_future:
            await self._message_future

        self._message_future = asyncio.ensure_future(self.edit(next_embed))

    async def done(self):
        await self.delete()
