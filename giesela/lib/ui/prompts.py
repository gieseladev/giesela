from typing import Awaitable

from discord import Colour, Embed, TextChannel

from .interactive import InteractableEmbed, emoji_handler


class EmbedPrompt(InteractableEmbed):
    embed: Embed

    def __init__(self, channel: TextChannel, **kwargs):
        prompt = kwargs.pop("embed", False) or kwargs.pop("text", "Are you sure?")
        if isinstance(prompt, str):
            prompt = Embed(text=prompt, colour=Colour.orange())
        self.embed = prompt

        super().__init__(channel, **kwargs)

    def __await__(self) -> Awaitable[bool]:
        return self.prompt()

    async def prompt(self) -> bool:
        await self.edit(self.embed, on_new=self.add_reactions)
        res = await self.wait_for_listener("reactions")
        await self.delete()
        return res


class PromptYesNo(EmbedPrompt):

    @emoji_handler("☑", pos=1)
    async def handle_true(self, **_):
        self.stop_listener()
        return True

    @emoji_handler("❎", pos=2)
    async def handle_false(self, **_):
        self.stop_listener()
        return False
