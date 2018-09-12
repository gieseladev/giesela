from typing import Awaitable, Optional

from .abstract import ConfigObject


class Commands(ConfigObject):
    prefix: str = "!"
    menu_prefix: str = ""
    message_decay: Optional[float] = 30


class _AsyncCommands:
    prefix: Awaitable[str]
    menu_prefix: Awaitable[str]
    message_decay: Awaitable[Optional[float]]


class Player(ConfigObject):
    volume: float = .1
    auto_pause: bool = True
    auto_disconnect: float = 20

    queue_limit: Optional[int] = None
    history_limit: int = 200

    voice_channel_id: Optional[int] = None


class _AsyncPlayer:
    volume: Awaitable[float]
    auto_pause: Awaitable[bool]
    auto_disconnect: Awaitable[float]

    queue_limit: Awaitable[Optional[int]]
    history_limit: Awaitable[int]

    voice_channel_id: Awaitable[Optional[int]]


class Guild(ConfigObject):
    commands: Commands
    player: Player


class _AsyncGuild:
    commands: _AsyncCommands
    player: _AsyncPlayer
