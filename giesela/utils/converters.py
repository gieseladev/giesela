from discord.ext.commands import BadArgument, Context, Converter

from . import url_utils

__all__ = ["Url", "ImageUrl"]


class Url(Converter, str):
    async def convert(self, ctx: Context, argument: str) -> str:
        return argument.strip("<>")


class ImageUrl(Url):
    async def convert(self, ctx: Context, argument: str) -> str:
        url = await super().convert(ctx, argument)
        if await url_utils.url_is_image(ctx.bot.aiosession, url):
            return url
        raise BadArgument(f"\"{url}\" doesn't look like an image!")
