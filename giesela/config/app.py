from pathlib import Path
from typing import List

from .abstract import ConfigObject, Truthy
from .guild import Guild


class Tokens(ConfigObject):
    discord: str = Truthy()
    google_api: str = Truthy()


class RedisDatabases(ConfigObject):
    config: str = "config"
    queue: str = "queue"


class Redis(ConfigObject):
    uri: str = Truthy()
    databases: RedisDatabases


class Mongodb(ConfigObject):
    uri: str = Truthy()
    database: str = "Giesela"


class LavalinkNode(ConfigObject):
    address: str = Truthy()
    password: str = Truthy()
    secure: bool = False


class Lavalink(ConfigObject):
    nodes: List[LavalinkNode]


class Webiesela(ConfigObject):
    start: bool = True
    port: int = 30000


class Files(ConfigObject):
    data: str = "data"

    certificates: str = "cert/"
    radio_stations: str = "radio_stations.yml"
    playlists: str = "playlists/playlists"

    def __init__(self):
        # these should be relative to data folder
        for key in ("certificates", "radio_stations", "playlists"):
            path = Path(getattr(self, key))
            if not path.root:
                # noinspection PyUnresolvedReferences
                path = self.data / path
            setattr(self, key, str(path))


class Misc(ConfigObject):
    idle_game: str = "Waiting for someone to queue something..."
    image_cx: str = "002017775112634544492:t0ynfpg8y0e"


class Application(ConfigObject):
    tokens: Tokens
    redis: Redis
    mongodb: Mongodb
    lavalink: Lavalink
    webiesela: Webiesela
    files: Files
    misc: Misc
    guild_defaults: Guild
