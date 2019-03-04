import functools
import inspect
import logging

from discord import ClientException, Colour, Embed
from discord.ext import commands
from discord.ext.commands import Bot, Command, Context

from giesela import VERSION as BOTVERSION
from giesela.lib import help_formatter

log = logging.getLogger(__name__)


class Info:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

        bot.remove_command("help")
        self.formatter = help_formatter

    async def on_ready(self):
        for command in self.bot.commands:
            self.ensure_help_sub_command(command)

    def ensure_help_sub_command(self, group: commands.Group):
        if not isinstance(group, commands.Group):
            return

        func = functools.partial(self._send_help, cmd=group.name)
        func.__module__ = __package__
        sub_cmd = Command(name="help", callback=func, aliases=["?"], hidden=True, help=f"Help for {group.qualified_name}")
        sub_cmd.params.pop("cmd")
        sub_cmd.params["cmds"] = inspect.Parameter("cmds", inspect.Parameter.VAR_POSITIONAL, annotation=str)

        try:
            group.add_command(sub_cmd)
        except ClientException:
            log.debug(f"{group} already defines a help function")

    @commands.command()
    async def version(self, ctx: Context):
        """Some more information about the current version and what's to come."""
        v_code, v_name = BOTVERSION.split("_", 1)
        desc = f"Giesela v`{v_code}` (**{v_name}**)"

        em = Embed(title=f"Version", description=desc, colour=0x67BE2E)

        await ctx.send(embed=em)

    async def _send_help(self, ctx: Context, *_cmds: str, cmd: str = None):
        async def _command_not_found(_name: str):
            _em = Embed(description=f"No command called **{_name}**", colour=Colour.red())
            await ctx.send(embed=_em)

        bot = ctx.bot
        cmds = list(_cmds)
        if cmd:
            cmds.insert(0, cmd)

        if len(cmds) == 0:
            cmd = bot
        elif len(cmds) == 1:
            # try to see if it is a cog name
            name = cmds[0]
            if name in bot.cogs:
                cmd = bot.cogs[name]
            else:
                cmd = bot.all_commands.get(name)
                if cmd is None:
                    await _command_not_found(name)
                    return
        else:
            # handle groups
            name = cmds[0]
            group = bot.all_commands.get(name)
            if group is None:
                await _command_not_found(name)
                return

            for key in cmds[1:]:
                try:
                    group = group.all_commands.get(key)
                    if group is None:
                        await _command_not_found(key)
                        return
                except AttributeError:
                    em = Embed(description=f"Command **{group.name}** has no subcommands", colour=Colour.red())
                    await ctx.send(embed=em)
                    return

            cmd = group

        await self.formatter.send_help_for(ctx, cmd)

    @commands.command(aliases=["?"])
    async def help(self, ctx: Context, *cmds):
        """Get the help you c̶l̶e̶a̶r̶l̶y̶ need"""
        await self._send_help(ctx, *cmds)


def setup(bot: Bot):
    bot.add_cog(Info(bot))
