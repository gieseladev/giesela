import json
import os
import re
import shutil
import traceback

import configparser

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

    def get_playlist(self, playlistname, playlist, channel=None, author=None, load_entries=True):
        playlistname = playlistname.lower().strip().replace(" ", "_")
        if not self.playlists.has_section(playlistname):
            return None

        plsection = self.playlists[playlistname]

        playlist_information = {}
        playlist_information["location"] = plsection["location"]
        playlist_information["author"] = plsection["author"]
        playlist_information["entry_count"] = plsection["entries"]
        playlist_information["replay_count"] = self.playlists.getint(
            playlistname, "replays", fallback=0)
        entries = []
        if load_entries and not os.stat(playlist_information["location"]).st_size == 0:
            with open(playlist_information["location"], "r") as file:
                serialized_json = json.loads(file.read())
            for entry in serialized_json:
                #print (str (urlEntry.entry_from_json (playlist, entry).title))
                if channel and author is not None:
                    entry.update({"meta":
                                  {"channel": {"type": "channel", "name": channel.name, "id": channel.id},
                                   "author": {"type": "author", "name": author.name, "id": author.id},
                                   "playlist": {"name": playlistname, "author": playlist_information["author"]}}})
                entries.append(urlEntry.from_dict(playlist, entry, False))

        playlist_information["entries"] = entries

        return playlist_information

    def set_playlist(self, entries, name, author_id, replays=0):
        name = name.lower().strip().replace(" ", "_")

        try:
            with open(self.playlist_save_location + str(name) + ".gpl", "w") as f:
                f.write(json.dumps([entry.to_dict() for entry in entries]))
        except Exception as e:
            raise
            return False

        if not self.playlists.has_section(name):
            self.playlists.add_section(name)
        self.playlists.set(
            name, "location", self.playlist_save_location + str(name) + ".gpl")
        self.playlists.set(name, "author", str(author_id))
        self.playlists.set(name, "entries", str(len(entries)))
        self.playlists.set(name, "replays", str(replays))

        self.save_playlist()
        self.update_playlist()
        return True

    def bump_replay_count(self, playlist_name):
        playlist_name = playlist_name.lower().strip().replace(" ", "_")

        if self.playlists.has_section(playlist_name):
            prevCount = 0
            if(self.playlists.has_option(playlist_name, "replays")):
                prevCount = int(self.playlists.get(playlist_name, "replays"))

            self.playlists.set(playlist_name, "replays", str(prevCount + 1))
            self.save_playlist()
            return True

        return False

    def remove_playlist(self, name):
        name = name.lower().strip().replace(" ", "_")

        os.remove(self.playlists[name]["location"])
        self.playlists.remove_section(name)
        self.save_playlist()
        self.update_playlist()

    def get_all_playlists(self, playlist):
        pls = []
        for pl in self.saved_playlists:
            pls.append((pl, self.get_playlist(pl, playlist, False)))

        return pls

    def edit_playlist(self, name, playlist, remove_entries=None, remove_entries_indexes=None, new_entries=None, new_name=None):
        name = name.lower().strip().replace(" ", "_")
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

        self.set_playlist(next_entries, next_name,
                          next_author_id, old_playlist["replay_count"])
