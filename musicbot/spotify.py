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

    def __str__(self):
        return "Artist \"{0.name}\" [{0.popularity}]".format(self)


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

    def __str__(self):
        return "Album \"{0.name}\" by {0.artists}".format(self)


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

    @property
    def cover_url(self):
        return self.album.images[0]["url"]

    @property
    def artist(self):
        return ", ".join(artist.name for artist in self.artists)


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_certainty(query, song_name, artists):
    song_name_edited = re.sub(
        "\{0[0]}.+\{0[1]}".format("()"), "", song_name)

    index = song_name_edited.find("-")
    song_name_edited = song_name_edited[
        :index if index > 3 else len(song_name_edited)]
    song_name_edited = song_name_edited.strip()

    poss = []
    poss.append(similar(query.lower(), "{0} {1}".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "{1} {0}".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "{0} \n {1}".format(
        song_name_edited.lower(), artists[0].name.lower())))
    poss.append(similar(query.lower(), "{1} \n {0}".format(
        song_name_edited.lower(), artists[0].name.lower())))

    return max(poss)


def parse_query(query):
    for chr in ["()", "[]", "<>"]:
        query = re.sub("\{0[0]}.+\{0[1]}".format(chr), "", query)

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
    query = re.sub(" {2,}", " ", query)

    return query
