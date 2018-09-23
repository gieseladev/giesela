import asyncio
import copy
import logging
import operator
import rapidjson
from typing import Any, Iterable, List, Optional, Tuple, Type

import aiohttp
from discord import Colour, Embed, Message
from discord.ext.commands import AutoShardedBot, Command, CommandError, CommandInvokeError, CommandNotFound, Context

from giesela.lib.web_author import WebAuthor
from . import cogs, constants, signals, utils
from .config import Config
from .lib import GiTilsClient

log = logging.getLogger(__name__)


class GieselaContext(Context):
    _sent_messages: List[Message]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sent_messages = []

    async def send(self, *args, **kwargs) -> Message:
        msg = await super().send(*args, **kwargs)
        self._sent_messages.append(msg)
        return msg

    async def decay(self):
        coros = (self.message.delete(), *map(operator.methodcaller("delete"), self._sent_messages))
        await asyncio.gather(*coros, return_exceptions=True)


class _StorageTypeHints:
    aiosession: aiohttp.ClientSession
    gitils: GiTilsClient

    async def ensure_permission(self, ctx: Context, *keys: str): ...

    async def has_permission(self, ctx: Context, *keys: str) -> bool: ...


class Giesela(AutoShardedBot, _StorageTypeHints):
    config: Config

    exit_signal: Optional[Type[signals.ExitSignal]]

    def __init__(self):
        super().__init__(None, )
        WebAuthor.bot = self  # TODO remove this garbage

        self._storage = {}

        self.exit_signal = None
        self.config = Config.load_app(constants.CONFIG_LOCATION)

        self.store_reference("aiosession", aiohttp.ClientSession(loop=self.loop))
        self.store_reference("gitils", GiTilsClient(self.aiosession, self.config.app.gitils.url))

        self.http.user_agent += f" Giesela/{constants.VERSION}"

        for ext in cogs.get_extensions():
            log.info(f"loading extension {ext}")
            self.load_extension(ext)

    def __getattr__(self, item: str):
        stored = self._storage.get(item)
        if stored is not None:
            return stored

        raise AttributeError(f"{self} doesn't have attribute {item}")

    def store_reference(self, key: str, value, *, override: bool = False):
        if key in self._storage and not override:
            raise KeyError(f"{key} is already in storage!")
        self._storage[key] = value

    async def persist(self, name: str, data: Any):
        key = f"{self.config.app.redis.namespaces.persist}:{name}"
        await self.config.redis.set(key, rapidjson.dumps(data))

    async def restore(self, name: str) -> Optional[Any]:
        key = f"{self.config.app.redis.namespaces.persist}:{name}"
        value = await self.config.redis.get(key)
        if value is not None:
            return rapidjson.loads(value)

    async def close(self):
        if self.is_closed():
            return

        if not self.exit_signal:
            self.exit_signal = signals.TerminateSignal

        await self.blocking_dispatch("shutdown")
        await self.aiosession.close()
        await super().close()

    async def start(self):
        log.info("loading config")
        await self.config.load_config()
        log.info("starting")
        await super().start(self.config.app.tokens.discord)

    def run(self):
        try:
            super().run()
        finally:
            if self.exit_signal:
                raise self.exit_signal

    async def on_message(self, message: Message):
        content = message.content
        if "&&" in content:
            await self.chain_commands(message)
        elif "||" in content:
            await self.run_commands_parallel(message)
        else:
            await super().on_message(message)

    async def chain_commands(self, message: Message, commands: Iterable[str] = None):
        if not commands:
            commands = map(str.lstrip, message.content.split("&&"))

        for command in commands:
            msg = copy.copy(message)
            msg.content = command
            await self.on_message(msg)

    async def run_commands_parallel(self, message: Message, commands: Iterable[str] = None):
        if not commands:
            commands = map(str.lstrip, message.content.split("||"))

        coros = []
        for command in commands:
            msg = copy.copy(message)
            msg.content = command
            coros.append(self.on_message(msg))

        await asyncio.gather(*coros)

    def find_commands(self, query: str, *, threshold: float = .5) -> List[Tuple[Command, float]]:
        commands = []

        for command in self.walk_commands():
            similarity = utils.similarity(query, (command.name, command.help), lower=True)
            if similarity > threshold:
                commands.append((command, similarity))
        commands.sort(key=operator.itemgetter(1), reverse=True)
        return commands

    async def get_prefix(self, message: Message) -> str:
        if message.guild:
            guild_id = message.guild.id
            return await self.config.get_guild(guild_id).commands.prefix
        else:
            prefixes = []
            user_id = message.author.id
            for guild in self.guilds:
                if guild.get_member(user_id):
                    prefixes.append(self.config.get_guild(guild.id).commands.prefix)

            if not prefixes:
                # if the user is in no guild (lol?), return the default guild prefix
                return await self.config.runtime.guild.commands.prefix

            return await asyncio.gather(*prefixes)

    async def get_context(self, message: Message, *, cls: Context = GieselaContext) -> Context:
        return await super().get_context(message, cls=cls)

    @classmethod
    async def on_command(cls, ctx: Context):
        if ctx.command:
            log.debug(f"{ctx.author} invoked {ctx.command.qualified_name}")

    async def on_command_finished(self, ctx: Context, **_):
        if isinstance(ctx, GieselaContext) and ctx.guild:
            decay_delay = await self.config.get_guild(ctx.guild.id).commands.message_decay
            if decay_delay:
                await asyncio.sleep(decay_delay)
                await ctx.decay()

    async def on_command_completion(self, ctx: Context):
        self.dispatch("command_finished", ctx)

    async def on_command_error(self, ctx: Context, exception: Exception):
        report = True

        if isinstance(exception, CommandError):
            if isinstance(exception, CommandInvokeError):
                original = exception.original

                if isinstance(original, signals.ExitSignal):
                    self.exit_signal = type(original)
                    await self.logout()
                    return

                description = "There was an internal error while processing your command." \
                              "This shouldn't happen (obviously) and it isn't your fault *(maybe)*.\n"

                embed = Embed(title="Internal Error", description=description, colour=Colour.dark_red())
                embed.add_field(name="Please ask someone (who knows their shit) to take a look at this:",
                                value=f"```python\n{original!r}```",
                                inline=False)
            else:
                embed = None
                if isinstance(exception, CommandNotFound):
                    query = ctx.invoked_with + ctx.view.read_rest()
                    commands = self.find_commands(query)
                    if commands:
                        commands = set(next(zip(*commands)))
                        embed = Embed(title="Did you mean:", colour=Colour.orange())
                        for cmd in commands:
                            if len(embed.fields) >= 25:
                                break
                            embed.add_field(name=cmd.qualified_name, value=f"`{cmd.short_doc}`")
                if not embed:
                    embed = Embed(title=type(exception).__name__, description=str(exception), colour=Colour.red())
                report = False

            await ctx.send(embed=embed)

        # TODO use sentry directly and add even more details
        log.exception("CommandError:", exc_info=exception, extra=dict(report=report, tags=dict(guild_id=ctx.guild.id, author_id=ctx.author.id)))

        self.dispatch("command_finished", ctx, exception=exception)

    @classmethod
    async def on_ready(cls):
        log.info(f"Connected!  Giesela v{constants.VERSION}")

    async def on_error(self, event: str, *args, **kwargs):
        log.exception(f"Error in {event} ({args}, {kwargs})")

    async def blocking_dispatch(self, event: str, *args, **kwargs):
        log.debug(f"Dispatching event {event}")
        method = f"on_{event}"
        handler = f"_handle_{event}"

        listeners = self._listeners.get(event)
        if listeners:
            removed = []
            for i, (future, condition) in enumerate(listeners):
                if future.cancelled():
                    removed.append(i)
                    continue

                try:
                    result = condition(*args)
                except Exception as e:
                    future.set_exception(e)
                    removed.append(i)
                else:
                    if result:
                        if len(args) == 0:
                            future.set_result(None)
                        elif len(args) == 1:
                            future.set_result(args[0])
                        else:
                            future.set_result(args)
                        removed.append(i)

            if len(removed) == len(listeners):
                self._listeners.pop(event)
            else:
                for idx in reversed(removed):
                    del listeners[idx]

        try:
            actual_handler = getattr(self, handler)
        except AttributeError:
            pass
        else:
            actual_handler(*args, **kwargs)

        coros = []

        try:
            coro = getattr(self, method)
        except AttributeError:
            pass
        else:
            coro = self._run_event(coro, method, *args, **kwargs)
            coros.append(coro)

        for ev in self.extra_events.get(method, []):
            coro = self._run_event(ev, event, *args, **kwargs)
            coros.append(coro)

        if coros:
            await asyncio.gather(*coros)
