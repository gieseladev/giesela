from typing import Awaitable, Optional

from .abstract import ConfigObject
from .guild import Guild, _AsyncGuild


class Misc(ConfigObject):
    idle_game: Optional[str] = "Waiting for someone to queue something..."


class _AsyncMisc:
    idle_game: Awaitable[Optional[str]]


class Runtime(ConfigObject):
    misc: Misc
    guild: Guild


class _AsyncRuntime:
    misc: _AsyncMisc
    guild: _AsyncGuild
