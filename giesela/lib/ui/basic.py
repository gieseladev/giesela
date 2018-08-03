import asyncio
import time

from discord import Embed

from giesela import utils
from . import ui_utils


class EditableEmbed:
    """
        Provides the base for an interface
    """

    def __init__(self):
        self._interface_message = None

    async def exit(self):
        if self._interface_message:
            await self.bot.safe_delete_message(self._interface_message)

    async def update_message(self, embed, on_new=None):
        if not self._interface_message:
            self._interface_message = await self.bot.safe_send_message(self.channel, embed=embed)

            if callable(on_new):
                res = on_new(self._interface_message)

                if asyncio.iscoroutine(res):
                    await res
        else:
            self._interface_message = await self.bot.safe_edit_message(self._interface_message, embed=embed)


class LoadingBar(EditableEmbed):
    """
        Keyword arguments:
        header -- Embed's title
        colour -- custom colour for the Embed
        total_items -- display the amount of items to parse
        show_time_left -- whether to display "time_left" (requires total_items to be set)
        show_ipm -- whether to the amount of items per minute
        item_name_plural -- item name put into plural form
        show_percentage -- whether to show the current percentage

        custom_embed_data -- data to pass over to the Embed
    """

    def __init__(self, bot, channel, **options):
        self.bot = bot
        self.channel = channel

        super().__init__()

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
    def avg_time(self):
        return (sum(self.times) / len(self.times)) if self.times else None

    def time_it(self):
        this_time = time.time() - self._current_time
        self.times.append(this_time)

        self._current_time = time.time()

    def build_next_embed(self):
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

    async def set_progress(self, percentage):
        self.time_it()

        self.progress = percentage

        next_embed = self.build_next_embed()

        if self._message_future:
            await self._message_future

        self._message_future = asyncio.ensure_future(self.update_message(next_embed))

    async def done(self):
        await self.exit()


class ItemPicker(EditableEmbed):
    """
        Keyword arguments:
        user -- user to respond to
        items -- list of Embeds to use
        item_callback -- function to call which returns an Embed
    """

    emojis = ("◀", "▶", "✅", "❎")
    abort = "❎"
    select = "✅"

    _prev = "◀"
    _next = "▶"

    def __init__(self, bot, channel, user=None, **kwargs):
        super().__init__()

        self.bot = bot
        self.channel = channel
        self.user = user

        self.items = kwargs.get("items")
        self.item_callback = kwargs.get("item_callback")

        self._current_index = 0

    @property
    async def next_item(self):
        if self.items:
            return self.items[self._current_index % len(self.items)]
        elif self.item_callback:
            res = self.item_callback(self._current_index)

            if asyncio.iscoroutine(res):
                res = await res

            return res

    async def add_reactions(self, msg):
        for emoji in ItemPicker.emojis:
            await self.bot.add_reaction(msg, emoji)

    async def result(self):
        while True:
            next_embed = await self.next_item
            await self.update_message(next_embed, on_new=self.add_reactions)

            reaction, user = await ui_utils.wait_for_reaction_change(emoji=ItemPicker.emojis, user=self.user, message=self._interface_message)

            emoji = reaction.emoji

            if emoji == ItemPicker.abort:
                await self.exit()
                return None

            elif emoji == ItemPicker.select:
                await self.exit()
                return self._current_index

            elif emoji == ItemPicker._prev:
                self._current_index -= 1
            elif emoji == ItemPicker._next:
                self._current_index += 1


class EmbedViewer(EditableEmbed):
    """
        Keyword arguments:
        user -- user to respond to
        embeds -- list of Embeds to use
        embed_callback -- function to call which returns an Embed based on the current index
    """

    emojis = ("◀", "▶", "❎")
    abort = "❎"

    _prev = "◀"
    _next = "▶"

    def __init__(self, bot, channel, user=None, **kwargs):
        super().__init__()

        self.bot = bot
        self.channel = channel
        self.user = user

        self.embeds = kwargs.get("embeds")
        self.embed_callback = kwargs.get("embed_callback")

        self._current_index = 0

    @property
    async def next_embed(self):
        if self.embeds:
            return self.embeds[self._current_index % len(self.embeds)]
        elif self.embed_callback:
            res = self.embed_callback(self._current_index)

            if asyncio.iscoroutine(res):
                res = await res

            return res

    async def add_reactions(self, msg):
        for emoji in EmbedViewer.emojis:
            await self.bot.add_reaction(msg, emoji)

    async def display(self):
        while True:
            next_embed = await self.next_embed
            await self.update_message(next_embed, on_new=self.add_reactions)

            reaction, user = await ui_utils.wait_for_reaction_change(emoji=EmbedViewer.emojis, user=self.user, message=self._interface_message)

            emoji = reaction.emoji

            if emoji == EmbedViewer.abort:
                await self.exit()
                return None

            elif emoji == EmbedViewer._prev:
                self._current_index -= 1
            elif emoji == EmbedViewer._next:
                self._current_index += 1


class VerticalEmbedViewer(EmbedViewer):
    emojis = ("🔼", "🔽", "❎")
    abort = "❎"

    _prev = "🔼"
    _next = "🔽"
