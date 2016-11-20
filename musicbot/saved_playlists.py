import os
import shutil
import traceback
import configparser

from .exceptions import HelpfulError


class Playlists:
    def __init__(self, playlists_file):
        self.playlists_file = playlists_file
        self.update_playlist ()
        self.playlist_save_location = "data/playlists/"

    def update_playlist (self):
        self.playlists = configparser.ConfigParser()

        if not self.playlists.read(self.playlists_file, encoding='utf-8'):
            print('[playlists] Playlists file not found')
            raise HelpfulError(
                "Your playlists file is missing"
            )

        self.playlists = configparser.ConfigParser(interpolation=None)
        self.playlists.read (self.playlists_file, encoding='utf-8')
        self.saved_playlists = self.playlists.sections ()

    def save_playlist (self):
        with open (self.playlists_file, "w") as pl_file:
            self.playlists.write (pl_file)

    def get_playlist (self, playlistname):
        if not self.playlists.has_section (playlistname):
            return None

        plsection = self.playlists [playlistname]

        playlist_informations = ***REMOVED******REMOVED***
        playlist_informations ["location"] = plsection ["location"]
        playlist_informations ["author"] = plsection ["author"]
        playlist_informations ["entry_count"] = plsection ["entries"]
        with open (playlist_informations ["location"], "r") as file:
            entries = file.read ().splitlines ()

        playlist_informations ["entries"] = entries

        return playlist_informations

    def set_playlist (self, entries, name, author_id):
        try:
            with open (self.playlist_save_location + str (name) + ".txt", "w") as f:
                for entry in entries:
                    f.write (entry + "\n")
        except Exception as e:
            raise ValueError (str (e))
            return False

        self.playlists.add_section (name)
        self.playlists.set (name, "location", self.playlist_save_location + str (name) + ".txt")
        self.playlists.set (name, "author", str (author_id))
        self.playlists.set (name, "entries", str (len (entries)))

        self.save_playlist ()
        self.update_playlist ()
        return True

    def remove_playlist (self, name):
        os.remove (self.playlists [name] ["location"])
        self.playlists.remove_section (name)
        self.save_playlist ()
        self.update_playlist ()
