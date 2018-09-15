import textwrap
import traceback
from contextlib import redirect_stdout
from io import StringIO

import aiohttp
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Giesela, RestartSignal, TerminateSignal, permission, perms
from giesela.shell import InterpreterUnavailable
from giesela.ui.custom import ShellUI


class AdminTools:
    def __init__(self, bot: Giesela):
        self.bot = bot
        self.aiosession = getattr(bot, "aiosession", None)

        if not self.aiosession:
            self.aiosession = aiohttp.ClientSession(loop=self.bot.loop)
   
    @commands.is_owner()
    @permission.has_permission(perms.admin.control.execute)
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

        log = console.getvalue().strip()

        if log:
            result += "\n**Console**\n```\n{}\n```".format(log)

        result = result.strip()
        if result:
            await ctx.send(result)
    
    @commands.is_owner()
    @permission.has_permission(perms.admin.control.execute)
    @commands.command()
    async def shell(self, ctx: Context, interpreter: str = "python"):
        """Open the GieselaShell™"""
        player = await self.bot.get_player(ctx)

        try:
            shell = ShellUI(ctx, shell=interpreter, variables=dict(player=player))
        except InterpreterUnavailable as e:
            raise commands.CommandError(e.msg)

        await shell.display()

    @commands.is_owner()
    @permission.has_permission(perms.admin.control.shutdown)
    @commands.command()
    async def shutdown(self, ctx: Context):
        """Shutdown"""
        await ctx.send(":wave:")
        raise TerminateSignal

    @commands.is_owner()
    @permission.has_permission(perms.admin.control.shutdown)
    @commands.command()
    async def restart(self, ctx: Context):
        """Restart"""
        await ctx.send(":wave:")
        raise RestartSignal

    @commands.is_owner()
    @permission.has_permission(perms.admin.control.impersonate)
    @commands.command()
    async def say(self, ctx: Context, msg: str):
        """Say something"""

        await ctx.message.delete()
        await ctx.send(msg)

    @commands.is_owner()
    @permission.has_permission(perms.admin.appearance.name)
    @commands.command()
    async def setname(self, ctx: Context, name: str):
        """Set name..."""

        try:
            await self.bot.user.edit(username=name)
        except Exception as e:
            raise commands.CommandError(e)

        await ctx.send(":ok_hand:")
        return
        
    @commands.is_owner()
    @permission.has_permission(perms.admin.appearance.avatar)
    @commands.command()
    async def setavatar(self, ctx: Context, url: str = None):
        """Set avatar"""

        if ctx.message.attachments:
            thing = ctx.message.attachments[0]["url"]
        else:
            thing = url.strip("<>")

        try:
            with aiohttp.ClientTimeout(10):
                async with self.aiosession.get(thing) as res:
                    await self.bot.user.edit(avatar=await res.read())

        except Exception as e:
            raise commands.CommandError(f"Unable to change avatar: {e}")

        await ctx.send(":ok_hand:")
        return


def setup(bot: Giesela):
    bot.add_cog(AdminTools(bot))
