import asyncio


class ItemPicker:
    emojis = ("◀", "▶", "✅", "❎")
    abort = "❎"
    select = "✅"

    _prev = "◀"
    _next = "▶"

    def __init__(self, bot, channel, user=None, **kwargs):
        self.bot = bot
        self.channel = channel
        self.user = user

        self.items = kwargs.get("items")
        self.item_callback = kwargs.get("item_callback")

        self._current_index = 0
        self._interface_message = None

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

    async def update_message(self, embed):
        if not self._interface_message:
            self._interface_message = await self.bot.safe_send_message(self.channel, embed=embed)
            await self.add_reactions(self._interface_message)
        else:
            self._interface_message = await self.bot.safe_edit_message(self._interface_message, embed=embed)

    async def exit(self):
        if self._interface_message:
            await self.bot.safe_delete_message(self._interface_message)

    async def result(self):
        while True:
            next_embed = await self.next_item
            await self.update_message(next_embed)

            reaction, user = await self.bot.wait_for_reaction(emoji=ItemPicker.emojis, user=self.user, message=self._interface_message)

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
