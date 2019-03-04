import inspect
import logging
import random
import textwrap
import time
import traceback
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Optional

import aiohttp
from discord import Colour, Embed, Message
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, RestartSignal, TerminateSignal, permission, utils
from giesela.permission import perm_tree
from giesela.shell import InterpreterUnavailable
from giesela.ui.custom import ShellUI

log = logging.getLogger(__name__)


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: Giesela) -> None:
        self.bot = bot
        self.aiosession = self.bot.aiosession

    @commands.Cog.listener()
    async def on_ready(self):
        goodbye_message = await self.bot.restore("goodbye_message", delete_after=True)
        if goodbye_message:
            channel_id = goodbye_message.get("channel_id")
            message_id = goodbye_message.get("message_id")

            if channel_id and message_id:
                emoji = random.choice([
                    # choice
                    "👌", "✋", "👍", "👎", "🖕", "👊", "🤘", "✊", "💪",
                    # direction
                    "☛",
                    # emotions
                    "✌", "👏", "👋", "🙌",
                    # misc
                    "🤙", "🤞"
                ])

                ts = goodbye_message.get("timestamp")
                if ts:
                    time_diff = int(time.time()) - ts
                    time_str = utils.format_time(time_diff)
                else:
                    time_str = "who knows how long"

                try:
                    await self.bot.http.edit_message(message_id, channel_id, content=f"{emoji} I'm back after {time_str}!")
                except Exception as e:
                    log.warning(f"Couldn't update goodbye message: {e}")

    @permission.has_global_permission(perm_tree.admin.control.execute)
    @commands.command()
    async def execute(self, ctx: Context):
        """Execute a statement"""
        pre = len(ctx.prefix + ctx.command.qualified_name)
        statement = ctx.message.content[pre + 1:]
        beautiful_statement = "```python\n{}\n```".format(statement)

        statement = "async def func():\n{}".format(textwrap.indent(statement, "\t"))
        await ctx.send("**RUNNING CODE**\n{}".format(beautiful_statement))

        env = {
            "bot": self.bot
        }
        env.update(globals())
        env.update(locals())

        console = StringIO()

        try:
            exec(statement, env)
        except SyntaxError as e:
            await ctx.send("**While compiling the statement the following error occurred**\n{}\n{}".format(traceback.format_exc(), str(e)))
            return

        func = env["func"]

        try:
            with redirect_stdout(console):
                ret = await func()
        except Exception as e:
            await ctx.send("**While executing the statement the following error occurred**\n{}\n{}".format(traceback.format_exc(), str(e)))
            return

        res = str(ret)
        if ret is not None and res:
            result = "**RESULT**\n{}".format(res)
        else:
            result = ""

        logged = console.getvalue().strip()

        if logged:
            result += "\n**Console**\n```\n{}\n```".format(logged)

        result = result.strip()
        if result:
            await ctx.send(result)

    @permission.has_global_permission(perm_tree.admin.control.execute)
    @commands.command()
    async def shell(self, ctx: Context, interpreter: str = "python"):
        """Open the GieselaShell™"""
        player = await self.bot.get_player(ctx)

        try:
            shell = ShellUI(ctx.channel, shell=interpreter, variables=dict(player=player, ctx=ctx), bot=self.bot, user=ctx.author)
        except InterpreterUnavailable as e:
            raise commands.CommandError(e.msg)

        await shell.display()

    @permission.has_global_permission(perm_tree.admin.control.shutdown)
    @commands.command()
    async def shutdown(self, ctx: Context):
        """Shutdown"""
        await ctx.send(":wave:")
        raise TerminateSignal

    @permission.has_global_permission(perm_tree.admin.control.shutdown)
    @commands.command()
    async def restart(self, ctx: Context):
        """Restart"""
        msg: Message = await ctx.send(":wave: goodbye")

        await self.bot.persist("goodbye_message", {
            "timestamp": int(time.time()),
            "channel_id": msg.channel.id,
            "message_id": msg.id,
        })

        raise RestartSignal

    @permission.has_global_permission(perm_tree.admin.control.impersonate)
    @commands.command()
    async def say(self, ctx: Context, msg: str):
        """Say something"""

        await ctx.message.delete()
        await ctx.send(msg)

    @permission.has_global_permission(perm_tree.admin.appearance.name)
    @commands.command()
    async def setname(self, ctx: Context, name: str):
        """Set name..."""

        try:
            await self.bot.user.edit(username=name)
        except Exception as e:
            raise commands.CommandError(e)

        await ctx.send(":ok_hand:")
        return

    @permission.has_global_permission(perm_tree.admin.appearance.avatar)
    @commands.command()
    async def setavatar(self, ctx: Context, url: str = None):
        """Set avatar"""

        if ctx.message.attachments:
            thing = ctx.message.attachments[0]["url"]
        elif url:
            thing = url.strip("<>")
        else:
            raise commands.CommandError("Please provide a url or attach an image!")

        try:
            with aiohttp.ClientTimeout(10):
                async with self.aiosession.get(thing) as res:
                    await self.bot.user.edit(avatar=await res.read())

        except Exception as e:
            raise commands.CommandError(f"Unable to change avatar: {e}")

        await ctx.send(":ok_hand:")
        return

    @permission.has_global_permission(perm_tree.admin.control.execute)
    @commands.command(name="reloadext", aliases=["extreload"])
    async def reload_extension_cmd(self, ctx: Context, extension: str) -> None:
        """Reload an extension"""

        def _get_extension_name(ext: str) -> Optional[str]:
            if ext in self.bot.extensions:
                return ext

            ext = Path(ext).stem
            if ext in self.bot.extensions:
                return ext

            ext = f"giesela.extensions.{ext}"
            if ext in self.bot.extensions:
                return ext

            return None

        ext_name = _get_extension_name(extension)

        if not ext_name:
            cog = self.bot.get_cog(extension)
            if not cog:
                raise commands.CommandError(f"Couldn't find extension or cog {extension}")

            ext_name = _get_extension_name(inspect.getfile(type(cog)))
            if not ext_name:
                raise commands.CommandError(f"No extension for cog {extension})")

        self.bot.unload_extension(ext_name)
        self.bot.load_extension(ext_name)

        await ctx.send(embed=Embed(description=f"Extension {extension} reloaded!", colour=Colour.green()))


def setup(bot: Giesela):
    bot.add_cog(AdminCog(bot))
