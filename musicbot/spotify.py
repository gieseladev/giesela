import re
from random import choice

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from .utils import similarity

cred = SpotifyClientCredentials(
    "df9e44098b934c028ea085227c3ec3f6", "f9d02852fb1a4dacaa50d14e915c5d0e")


def get_spotify_client():
    return spotipy.Spotify(auth=cred.get_access_token())


class SpotifyArtist:

    def __init__(self, id, name, images, popularity, genres, uri, href, top_tracks=None):
        self.id = id
        self.name = name
        self.images = images
        self.popularity = popularity
        self.genres = genres
        self.uri = uri
        self.href = href
        self._top_tracks = top_tracks

    @property
    def image(self):
        return choice(self.images)["url"] if self.images else None

    @classmethod
    def from_data(cls, data):
        try:
            return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"], data["external_urls"]["spotify"])
        except KeyError:
            # if the provided data isn't the full data then just go and get it
            # yourself
            data = get_spotify_client().artist(data["id"])
            return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"], data["external_urls"]["spotify"])

    @classmethod
    def from_dict(cls, data):
        return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"], data["href"])

    @property
    def top_tracks(self):
        if self._top_tracks is None:
            data = get_spotify_client().artist_top_tracks(self.id, "CH")
            self._top_tracks = [
                SpotifyTrack.from_data(entry) for entry in data["tracks"]]

        return self._top_tracks

    def __str__(self):
        return "Artist \"{0.name}\" [{0.popularity}]".format(self)

    def get_dict(self):
        data = {
            "id": self.id,
            "name": self.name,
            "images": self.images,
            "genres": self.genres,
            "popularity": self.popularity,
            "uri": self.uri,
            "href": self.href
        }
        return data


class SpotifyAlbum:

    def __init__(self, id, name, artists, images, uri):
        self.id = id
        self.name = name
        self.artists = artists
        self.images = images
        self.uri = uri

    @property
    def cover(self):
        return self.images[0]["url"] if self.images else None

    @classmethod
    def from_data(cls, data):
        return cls(data["id"], data["name"], [SpotifyArtist.from_data(artist) for artist in data["artists"]], data["images"], data["uri"])

    @classmethod
    def from_dict(cls, data):
        return cls(data["id"], data["name"], [SpotifyArtist.from_dict(artist) for artist in data["artists"]], data["images"], data["uri"])

    def __str__(self):
        return "Album \"{0.name}\" by {0.artists}".format(self)

    def get_dict(self):
        data = {
            "id": self.id,
            "name": self.name,
            "artists": [artist.get_dict() for artist in self.artists],
            "images": self.images,
            "uri": self.uri
        }
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
        search_result = get_spotify_client().search(
            query, limit=1, type="track")
        if len(search_result) < 1 or len(search_result["tracks"]["items"]) < 1:
            return cls.EmptyTrack(query)

        track = search_result["tracks"]["items"][0]

        spotify_track = cls.from_data(track)

        spotify_track.certainty = get_certainty(
            query, track["name"], spotify_track.artists)
        spotify_track.query = query

        return spotify_track

    @classmethod
    def from_data(cls, data):
        album = SpotifyAlbum.from_data(data["album"])

        artists = [SpotifyArtist.from_data(artist)
                   for artist in data["artists"]]

        return cls(data["id"], data["name"], artists, data["duration_ms"] / 1000, album, data["popularity"], data["uri"])

    @classmethod
    def from_dict(cls, data):
        if data is None:
            return None

        return cls(data["id"], data["name"], [SpotifyArtist.from_dict(artist) for artist in data["artists"]] if data["artists"] is not None else None, data["duration"], SpotifyAlbum.from_dict(data["album"]) if data["album"] is not None else None, data["popularity"], data["uri"], data["query"], data["certainty"])

    @property
    def cover_url(self):
        return self.album.cover

    @property
    def artist_string(self):
        return " & ".join(artist.name for artist in self.artists[:2])

    def get_dict(self):
        data = {
            "id": self.id,
            "name": self.name,
            "artists": [artist.get_dict() for artist in self.artists] if self.artists else None,
            "artist": self.artist_string,
            "cover_url": self.cover_url,
            "duration": self.duration,
            "album": self.album.get_dict() if self.album else None,
            "popularity": self.popularity,
            "uri": self.uri,
            "query": self.query,
            "certainty": self.certainty
        }
        return data


def get_certainty(query, song_name, artists):
    song_name_edited = re.sub(r"\(.+\)", "", song_name)

    index = song_name_edited.find("-")
    song_name_edited = song_name_edited[:index if index > 3 else len(song_name_edited)]
    song_name_edited = song_name_edited.strip().lower()

    poss = []
    poss.append(similarity(query.lower(), "{0} {1}".format(song_name_edited, artists[0].name.lower())))
    poss.append(similarity(query.lower(), "{1} {0}".format(song_name_edited, artists[0].name.lower())))

    return max(poss)
