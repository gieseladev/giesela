import os
import shutil
import traceback
import configparser

from .exceptions import HelpfulError


class Playlists:
    def __init__(self, playlists_file):
        self.playlists_file = playlists_file
        self.update_playlist ()

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

    def get_playlist (self, playlistname):
        if not self.playlists.has_section (playlistname):
            return None

        plsection = self.playlists [playlistname]

        playlist_informations = {}
        playlist_informations ["location"] = plsection ["location"]
        playlist_informations ["author"] = plsection ["author"]
        playlist_informations ["entry_count"] = plsection ["entries"]
        with open (playlist_informations ["location"], "r") as file:
            entries = file.read ().splitlines ()

        playlist_informations ["entries"] = entries

        return playlist_informations
