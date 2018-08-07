import inspect
import itertools

from discord import Colour, Embed
from discord.ext import commands
from discord.ext.commands import Bot, Command, Context, HelpFormatter

from giesela import VERSION as BOTVERSION
from giesela.lib.ui import EmbedPaginator, copy_embed
from giesela.utils import (get_dev_version,
                           get_version_changelog)


class Info:
    def __init__(self, bot: Bot):
        self.bot = bot

        bot.remove_command("help")
        self.formatter = GieselaHelpFormatter(width=50)

    @commands.command()
    async def version(self, ctx: Context):
        """Some more information about the current version and what's to come."""

        async with ctx.typing():
            v_code, v_name = BOTVERSION.split("_", 1)
            dev_code, dev_name = get_dev_version()
            if v_code == dev_code:
                changelog = "**Up to date!**"
            else:
                changelog = "**What's to come:**\n\n"
                changelog += "\n".join(
                    "● " + l for l in get_version_changelog()
                )

        desc = "Current Version is `{}`\nDevelopment is at `{}`\n\n{}".format(
            BOTVERSION, dev_code + "_" + dev_name, changelog)[:2000]

        em = Embed(title="Version \"{}\"".format(v_name.replace("_", " ").title()), description=desc,
                   url="https://gieseladev.github.io/Giesela", colour=0x67BE2E)

        await ctx.send(embed=em)

    @commands.command()
    async def help(self, ctx, *cmds):
        """Help me

        [p]help [Category]
        [p]help [Command]

        Just use whatever you want ¯\_(ツ)_/¯
        """

        async def _command_not_found(_name: str):
            _em = Embed(description=f"No command called **{_name}**", colour=Colour.red())
            await ctx.send(embed=_em)

        bot = ctx.bot
        if len(cmds) == 0:
            embeds = await self.formatter.format_help_for(ctx, bot)
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

            embeds = await self.formatter.format_help_for(ctx, cmd)
        else:
            # handle groups
            name = cmds[0]
            cmd = bot.all_commands.get(name)
            if cmd is None:
                await _command_not_found(name)
                return

            for key in cmds[1:]:
                try:
                    cmd = cmd.all_commands.get(key)
                    if cmd is None:
                        await _command_not_found(key)
                        return
                except AttributeError:
                    em = Embed(description=f"Command **{cmd.name}** has no subcommands", colour=Colour.red())
                    await ctx.send(embed=em)
                    return

            embeds = await self.formatter.format_help_for(ctx, cmd)

        for embed in embeds:
            await ctx.send(embed=embed)


class GieselaHelpFormatter(HelpFormatter):
    async def format(self):
        template_embed = Embed(colour=Colour.green())
        first_embed = copy_embed(template_embed)
        first_embed.title = "Giesela Help"

        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)
        if description:
            first_embed.description = description

        paginator = EmbedPaginator(template=template_embed, special_template=first_embed)

        def get_commands_text(_commands):
            max_width = self.max_name_size
            value = ""
            for name, cmd in _commands:
                if name in cmd.aliases:
                    # skip aliases
                    continue

                entry = f"{name:<{max_width}} | {cmd.short_doc}"
                shortened = self.shorten(entry)
                value += shortened + "\n"
            return value

        def get_final_embeds():
            embeds = paginator.embeds
            embeds[-1].set_footer(text=self.get_ending_note(), icon_url=embeds[-1].footer.icon_url)
            return embeds

        if isinstance(self.command, Command):
            # <signature portion>
            signature = self.get_command_signature()
            paginator.add_field("Syntax", f"```fix\n{signature}```")

            # <long doc> section
            if self.command.help:
                paginator.add_field("Help", f"```css\n{self.command.help}```")

            # end it here if it's just a regular command
            if not self.has_subcommands():
                return get_final_embeds()

        def category(tup):
            cog = tup[1].cog_name
            # we insert the zero width space there to give it approximate
            # last place sorting position.
            return cog + ":" if cog is not None else "\u200bNo Category:"

        if self.is_bot():
            data = sorted(await self.filter_command_list(), key=category)
            for category, command_list in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                command_list = list(command_list)
                if len(command_list) > 0:
                    name = category
                    value = get_commands_text(command_list)
                    paginator.add_field(name, f"```css\n{value}```")
        else:
            value = get_commands_text(await self.filter_command_list())
            paginator.add_field("Commands", f"```css\n{value}```")

        return get_final_embeds()


def setup(bot: Bot):
    bot.add_cog(Info(bot))
