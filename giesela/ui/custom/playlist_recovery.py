import asyncio
import inspect
import logging
from collections import OrderedDict
from typing import Any, Optional, Type

from discord import Colour, Embed, TextChannel, User
from discord.ext import commands
from discord.ext.commands import Context

from giesela import Extractor
from giesela.playlist import Playlist, PlaylistRecovery
from .. import text
from ..help import AutoHelpEmbed
from ..interactive import Abortable, InteractableEmbed, MessageableEmbed, emoji_handler
from ..ui_utils import CustomParamsCommand

log = logging.getLogger(__name__)


class PlaylistRecoveryUI(AutoHelpEmbed, MessageableEmbed, Abortable, InteractableEmbed):
    extractor: Extractor
    recovery: PlaylistRecovery

    _current_task: asyncio.Task

    def __init__(self, channel: TextChannel, user: User = None, **kwargs) -> None:
        self.extractor = kwargs.pop("extractor")
        self.recovery = kwargs.pop("recovery")

        super().__init__(channel, user=user, **kwargs)

        self.recovery.provide_extractor(self.extractor)

        self._current_task = None
        self._is_done = False

    @property
    def help_title(self) -> str:
        return "Playlist Recovery"

    @property
    def help_description(self) -> str:
        return "The playlist recovery progress includes a number of steps. Some of which might even require your input!"

    def build_playlist(self) -> Optional[Playlist]:
        return self.recovery.try_build()

    async def display(self):
        await self.after_advance()
        await self.wait_for_listener()
        if self._current_task:
            self._current_task.cancel()

        await self.delete()
        return self._is_done

    def get_embed_frame(self) -> Embed:
        name = self.recovery.information.get("name", "Playlist")
        embed = Embed(title=f"{name} Recovery", colour=Colour.dark_green())
        embed.set_footer(text=f"Step {self.recovery.current_step_index + 1}/{len(self.recovery)}")
        return embed

    async def get_step_embed(self) -> Embed:
        embed = self.get_embed_frame()
        step = self.recovery.current_step

        if self.recovery.is_input:
            embed.colour = Colour.blue()
            embed.title = "Input required"
            embed.description = "Please provide the following values"

            for arg in step.required_input:
                value = step.args.get(arg, "`Please set`")
                embed.add_field(name=arg, value=value)

        elif step.description:
            embed.description = step.description

        if self.error:
            embed.add_field(name="Error", value=self.error, inline=False)
            embed.colour = Colour.red()
            self.error = None

        return embed

    async def on_command_error(self, ctx: Optional[Context], exception: Exception):
        await super().on_command_error(ctx, exception)
        await self.update_window()

    async def on_emoji_handler_error(self, error: Exception, *_):
        await self.on_command_error(None, error)

    async def update_window(self):
        embed = await self.get_step_embed()
        await self.edit(embed)

    async def show_window(self):
        await self.update_window()
        self._current_task = asyncio.ensure_future(self.maybe_advance())

    async def after_advance(self):
        self.menu_command.clear_dynamic_commands()

        if self.recovery.done:
            log.debug(f"recovery done {self.recovery}")
            self._is_done = True
            self.cancel_listener()
        else:
            if self.recovery.is_input:
                step = self.recovery.current_step
                for name, value_type in step.required_input.items():
                    cmd = self.create_dynamic_input_command(name, value_type)
                    self.menu_command.add_dynamic_command(cmd)

            await self.show_window()

    async def advance(self):
        progress_update = asyncio.ensure_future(self._show_progress())
        try:
            await self.recovery.advance()
        finally:
            progress_update.cancel()
        await self.after_advance()

    async def maybe_advance(self):
        if self.recovery.can_advance and not self.recovery.is_input:
            await self.advance()

    async def _show_progress(self):
        step = self.recovery.current_step
        last_progress = None
        while True:
            progress = step.progress

            if last_progress is not None and progress == last_progress:
                await asyncio.sleep(1)
                continue

            last_progress = progress

            if progress is None:
                description = "Processing..."
            else:
                description = text.create_bar(progress, length=30)
            embed = self.get_embed_frame()
            embed.colour = Colour.greyple()

            embed.add_field(name="Progress", value=description)

            await self.edit(embed)

    async def set_input(self, arg: str, value: Any):
        await self.recovery.provide_input({arg: value})
        await self.update_window()

    def create_dynamic_input_command(self, name: str, value: Type) -> commands.Command:
        help_text = f"Set the {name} input"

        async def set_value(_, **kwargs):
            key, val = next(iter(kwargs.items()))
            await self.set_input(key, val)

        ctx_param = inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD)
        value_param = inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=value)
        params = OrderedDict((("ctx", ctx_param), (name, value_param)))
        cmd = CustomParamsCommand(name, set_value, params, help=help_text)
        return cmd

    @emoji_handler("✅")
    async def submit_input(self, *_):
        """Submit your input

        This button is only necessary when your input is required.
        """
        if not self.recovery.is_input:
            raise commands.CommandError("Don't need any input right now, thx")
        if not self.recovery.can_advance:
            raise commands.CommandError("Not all required values set yet")

        self._current_task = asyncio.ensure_future(self.advance())
