import inspect
import itertools
from typing import Iterable, List, Tuple, Union

from discord import Colour, Embed, Message
from discord.ext import commands
from discord.ext.commands import Command, Context, HelpFormatter

from giesela.ui import EmbedPaginator, copy_embed


class GieselaHelpFormatter(HelpFormatter):
    def get_max_width(self, _commands: Iterable[Tuple[str, Command]]) -> int:
        try:
            return self.max_name_size
        except AttributeError:
            return max(len(name) for name, command in _commands)

    def get_commands_text(self, _commands: Iterable[Tuple[str, Command]]) -> str:
        _commands = list(_commands)
        max_width = self.get_max_width(_commands)
        value = ""
        for name, cmd in _commands:
            if name in cmd.aliases:
                # skip aliases
                continue

            entry = f"{name:<{max_width}} | {cmd.short_doc}"
            shortened = self.shorten(entry)
            value += shortened + "\n"
        return value

    async def format(self):
        template_embed = Embed(colour=Colour.green())
        first_embed = copy_embed(template_embed)
        first_embed.title = "Giesela Help"

        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)
        if description:
            first_embed.description = description

        paginator = EmbedPaginator(template=template_embed, special_template=first_embed)

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
                    value = self.get_commands_text(command_list)
                    if value:
                        paginator.add_field(name, f"```css\n{value}```")
        else:
            value = self.get_commands_text(await self.filter_command_list())
            if value:
                paginator.add_field("Commands", f"```css\n{value}```")

        return get_final_embeds()

    async def send_help_for(self, context: Context, command_or_bot: Union[commands.Bot, commands.Command]) -> List[Message]:
        embeds = await self.format_help_for(context, command_or_bot)
        messages = []
        for embed in embeds:
            msg = await context.send(embed=embed)
            messages.append(msg)
        return messages


help_formatter = GieselaHelpFormatter(width=50)
