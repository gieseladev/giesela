import json
import re
from random import randint

from .utils import similarity


def ensure_saving(func):
    def inner(self, *args, **kwargs):
        res = func(self, *args, **kwargs)
        self.save()
        return res

    return inner


def ensure_loaded(func):
    def inner(self, *args, **kwargs):
        if not self.loaded:
            self.load()

        return func(self, *args, **kwargs)
    return inner


class Bookmarks:

    def __init__(self):
        self.loaded = False
        self.version = 0
        self.bookmarks = {}

    @ensure_loaded
    def __contains__(self, key):
        return key in self.bookmarks

    @property
    @ensure_loaded
    def all_bookmarks(self):
        return self.bookmarks.values()

    @ensure_loaded
    def save(self):
        save_data = {
            "version": str(hex(self.version + 1)[2:]),
            "bookmarks": self.bookmarks
        }
        json.dump(save_data, open("data/bookmarks.gb", "w+"), indent=2)

    def load(self):
        try:
            saved_data = json.load(open("data/bookmarks.gb", "r+"))
            self.version = int(saved_data["version"], 16)
            self.bookmarks = saved_data["bookmarks"]
            self.loaded = True
        except:
            pass

    @ensure_loaded
    def get_id(self):
        while True:
            id = str(hex(randint(0, 100000)))[2:]
            if id not in self.bookmarks:
                return id

    @ensure_loaded
    def search_bookmarks(self, query, min_certainty=0):
        poss = []
        for bm in self.bookmarks:
            bookmark = self.bookmarks[bm]
            s = similarity(bookmark["name"].lower(), query)
            if s > min_certainty:
                poss.append((s, bookmark))

        if not poss:
            return None

        return list(zip(*sorted(poss, key=lambda e: e[0], reverse=True)))[1]

    @ensure_loaded
    def get_bookmark(self, query):
        query = re.sub(r"\W", "", query.lower())

        if query in self.bookmarks:
            return self.bookmarks[query]

        search_results = self.search_bookmarks(query, .8)
        if not search_results:
            return False
        return search_results[0]

    @ensure_loaded
    @ensure_saving
    def add_bookmark(self, entry, timestamp, author_id, bookmark_name=None):
        # if type(entry).__name__ != "URLPlaylistEntry":
        #     # raise TypeError("Can only bookmark URLPlaylistEntries")
        #     return False

        bookmark_id = self.get_id()
        bookmark_name = bookmark_name if bookmark_name else entry.title
        entry_data = entry.to_dict()
        entry_data["start_seconds"] = timestamp

        data = {
            "id": bookmark_id,
            "name": bookmark_name,
            "entry": entry_data,
            "timestamp": timestamp,
            "author_id": author_id
        }
        self.bookmarks[bookmark_id] = data

        return bookmark_id

    @ensure_loaded
    @ensure_saving
    def edit_bookmark(self, id, new_name=None, new_timestamp=None):
        if id not in self.bookmarks:
            return False

        data = self.bookmarks[id]  # grab previous data

        new_data = {}
        if new_name:
            new_data["name"] = new_name
        if new_timestamp:
            new_data["timestamp"] = new_timestamp
            data["entry"]["start_seconds"] = new_timestamp

        data.update(new_data)  # override the values with the new ones

        self.bookmarks[id] = data  # save it
        return True

    @ensure_loaded
    @ensure_saving
    def remove_bookmark(self, id):
        if id not in self.bookmarks:
            return False

        return self.bookmarks.pop(id)

bookmark = Bookmarks()
# bookmark_singleton = Bookmarks()
#
# print(bookmark_singleton.add_bookmark(
# type("URLPlaylistEntry", (object,), {"title": "test_title",
# "start_seconds": 0, "to_dict": lambda: []}), None, None, "test"))
