import json
import os
import random
import re
import time
from io import BytesIO

from musicbot import mosaic
from musicbot.entry import Entry, SpotifyEntry
from musicbot.exceptions import BrokenEntryError, OutdatedEntryError
from musicbot.imgur import _upload_playlist_cover
from musicbot.utils import format_time, similarity
from musicbot.web_author import WebAuthor


class Playlists:

    def __init__(self, playlists_file):
        self.playlists_file = playlists_file
        self.update_playlists()
        self.playlist_save_location = "data/playlists/"

        self._web_playlists_dirty = False
        self._cached_web_playlists = None

    def update_playlists(self):
        with open(self.playlists_file, "r+") as f:
            self.playlists = json.load(f)

    def save_playlists(self):
        self._web_playlists_dirty = True

        with open(self.playlists_file, "w+") as f:
            json.dump(self.playlists, f, indent=4)

    def get_all_web_playlists(self, queue):
        if self._web_playlists_dirty or not self._cached_web_playlists:
            self._cached_web_playlists = sorted([self.get_web_playlist(name, queue) for name, data in self.playlists.items() if data.get("cover_url")], key=lambda playlist: playlist["name"])
            self._web_playlists_dirty = False
            print("[playlists] updated cached web playlists")
        else:
            print("[playlists] using cached web playlists")

        return self._cached_web_playlists

    def get_web_playlist(self, playlist_id, queue):
        data = self.get_playlist(playlist_id, queue)

        duration = sum(entry.duration for entry in data["entries"])

        playlist_info = {
            "name":         data["name"],
            "id":           data["id"],
            "cover":        data["cover_url"],
            "description":  data["description"],
            "author":       data["author"].to_dict(),
            "replay_count": data["replay_count"],
            "entries":      [entry.to_web_dict(skip_calc=True) for entry in data["entries"]],
            "duration":     duration,
            "human_dur":    format_time(duration, max_specifications=1)
        }

        return playlist_info

    def get_playlist(self, playlist_id, queue, load_entries=True, channel=None):
        if playlist_id not in self.playlists:
            return None

        plsection = self.playlists[playlist_id]

        playlist_author = plsection["author"]

        if isinstance(playlist_author, dict):
            playlist_author = WebAuthor.from_dict(playlist_author)
        else:
            playlist_author = WebAuthor.from_id(playlist_author)

        playlist_information = {
            "id":           playlist_id,
            "name":         plsection.get("name", False) or playlist_id.title().replace("_", " "),
            "location":     plsection["location"],
            "author":       playlist_author,
            "replay_count": int(plsection["replays"]),
            "description":  plsection.get("description"),
            "cover_url":    plsection.get("cover_url")
        }

        entries = []
        # this is gonna be a list of serialised entries populated with the broken or outdated
        # entries
        broken_entries = []
        if load_entries and not os.stat(playlist_information["location"]).st_size == 0:
            with open(playlist_information["location"], "r") as f:
                serialized_json = json.loads(f.read())

            for ind, ser_entry in enumerate(serialized_json):
                try:
                    entry = Entry.from_dict(queue, ser_entry)
                    entry.meta["channel"] = channel
                except (BrokenEntryError, OutdatedEntryError, TypeError, KeyError):
                    entry = None

                if not entry:
                    broken_entries.append(ser_entry)
                else:
                    entries.append(entry)

        playlist_information["entries"] = entries
        playlist_information["broken_entries"] = broken_entries

        return playlist_information

    def set_playlist(self, playlist_id, entries, name, author, description=None, cover_url=None, replays=0):
        if not cover_url:
            covers = [entry.cover for entry in entries if isinstance(entry, SpotifyEntry)]

            if len(covers) >= 3:
                print("[Playlists] no cover provided, generating one for", playlist_id)

                image_amount = min(random.choice((3, 4, 5, 6, 7, 8, 9)), len(covers))

                covers_to_use = random.sample(covers, image_amount)

                images = mosaic.grab_images(*covers_to_use)
                print("[Playlist] downloaded", image_amount, "images")

                cover_image = mosaic.create_random_cover(*images)

                print("[Playlists] generated mosaic, uploading to Imgur")

                image_file = BytesIO()
                cover_image.save(image_file, format="PNG")
                image_file.seek(0)

                cover_url = _upload_playlist_cover(playlist_id, image_file)
                print("[Playlists] Uploaded Cover to Imgur")
            else:
                print("[Playlists] not enough covers to generate a cover for", playlist_id)

        serialized_entries = []
        for index, entry in enumerate(sorted(entries, key=lambda entry: entry.sortby)):
            added_timestamp = entry.meta.get("playlist", {}).get("timestamp", round(time.time()))

            entry.meta["playlist"] = {
                "cover": cover_url,
                "name": name,
                "id": playlist_id,
                "index": index,
                "timestamp": added_timestamp
            }

            serialized_entries.append(entry.to_dict())

        json.dump(serialized_entries, open("{}{}.gpl".format(self.playlist_save_location, playlist_id), "w+"), indent=4)

        playlist_data = self.playlists.get(playlist_id, {})

        if not isinstance(author, WebAuthor):
            author = WebAuthor.from_id(author)

        playlist_data.update({
            "location": "{}{}.gpl".format(self.playlist_save_location, playlist_id),
            "author": author.to_dict(),
            "replays": replays,
            "description": description,
            "cover_url": cover_url,
            "name": name
        })

        self.playlists[playlist_id] = playlist_data

        self.save_playlists()
        return True

    def bump_replay_count(self, playlist_id):
        if playlist_id in self.playlists:
            prev_count = self.playlists[playlist_id].get("replays", 0)

            self.playlists[playlist_id].update(replays=prev_count + 1)
            self.save_playlists()
            return True

        return False

    def in_playlist(self, queue, playlist_id, query, certainty_threshold=.6):
        results = self.search_entries_in_playlist(
            queue, playlist_id, query
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

    def remove_playlist(self, playlist_id):
        if playlist_id in self.playlists:
            os.remove(self.playlists[playlist_id]["location"])
            self.playlists.pop(playlist_id)
            self.save_playlists()

    def edit_playlist(self, playlist_id, queue, all_entries=None, remove_entries=None, remove_entries_indexes=None, new_entries=None, new_name=None, new_description=None, new_cover=None, edit_entries=None):
        old_playlist = self.get_playlist(playlist_id, queue)

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

            if edit_entries:
                for old, new in edit_entries:
                    if all((new, old)) and old != new:
                        index = next(ind for ind, entry in enumerate(next_entries) if entry.url == old.url)
                        next_entries.pop(index)
                        next_entries.insert(index, new)

        next_name = new_name or old_playlist.get("name", playlist_id.title())
        next_author = old_playlist["author"]
        next_description = new_description or old_playlist["description"]
        next_cover = new_cover or old_playlist["cover_url"]

        if len(next_entries) < 1:
            self.remove_playlist(playlist_id)
            return

        self.set_playlist(playlist_id, next_entries, next_name, next_author, next_description,
                          next_cover, replays=old_playlist["replay_count"])

    async def mark_entry_broken(self, queue, playlist_id, entry):
        playlist = self.get_playlist(playlist_id, queue)

        entries = playlist["entries"]

        index = next(ind for ind, e in enumerate(entries) if e.url == entry.url)

        with open(playlist["location"], "r") as f:
            serialized_entries = json.load(f)

        serialized_entries[index]["broken"] = True

        with open(playlist["location"], "w") as f:
            json.dump(serialized_entries, f, indent=4)

        print("marked {} from {} as broken".format(entry.title, playlist_name))
