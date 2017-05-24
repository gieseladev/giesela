import re
from difflib import SequenceMatcher

import spotipy

spotify = spotipy.Spotify()


class SpotifyArtist:

    def __init__(self, id, name, images, popularity, genres, uri):
        self.id = id
        self.name = name
        self.images = images
        self.popularity = popularity
        self.genres = genres
        self.uri = uri

    @classmethod
    def from_data(cls, data):
        artist_id = data["id"]

        data = spotify.artist("spotify:artist:" + artist_id)
        return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"])

    @classmethod
    def from_dict(cls, data):
        return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"])

    def __str__(self):
        return "Artist \"***REMOVED***0.name***REMOVED***\" [***REMOVED***0.popularity***REMOVED***]".format(self)

    def get_dict(self):
        data = ***REMOVED***
            "id": self.id,
            "name": self.name,
            "images": self.images,
            "genres": self.genres,
            "popularity": self.popularity,
            "uri": self.uri
        ***REMOVED***
        return data


class SpotifyAlbum:

    def __init__(self, id, name, artists, images, uri):
        self.id = id
        self.name = name
        self.artists = artists
        self.images = images
        self.uri = uri

    @classmethod
    def from_data(cls, data):
        return cls(data["id"], data["name"], [SpotifyArtist.from_data(artist) for artist in data["artists"]], data["images"], data["uri"])

    @classmethod
    def from_dict(cls, data):
        return cls(data["id"], data["name"], [SpotifyArtist.from_dict(artist) for artist in data["artists"]], data["duration"], data["images"], data["uri"])

    def __str__(self):
        return "Album \"***REMOVED***0.name***REMOVED***\" by ***REMOVED***0.artists***REMOVED***".format(self)

    def get_dict(self):
        data = ***REMOVED***
            "id": self.id,
            "name": self.name,
            "artists": [artist.get_dict() for artist in self.artists],
            "images": self.images,
            "uri": self.uri
        ***REMOVED***
        return data


class SpotifyTrack:

    def __init__(self, id, name, artists, duration, album, popularity, uri, query=None, certainty=1):
        self.id = id
        self.name = name
        self.artists = artists
        self.duration = duration
        self.album = album
        self.popularity = popularity
        self.uri = uri
        self.query = query
        self.certainty = certainty

    @classmethod
    def EmptyTrack(cls, query):
        return cls(None, query, None, None, None, None, None, certainty=0)

    @classmethod
    def from_query(cls, query):
        query = parse_query(query)

        search_result = spotify.search(query, limit=1, type="track")
        if len(search_result) < 1 or len(search_result["tracks"]["items"]) < 1:
            return SpotifyTrack.EmptyTrack(query)

        track = search_result["tracks"]["items"][0]
        album = SpotifyAlbum.from_data(track["album"])

        artists = [SpotifyArtist.from_data(artist)
                   for artist in track["artists"]]

        cer = get_certainty(query, track["name"], artists)

        return cls(track["id"], track["name"], artists, track["duration_ms"] / 1000, album, track["popularity"], track["uri"], query, cer)

    @classmethod
    def from_dict(cls, data):
        if data is None:
            return None

        return cls(data["id"], data["name"], [SpotifyArtist.from_dict(artist) for artist in data["artists"]], data["duration"], SpotifyAlbum.from_dict(data["album"]), data["popularity"], data["uri"], data["query"], data["certainty"])

    @property
    def cover_url(self):
        return self.album.images[0]["url"]

    @property
    def artist(self):
        return ", ".join(artist.name for artist in self.artists)

    def get_dict(self):
        data = ***REMOVED***
            "id": self.id,
            "name": self.name,
            "artists": [artist.get_dict() for artist in self.artists],
            "duration": self.duration,
            "album": self.album.get_dict(),
            "popularity": self.popularity,
            "uri": self.uri,
            "query": self.query,
            "certainty": self.certainty
        ***REMOVED***
        return data


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_certainty(query, song_name, artists):
    song_name_edited = re.sub(
        "\***REMOVED***0[0]***REMOVED***.+\***REMOVED***0[1]***REMOVED***".format("()"), "", song_name)

    index = song_name_edited.find("-")
    song_name_edited = song_name_edited[
        :index if index > 3 else len(song_name_edited)]
    song_name_edited = song_name_edited.strip()

    poss = []
    poss.append(similar(query.lower(), "***REMOVED***0***REMOVED*** ***REMOVED***1***REMOVED***".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "***REMOVED***1***REMOVED*** ***REMOVED***0***REMOVED***".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "***REMOVED***0***REMOVED*** \n ***REMOVED***1***REMOVED***".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "***REMOVED***1***REMOVED*** \n ***REMOVED***0***REMOVED***".format(
        song_name_edited.lower(), artists[0].name.lower())))

    return max(poss)


def parse_query(query):
    for chr in ["()", "[]", "<>"]:
        query = re.sub("\***REMOVED***0[0]***REMOVED***.+\***REMOVED***0[1]***REMOVED***".format(chr), "", query)

    query = re.sub("'", "", query)

    query = query.replace("|", " ", 1)

    query = query.replace(":", "")
    query = query.replace(" OST ", "")
    query = query.replace(" ost ", "")
    query = query.replace(" Ost ", "")
    query = re.sub("\d+", "", query)

    index = query.lower().find(" download ")
    query = query[:index if index > 3 else len(query)]

    index = query.lower().find(" and ")
    query = query[:index if index > 3 else len(query)]

    index = query.lower().find(" ft ") if query.lower().find(
        " ft ") > 0 else query.lower().find(" ft.")
    dash = query.find("-")
    if dash == -1 and index > 0:
        query = query[index + 1 if index > 0 else 0:]
    elif index > 0:
        query = query[:index + 1 if index > 0 else len(query)] + query[dash:]

    index = query.lower().find(" feat ")
    query = query[:index if index > 3 else len(query)]

    index = query.lower().find(" lyric")
    query = query[:index if index > 3 else len(query)]

    index = query.lower().find(" official")
    query = query[:index if index > 3 else len(query)]

    index = query.lower().find("&") if query.lower().find(
        "&") != -1 else query.lower().find(" x ")
    dash = query.find("-")
    if dash == -1 and index > 0:
        query = query[index + 1 if index > 0 else 0:]
    elif index > 0:
        query = query[:index if index > 0 else len(query)] + query[dash:]

    query = query.replace("-", "\n", 1)
    index = query.find(" - ")
    query = query[:index if index > 3 else len(query)]
    query = query.strip()
    query = re.sub(" ***REMOVED***2,***REMOVED***", " ", query)

    return query
