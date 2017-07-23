import json
import os
import re

import configparser

from .entry import Entry
from .exceptions import OutdatedEntryError
from .utils import clean_songname, similarity


class Playlists:

    def __init__(self, playlists_file):
        self.playlists_file = playlists_file
        self.update_playlist()
        self.playlist_save_location = "data/playlists/"

    def update_playlist(self):
        self.playlists = configparser.ConfigParser()

        if not self.playlists.read(self.playlists_file, encoding="utf-8"):
            print("[playlists] Playlists file not found")
            raise HelpfulError(
                "Your playlists file is missing"
            )

        self.playlists = configparser.ConfigParser(interpolation=None)
        self.playlists.read(self.playlists_file, encoding="utf-8")
        self.saved_playlists = self.playlists.sections()

    def save_playlist(self):
        with open(self.playlists_file, "w") as pl_file:
            self.playlists.write(pl_file)

    def get_playlist(self, playlistname, playlist, load_entries=True, channel=None):
        playlistname = playlistname.lower().strip().replace(" ", "_")
        if not self.playlists.has_section(playlistname):
            return None

        plsection = self.playlists[playlistname]

        playlist_information = {
            "id": playlistname,
            "name": playlistname.replace("_", " ").title(),
            "location": plsection["location"],
            "author": plsection["author"],
            "replay_count": int(plsection["replays"]),
            "description": None if plsection.get("description") == "None" else plsection.get("description"),
            "cover_url": None if plsection.get("cover_url") == "None" else plsection.get("cover_url")
        }

        entries = []
        # this is gonna be a list of urls populated with the broken or outdated
        # entries
        broken_entries = []
        if load_entries and not os.stat(playlist_information["location"]).st_size == 0:
            with open(playlist_information["location"], "r") as file:
                serialized_json = json.loads(file.read())
            for ind, ser_entry in enumerate(serialized_json):
                try:
                    entry = Entry.from_dict(playlist, ser_entry)
                    entry.meta.pop("channel", None)
                    entry.meta["channel"] = channel
                    entry.meta["playlist"] = {
                        "name": playlistname,
                        "index": ind
                    }
                except (OutdatedEntryError, TypeError, KeyError):
                    entry = None

                if not entry:
                    broken_entries.append(ser_entry)
                else:
                    entries.append(entry)

        playlist_information["entries"] = entries
        playlist_information["broken_entries"] = broken_entries

        return playlist_information

    def set_playlist(self, entries, name, author_id, description=None, cover_url=None, replays=0):
        name = name.lower().strip().replace(" ", "_")

        try:
            serialized_entries = []
            for index, entry in enumerate(entries):
                entry.start_seconds = 0

                entry.meta["playlist"] = {
                    "name": name,
                    "index": index
                }

                serialized_entries.append(entry.to_dict())

            with open(self.playlist_save_location + str(name) + ".gpl", "w") as f:
                f.write(json.dumps(serialized_entries, indent="\t"))
        except Exception as e:
            raise
            return False

        if not self.playlists.has_section(name):
            self.playlists.add_section(name)

        self.playlists.set(
            name, "location", self.playlist_save_location + str(name) + ".gpl")
        self.playlists.set(name, "author", str(author_id))
        self.playlists.set(name, "replays", str(replays))
        self.playlists.set(name, "description", str(description))
        self.playlists.set(name, "cover_url", str(cover_url))

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

    def in_playlist(self, queue, playlist, query, certainty_threshold=.6):
        results = self.search_entries_in_playlist(
            queue, playlist, query
        )
        result = results[0]
        if result[0] > certainty_threshold:
            return result[1]
        else:
            return False

    def search_entries_in_playlist(self, queue, playlist, query, certainty_threshold=None):
        if isinstance(playlist, str):
            playlist = self.get_playlist(playlist, queue)

        if isinstance(query, str):
            query_title = query_url = query
        else:
            query_title = query.title
            query_url = query.url

        entries = playlist["entries"]

        def get_similarity(entry):
            s1 = similarity(query_title, entry.title)
            s2 = 1 if query_url == entry.url else 0

            words_in_query = [re.sub(r"\W", "", w)
                              for w in query_title.lower().split()]
            words_in_query = [w for w in words_in_query if w]

            words_in_title = [re.sub(r"\W", "", w)
                              for w in entry.title.lower().split()]
            words_in_title = [w for w in words_in_title if w]

            s3 = sum(len(w) for w in words_in_query if w in entry.title.lower(
            )) / len(re.sub(r"\W", "", query_title))
            s4 = sum(len(w) for w in words_in_title if w in query_title.lower(
            )) / len(re.sub(r"\W", "", entry.title))
            s5 = (s3 + s4) / 2

            return max(s1, s2, s5)

        matched_entries = [(get_similarity(entry), entry) for entry in entries]
        if certainty_threshold:
            matched_entries = [
                el for el in matched_entries if el[0] > certainty_threshold]
        ranked_entries = sorted(
            matched_entries,
            key=lambda el: el[0],
            reverse=True
        )

        return ranked_entries

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

    def edit_playlist(self, name, playlist, all_entries=None, remove_entries=None, remove_entries_indexes=None, new_entries=None, new_name=None, new_description=None, new_cover=None):
        name = name.lower().strip().replace(" ", "_")
        old_playlist = self.get_playlist(name, playlist)

        if all_entries:
            next_entries = all_entries
        else:
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
                old_entries.extend(new_entries)
            next_entries = old_entries

        next_name = new_name if new_name is not None else name
        next_author_id = old_playlist["author"]
        next_description = new_description or old_playlist["description"]
        next_cover = new_cover or old_playlist["cover_url"]

        if len(next_entries) < 1:
            self.remove_playlist(name)
            return

        if next_name != name:
            self.remove_playlist(name)

        self.set_playlist(next_entries, next_name, next_author_id, next_description,
                          next_cover, replays=old_playlist["replay_count"])
