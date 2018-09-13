import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, List, Optional, Union

from discord import Embed, Message, NotFound, TextChannel

from giesela import utils
from . import text
from .abstract import Startable, Stoppable

__all__ = ["EditableEmbed", "LoadingBar", "UpdatingMessage", "IntervalUpdatingMessage"]

log = logging.getLogger(__name__)


class EditableEmbed:
    def __init__(self, channel: TextChannel, message: Message = None):
        self.channel = channel

        self._message = message

    @property
    def message(self) -> Optional[Message]:
        return self._message

    async def update_message_state(self):
        if self.message:
            self._message = await self.channel.get_message(self.message.id)

    async def delete(self):
        if self.message:
            await self.message.delete()
            self._message = None

    async def edit(self, embed: Embed, on_new: Callable[[Message], Any] = None):
        if self.message:
            try:
                await self._message.edit(embed=embed)
            except NotFound:
                log.warning(f"message for {self} was deleted")
            else:
                return

        self._message = await self.channel.send(embed=embed)

        if callable(on_new):
            res = on_new(self.message)

            if asyncio.iscoroutine(res):
                await res


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
    _cancelled_messages: int

    def __init__(self, channel: TextChannel, **options):
        self.header = options.pop("header", "Please Wait")
        self.colour = options.pop("colour", 0xf90a7d)
        self.total_items = options.pop("total_items", None)
        self.show_time_left = options.pop("show_time_left", True)
        self.show_ipm = options.pop("show_ipm", True)
        self.item_name_plural = options.pop("item_name_plural", "items")
        self.show_percentage = options.pop("show_percentage", True)

        self.custom_embed_data = options.pop("custom_embed_data", {})
        super().__init__(channel, **options)

        self.progress = 0
        self.times = []

        self._current_time = time.time()
        self._current_embed = None
        self._message_future = None
        self._cancelled_messages = 0

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

        description = text.create_bar(self.progress, length=15)
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

    def set_progress(self, percentage: float):
        self.time_it()

        self.progress = percentage

        next_embed = self.build_next_embed()

        if self._message_future and not self._message_future.done():
            if self._cancelled_messages <= 2:
                self._message_future.cancel()
                self._cancelled_messages += 1
            else:
                log.warning("Can't keep up with progress, not updating until caught up!")
                return
        else:
            self._cancelled_messages = 0

        self._message_future = asyncio.ensure_future(self.edit(next_embed))

    def tick(self):
        if self.total_items:
            progress = self.progress + (1 / self.total_items)
            self.set_progress(progress)


class UpdatingMessage(EditableEmbed):
    def __init__(self, channel: TextChannel, *, callback: Callable[[], Union[Embed, Awaitable[Embed]]] = None, **kwargs):
        self.callback = callback
        super().__init__(channel, **kwargs)

    async def get_embed(self) -> Embed:
        if not self.callback:
            raise ValueError("No Callback given")

        embed = self.callback()
        if asyncio.iscoroutine(embed):
            embed = await embed
        return embed

    async def on_create_message(self, msg: Message):
        pass

    async def trigger_update(self):
        await self.edit(await self.get_embed(), on_new=self.on_create_message)


class IntervalUpdatingMessage(UpdatingMessage, Startable, Stoppable):
    _runner: Optional[asyncio.Task]

    def __init__(self, channel: TextChannel, *, interval: float = 5, **kwargs):
        super().__init__(channel, **kwargs)

        self.interval = interval

        self._runner = None
        self._runner_ready = asyncio.Event()

    async def _run_loop(self):
        _last_updater: Optional[asyncio.Task] = None
        while True:
            try:
                if _last_updater and not _last_updater.done():
                    await _last_updater
                _last_updater = asyncio.ensure_future(self.trigger_update())

                if not self._runner_ready.is_set():
                    await _last_updater
                    self._runner_ready.set()

                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return
            except Exception:
                if self._runner_ready.is_set():
                    log.exception("Error in loop")
                else:
                    self._runner_ready.set()
                    raise

    async def start(self):
        if self._runner:
            raise ValueError("Already running!")
        self._runner_ready.clear()
        self._runner = asyncio.ensure_future(self._run_loop())
        await self._runner_ready.wait()
        # noinspection PyArgumentList
        exc = self._runner.done() and self._runner.exception()
        if exc:
            raise exc

        await super().start()

    async def stop(self):
        if self._runner:
            self._runner.cancel()
        await super().stop()

    async def delete(self):
        await self.stop()
        await super().delete()
