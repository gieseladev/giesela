from typing import Optional, TYPE_CHECKING, Union

from aiohttp import ClientSession
from discord import Guild, Member, User, VoiceChannel
from discord.ext.commands import Context

from giesela.utils import annotation_only

if TYPE_CHECKING:
    from .extractor import Extractor
    from .permission import PermManager, PermissionType, RoleTargetType
    from .player import GieselaPlayer
    from .playlist import PlaylistManager
    from .radio import RadioStationManager
    from .lib.gitils import GiTilsClient

__all__ = ["GieselaRefStorageTypeHints"]


@annotation_only
class GieselaRefStorageTypeHints:
    """Type hints for references stored in Giesela's "storage" by extensions"""
    aiosession: ClientSession
    gitils: "GiTilsClient"

    extractor: "Extractor"

    async def get_player(self, target: Union[Guild, Context, int], *,
                         create: bool = True, channel: VoiceChannel = None, member: Union[User, Member] = None) -> Optional["GieselaPlayer"]: ...

    perm_manager: "PermManager"

    async def ensure_permission(self, ctx: Union[Context, User], *keys: "PermissionType", global_only: bool = False) -> True: ...

    async def has_permission(self, target: "RoleTargetType", *perms: "PermissionType", global_only: bool = False) -> bool: ...

    playlist_manager: "PlaylistManager"

    radio_station_manager: "RadioStationManager"
