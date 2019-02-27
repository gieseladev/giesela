from typing import Optional

from discord.ext.commands import BadArgument, Command, Context, Converter

from . import url_utils

__all__ = ["Url", "ImageUrl", "CommandRef"]


class Url(Converter, str):
    async def convert(self, ctx: Context, argument: str) -> str:
        return argument.strip("<>")


class ImageUrl(Url):
    async def convert(self, ctx: Context, argument: str) -> str:
        url = await super().convert(ctx, argument)
        if await url_utils.url_is_image(ctx.bot.aiosession, url):
            return url
        raise BadArgument(f"\"{url}\" doesn't look like an image!")


class CommandRef(Converter):
    async def convert(self, ctx: Context, argument: str) -> Command:
        cmd: Optional[Command] = ctx.bot.get_command(argument)

        if not cmd:
            raise BadArgument(f"Couldn't find command \"{argument}\"")

        return cmd
