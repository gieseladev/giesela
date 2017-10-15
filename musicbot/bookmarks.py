import json
import re
from random import randint

from musicbot.utils import clean_songname, similarity
from musicbot.web_author import WebAuthor


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
    gp_version = 2

    def __init__(self):
        self.loaded = False
        self.version = 0
        self.bookmarks = ***REMOVED******REMOVED***

    @ensure_loaded
    def __contains__(self, key):
        return key in self.bookmarks

    @property
    @ensure_loaded
    def all_bookmarks(self):
        return self.bookmarks.values()

    @ensure_loaded
    def save(self):
        save_data = ***REMOVED***
            "version": hex(self.version + 1)[2:],
            "gp_version": hex(Bookmarks.gp_version)[2:],
            "bookmarks": self.bookmarks
        ***REMOVED***
        json.dump(save_data, open("data/bookmarks.gb", "w+"), indent=2)

    def load(self):
        try:
            saved_data = json.load(open("data/bookmarks.gb", "r+"))

            if int(saved_data.get("gp_version", "0"), 16) < Bookmarks.gp_version:
                print("[Bookmarks] Can't load the bookmarks, they're outdated")
                self.version = 0
                self.bookmarks = ***REMOVED******REMOVED***
                self.loaded = True
            else:
                self.version = int(saved_data["version"], 16)
                self.bookmarks = saved_data["bookmarks"]
                self.loaded = True
        except:
            pass

    @ensure_loaded
    def get_id(self):
        while True:
            _id = hex(randint(0x100, 0xFFFF))[2:]
            if _id not in self.bookmarks:
                return _id

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
    def add_bookmark(self, entry, timestamp, author, bookmark_name=None):
        if isinstance(author, str):
            author = WebAuthor.from_id(author)

        bookmark_id = self.get_id()
        bookmark_name = bookmark_name if bookmark_name else clean_songname(entry.title)
        entry_data = entry.to_dict()

        data = ***REMOVED***
            "id": bookmark_id,
            "name": bookmark_name,
            "entry": entry_data,
            "timestamp": timestamp,
            "author": author.to_dict()
        ***REMOVED***

        self.bookmarks[bookmark_id] = data

        return bookmark_id

    @ensure_loaded
    @ensure_saving
    def edit_bookmark(self, id, new_name=None, new_timestamp=None):
        if id not in self.bookmarks:
            return False

        data = self.bookmarks[id]  # grab previous data

        new_data = ***REMOVED******REMOVED***
        if new_name:
            new_data["name"] = new_name
        if new_timestamp is not None:  # again, 0=False thus I need to check it this way
            new_data["timestamp"] = new_timestamp

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
