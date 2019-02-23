from enum import Enum
from pathlib import Path
from typing import List

from .abstract import ConfigObject, Truthy
from .runtime import Runtime


class Tokens(ConfigObject):
    discord: str = Truthy()
    google_api: str = Truthy()


class RedisNamespaces(ConfigObject):
    config: str = Truthy("config")
    permissions: str = Truthy("permissions")
    queue: str = Truthy("queue")
    persist: str = Truthy("persist")


class Redis(ConfigObject):
    uri: str = Truthy()
    database: int = 0
    namespaces: RedisNamespaces


class MongodbCollections(ConfigObject):
    config: str = Truthy("config")
    permissions: str = Truthy("perm")


class Mongodb(ConfigObject):
    uri: str = Truthy()
    database: str = "Giesela"
    collections: MongodbCollections


class LavalinkNodeRegion(Enum):
    GLOBAL = "global"
    EU = "eu"  # Eu first, America second
    US = "us"
    ASIA = "asia"


class LavalinkNode(ConfigObject):
    region: LavalinkNodeRegion = LavalinkNodeRegion.GLOBAL
    address: str = Truthy()
    password: str = Truthy()
    secure: bool = False


class Lavalink(ConfigObject):
    nodes: List[LavalinkNode]


class Webiesela(ConfigObject):
    start: bool = True
    port: int = 30000


class GiTils(ConfigObject):
    url: str = Truthy("https://gitils.giesela.io")


class Files(ConfigObject):
    data: str = Truthy("data")

    permissions: str = Truthy("permissions.yml")
    radio_stations: str = Truthy("radio_stations.yml")
    certificates: str = Truthy("cert/")
    playlists: str = Truthy("playlists/playlists")

    def __init__(self) -> None:
        data_path = Path(self.data)
        # these should be relative to data folder
        for key in ("permissions", "radio_stations", "certificates", "playlists"):
            path = Path(getattr(self, key))
            if not path.root:
                path = data_path / path.joinpath()
            setattr(self, key, str(path))


class Misc(ConfigObject):
    image_cx: str = "002017775112634544492:t0ynfpg8y0e"


class Application(ConfigObject):
    tokens: Tokens
    redis: Redis
    mongodb: Mongodb
    lavalink: Lavalink
    webiesela: Webiesela
    gitils: GiTils
    files: Files
    misc: Misc

    runtime: Runtime
