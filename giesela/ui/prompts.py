from typing import Optional, Union

from discord import Client, Colour, Embed, Message, TextChannel, User

from .interactive import InteractableEmbed, emoji_handler


class EmbedPrompt(InteractableEmbed):
    embed: Embed

    def __init__(self, channel: TextChannel, *,
                 bot: Client,
                 user: Optional[User],
                 message: Message = None,
                 embed: Union[Embed, str] = None,
                 text: str = None,
                 **kwargs) -> None:
        embed = embed or text or "Are you sure?"
        if isinstance(embed, str):
            embed = Embed(title=embed, colour=Colour.orange())
        self.embed = embed

        super().__init__(channel, bot=bot, user=user, message=message, **kwargs)

    def __await__(self):
        return self.prompt().__await__()

    async def prompt(self) -> bool:
        await self.edit(self.embed)
        res = await self.wait_for_listener()
        await self.delete()
        return res


class PromptYesNo(EmbedPrompt):

    @emoji_handler("☑", pos=1)
    async def handle_true(self, *_):
        self.stop_listener()
        return True

    @emoji_handler("❎", pos=2)
    async def handle_false(self, *_):
        self.stop_listener()
        return False
