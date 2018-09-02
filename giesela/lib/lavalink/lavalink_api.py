from typing import Any, Dict

from discord import Client
from websockets import ConnectionClosed

from .models import LavalinkEvent, LavalinkPlayerState
from .rest_client import LavalinkREST
from .ws_client import LavalinkWebSocket

__all__ = ["LavalinkAPI"]


class LavalinkAPI(LavalinkREST, LavalinkWebSocket):
    def __init__(self, bot: Client, password: str, rest_url: str, ws_url: str, **kwargs):
        super().__init__(bot=bot, password=password, rest_url=rest_url, ws_url=ws_url, **kwargs)

    async def on_event(self, guild_id: int, event: LavalinkEvent, track, data: Dict[str, Any]):
        pass

    async def on_unknown_event(self, event_type: str, data: Dict[str, Any]):
        pass

    async def on_player_update(self, guild_id: int, state: LavalinkPlayerState):
        pass

    async def on_disconnect(self, error: ConnectionClosed):
        pass
