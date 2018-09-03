from typing import Any, Dict

from discord import Client
from websockets import ConnectionClosed

from .models import LavalinkEvent, LavalinkPlayerState, TrackEventDataType
from .rest_client import LavalinkREST
from .ws_client import LavalinkWebSocket

__all__ = ["LavalinkAPI"]


class LavalinkAPI(LavalinkREST, LavalinkWebSocket):
    def __init__(self, bot: Client, password: str, address: str, secure: bool, **kwargs):
        super().__init__(bot=bot, password=password, lavalink_address=address, lavalink_secure=secure, **kwargs)

    async def on_event(self, guild_id: int, event: LavalinkEvent, data: TrackEventDataType):
        pass

    async def on_unknown_event(self, event_type: str, raw_data: Dict[str, Any]):
        pass

    async def on_player_update(self, guild_id: int, state: LavalinkPlayerState):
        pass

    async def on_disconnect(self, error: ConnectionClosed):
        pass
