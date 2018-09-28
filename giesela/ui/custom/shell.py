from textwrap import TextWrapper
from typing import Any, Mapping, Optional, Tuple

from discord import Embed, Message
from discord.ext import commands
from discord.ext.commands import CommandNotFound, Context

from giesela import GieselaShell
from giesela.shell import ShellLine
from ..help import AutoHelpEmbed
from ..interactive import MessageableEmbed, VerticalTextViewer, emoji_handler

_TEXT_WRAPPER = dict(width=70, max_lines=10, drop_whitespace=False, replace_whitespace=False)
TEXT_WRAPPER = TextWrapper(**_TEXT_WRAPPER)


def prepare_shell_line(line: ShellLine) -> str:
    raw_code = line.code

    if line.oneliner:
        code = f">>> `{raw_code}`"
    else:
        code = f"```{line.interpreter.highlight_language}\n{raw_code}```"

    if not line.result_str:
        return code

    result = TEXT_WRAPPER.fill(line.result_str)
    result_lines = result.splitlines()

    if line.error:
        result = f"```fix\n{result}```"
    elif len(result_lines) > 1:
        result = f"```\n{result}```"

    return f"{code}\n{result}"


class ShellUI(AutoHelpEmbed, MessageableEmbed, VerticalTextViewer):
    ctx: Context
    shell: GieselaShell

    run_timeout: Optional[int]
    upload_url: Optional[Tuple[str, str]]

    def __init__(self, ctx: Context, *, variables: Mapping[str, Any] = None, **kwargs) -> None:
        shell = kwargs.pop("shell", None)
        interpreter_kwargs = variables or {}
        interpreter_kwargs.update(ctx=ctx)

        if isinstance(shell, str):
            shell = GieselaShell.find_interpreter(shell, **interpreter_kwargs)
        elif not shell:
            shell = GieselaShell.python(**interpreter_kwargs)

        self.shell = shell

        super().__init__(ctx.channel, user=ctx.author, bot=ctx.bot, **kwargs)

        self.ctx = ctx
        self.run_timeout = None
        self.upload_url = None

    @property
    def help_title(self) -> str:
        return "GieselaShell Help"

    @property
    def help_description(self) -> str:
        return "Run some fancy code or something idc.\n" \
               "Anyway, you can prefix your messages with `>>>` if you want to escape commands."

    @property
    def total_lines(self) -> int:
        return len(self.shell.history)

    @property
    def embed_frame(self) -> Embed:
        language = self.shell.interpreter.language_name
        embed = Embed(title=f"{language} Shell")
        embed.set_footer(text="{progress_bar}")

        if self.upload_url:
            adapter_name, url = self.upload_url
            embed.url = url
            embed.add_field(name=f"{adapter_name} Upload", value=f"[{url}]({url})", inline=False)

        return embed

    async def get_line(self, line: int) -> str:
        shell_line = self.shell.history[line]
        return prepare_shell_line(shell_line)

    async def on_command_error(self, ctx: Context, exception: Exception):
        if isinstance(exception, CommandNotFound):
            await self.on_line(ctx)
        else:
            await super().on_command_error(ctx, exception)

    async def _run(self, content: str):
        await self.shell.run(content, timeout=self.run_timeout)
        await self.show_window()

    async def on_line(self, ctx: Context):
        await self._run(ctx.message.content)

    async def on_message(self, message: Message):
        content = message.content
        if content.startswith(">"):
            await self._run(content.lstrip(">"))
            await message.delete()
        else:
            await super().on_message(message)

    async def stop(self):
        await self.shell.stop()
        await super().stop()

    async def _upload_history(self, **kwargs):
        link = await self.shell.upload(**kwargs)
        self.upload_url = (self.shell.upload_adapter.NAME, link)
        await self.show_window()

    @emoji_handler("📄", pos=1099)
    async def upload_history(self, *_):
        """Upload and get link"""
        await self._upload_history()

    @emoji_handler("🚮", pos=1100)
    async def clear_history(self, *_):
        """Clear history"""
        self.shell.history.clear()
        self.upload_url = None
        await self.show_window()

    @commands.command()
    async def prettify(self, _):
        """Beautify previous output"""
        self.shell.prettify()
        await self.show_window()

    @commands.command("upload", aliases=["up", "save"])
    async def upload_history_cmd(self, _, full: bool = False):
        """Upload history"""
        await self._upload_history(skip_errors=not full)
