import os
import shutil
import traceback
import configparser
import re

from .entry import URLPlaylistEntry as urlEntry

from .exceptions import HelpfulError


class Playlists:

    def __init__(self, playlists_file):
        self.playlists_file = playlists_file
        self.update_playlist()
        self.playlist_save_location = "data/playlists/"

    def update_playlist(self):
        self.playlists = configparser.ConfigParser()

        if not self.playlists.read(self.playlists_file, encoding='utf-8'):
            print('[playlists] Playlists file not found')
            raise HelpfulError(
                "Your playlists file is missing"
            )

        self.playlists = configparser.ConfigParser(interpolation=None)
        self.playlists.read(self.playlists_file, encoding='utf-8')
        self.saved_playlists = self.playlists.sections()

    def save_playlist(self):
        with open(self.playlists_file, "w") as pl_file:
            self.playlists.write(pl_file)

    def get_playlist(self, playlistname, playlist):
        if not self.playlists.has_section(playlistname):
            return None

        plsection = self.playlists[playlistname]

        playlist_informations = {}
        playlist_informations["location"] = plsection["location"]
        playlist_informations["author"] = plsection["author"]
        playlist_informations["entry_count"] = plsection["entries"]
        entries = []
        if not os.stat(playlist_informations["location"]).st_size == 0:
            with open(playlist_informations["location"], "r") as file:
                serialized_json = re.split("\n;\n", file.read())
            for entry in serialized_json:
                #print (str (urlEntry.entry_from_json (playlist, entry).title))
                entries.append(urlEntry.entry_from_json(playlist, entry))

        playlist_informations["entries"] = entries

        return playlist_informations

    def set_playlist(self, entries, name, author_id):
        try:
            with open(self.playlist_save_location + str(name) + ".txt", "w") as f:
                f.write("\n;\n".join([entry.to_json() for entry in entries]))
        except Exception as e:
            raise ValueError(str(e))
            return False

        if not self.playlists.has_section(name):
            self.playlists.add_section(name)
        self.playlists.set(
            name, "location", self.playlist_save_location + str(name) + ".txt")
        self.playlists.set(name, "author", str(author_id))
        self.playlists.set(name, "entries", str(len(entries)))

        self.save_playlist()
        self.update_playlist()
        return True

    def remove_playlist(self, name):
        os.remove(self.playlists[name]["location"])
        self.playlists.remove_section(name)
        self.save_playlist()
        self.update_playlist()

    def edit_playlist(self, name, playlist, remove_entries=None, remove_entries_indexes=None, new_entries=None, new_name=None):
        old_playlist = self.get_playlist(name, playlist)
        old_entries = old_playlist[
            "entries"] if old_playlist is not None else []

        if remove_entries_indexes is not None:
            old_entries = [old_entries[x] for x in range(
                len(old_entries)) if x not in remove_entries_indexes]

        if remove_entries is not None:
            urls = [x.url for x in remove_entries]
            for entry in old_entries:
                if entry.url in urls:
                    old_entries.remove(entry)

        if new_entries is not None:
            try:
                old_entries.extend(new_entries)
            except:
                print("I guess something went wrong while extending the playlist...")

        #print (str (old_entries))
        next_entries = old_entries
        next_name = new_name if new_name is not None else name
        next_author_id = old_playlist["author"]

        if len(next_entries) < 1:
            self.remove_playlist(name)
            return

        if next_name != name:
            self.remove_playlist(name)

        self.set_playlist(next_entries, next_name, next_author_id)
