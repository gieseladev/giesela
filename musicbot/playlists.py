import json
import os

from musicbot.config import static_config
from musicbot.entry import Entry
from musicbot.lib.serialisable import Serialisable, WebSerialisable
from musicbot.web_author import WebAuthor


class PlaylistStats(Serialisable, WebSerialisable):

    def __init__(self, loaded):
        self.loaded = loaded


class Playlist(Serialisable, WebSerialisable):

    def __init__(self, _id, name, description, cover, author, serialised_entries, stats):
        self.id = _id
        self.name = name
        self.description = description
        self.cover = cover
        self.author = author
        self.serialised_entries = serialised_entries
        self.stats = stats

        self._dirty = True
        self._serialised_data = None

    @classmethod
    def from_dict(cls, data):
        kwargs = data

        kwargs["author"] = WebAuthor.from_dict(data["author"]).discord_user
        kwargs["stats"] = PlaylistStats.from_dict(data["stats"])

        return cls(**kwargs)

    def get_entries(self, queue):
        return [Entry.from_dict(queue, serialised_entry) for serialised_entry in self.serialised_entries]

    async def generate_cover(self):
        pass

    def to_dict(self):
        if self._dirty or self._serialised_data is None:
            self._serialised_data = {
                "id":                   self.id,
                "name":                 self.name,
                "description":          self.description,
                "cover":                self.cover,
                "author":               WebAuthor.from_user(self.author).to_dict(),
                "serialised_entries":   self.serialised_entries,
                "stats":                self.stats.to_dict()
            }

            self._dirty = False

        return self._serialised_data

    def to_web_dict(self):
        pass


class Playlists:
    playlist_path = os.path.join(os.getcwd(), static_config.playlists_location)
    playlists = []

    @staticmethod
    def load():
        if not os.path.isdir(Playlists.playlist_path):
            os.mkdir(Playlists.playlist_path)

        playlist_files = [os.path.join(Playlists.playlist_path, path) for path in os.listdir(Playlists.playlist_path)]

        for playlist_file in playlist_files:
            try:
                with open(playlist_file, "r") as f:
                    data = json.load(f)
                    Playlists.playlists.append(Playlist.from_dict(data))
            except OSError:
                print("[Playlists] Couldn't open:", playlist_file)
            except json.JSONDecodeError:
                print("[Playlists] Couldn't decode:", playlist_file)
            except KeyError:
                print("[Playlist] Wrong format", playlist_file)
