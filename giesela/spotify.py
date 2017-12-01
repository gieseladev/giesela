import asyncio
import re
import time
from random import choice

import spotipy
from giesela.utils import similarity
from spotipy.oauth2 import SpotifyClientCredentials


class UrlError(Exception):
    pass


class NotFoundError(Exception):
    pass


cred = SpotifyClientCredentials(
    "df9e44098b934c028ea085227c3ec3f6", "f9d02852fb1a4dacaa50d14e915c5d0e")


def get_spotify_client():
    return spotipy.Spotify(auth=cred.get_access_token())


class SpotifyPlaylist:

    def __init__(self, _id, name, description, tracks, author, images, uri, href):
        self.id = _id
        self.name = name
        self.description = description
        self.tracks = tracks
        self.author = author
        self.images = images
        self.uri = uri
        self.href = href

    def __str__(self):
        return "[SpotifyPlaylist] {} by {} with {} tracks".format(self.name, self.author, len(self.tracks))

    @classmethod
    def from_spotify_playlist(cls, playlist):
        tracks = []
        page = playlist["tracks"]

        tracks.extend([SpotifyTrack.from_data(playlist_track["track"], simple=True) for playlist_track in page["items"]])

        while page["next"]:
            page = get_spotify_client().next(page)
            tracks.extend([SpotifyTrack.from_data(playlist_track["track"], simple=True) for playlist_track in page["items"]])

        kwargs = {
            "_id":          playlist["id"],
            "name":         playlist["name"],
            "description":  playlist["description"],
            "tracks":       tracks,
            "author":       playlist["owner"]["display_name"],
            "images":       playlist["images"],
            "uri":          playlist["uri"],
            "href":         playlist["href"]
        }

        return cls(**kwargs)

    @classmethod
    def from_url(cls, url):
        match = re.search(r"spotify.com\/user\/(\w+)\/playlist\/(\w+)", url)

        if not match:
            raise UrlError("<url> can't be parsed")

        user_id, playlist_id = match.group(1, 2)

        if not (user_id and playlist_id):
            raise UrlError("Couldn't extract user and playlist from <url>")

        try:
            playlist = get_spotify_client().user_playlist(user_id, playlist_id)
        except spotipy.client.SpotifyException:
            raise NotFoundError("Couldn't find the playlist")

        return cls.from_spotify_playlist(playlist)

    @property
    def cover(self):
        return choice(self.images)["url"]

    async def get_spotify_entries_generator(self, queue, **meta):
        gatherers = [track.get_spotify_entry(queue, callback=None, **meta) for track in self.tracks]

        for ind, track_getter in enumerate(gatherers):
            entry = await track_getter
            yield ind, entry

    async def get_spotify_entries(self, queue, callback=None, **meta):
        start = time.time()

        gatherers = [track.get_spotify_entry(queue, callback=callback, **meta) for track in self.tracks]

        done = await asyncio.gather(*gatherers)

        entries = [entry for entry in done if entry]

        print("[Spotify] it took {} seconds to convert the entries".format(time.time() - start))
        return entries


class SpotifyArtist:

    def __init__(self, id, name, images, popularity, genres, uri, href, top_tracks=None):
        self.id = id
        self.name = name
        self._images = images
        self._popularity = popularity
        self._genres = genres
        self.uri = uri
        self.href = href
        self._top_tracks = top_tracks

    @classmethod
    def from_data(cls, data, simple=False):
        try:
            return cls(data["id"], data["name"], data["images"], data["popularity"], data["genres"], data["uri"], data["external_urls"]["spotify"])
        except KeyError:
            if simple:
                return cls(data["id"], data["name"], None, None, None, data["uri"], data["external_urls"]["spotify"])

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
            data = get_spotify_client().artist_top_tracks(self.id)
            self._top_tracks = [
                SpotifyTrack.from_data(entry) for entry in data["tracks"]]

        return self._top_tracks

    @property
    def image(self):
        return choice(self.images)["url"] if self.images else None

    @property
    def images(self):
        if not self._images:
            self.upgrade_to_full()

        return self._images

    @property
    def popularity(self):
        if not self._popularity:
            self.upgrade_to_full()

        return self._popularity

    @property
    def genres(self):
        if not self._genres:
            self.upgrade_to_full()

        return self._genres

    def upgrade_to_full(self):
        data = get_spotify_client().artist(self.id)

        self._images = data["images"]
        self._popularity = data["popularity"]
        self._genres = data["genres"]

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
        return cls(data["id"], data["name"], [SpotifyArtist.from_data(artist, simple=True) for artist in data["artists"]], data["images"], data["uri"])

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

        spotify_track.certainty = get_certainty(query, track["name"], spotify_track.artists[0].name.lower())
        spotify_track.query = query

        return spotify_track

    @classmethod
    def from_url(cls, url):
        match = re.search(r"open\.spotify\.com\/track\/(\w{22})", url)

        if not match:
            raise UrlError("<url> can't be parsed")

        track_id = match.group(1)

        try:
            track = get_spotify_client().track(track_id)
        except spotipy.client.SpotifyException:
            raise NotFoundError("Couldn't find the track")

        return cls.from_data(track)

    @classmethod
    def from_data(cls, data, simple=False):
        album = SpotifyAlbum.from_data(data["album"])

        artists = [SpotifyArtist.from_data(artist, simple=simple)
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

    async def get_spotify_entry(self, queue, callback=None, **meta):
        from giesela.entry import SpotifyEntry

        search_query = re.sub(r"[^\w\s]", "", "{} {}".format(self.artists[0].name, self.name))

        try:
            info = (await queue.downloader.extract_info(queue.loop, search_query, download=False, process=True, retry_on_error=True))["entries"][0]
        except:
            print("[Spotify]", search_query, "failed")

            if callable(callback):
                fut = callback(None, self)
                if asyncio.iscoroutine(fut):
                    await fut

            return None

        args = (
            queue,
            info.get("id"),
            info.get("webpage_url"),
            info.get("title"),
            info.get("duration", 0),
            info.get("thumbnail"),
            info.get("description"),
            self
        )

        # print("\n".join(str(a) for a in args) + "\n\n")

        entry = SpotifyEntry(
            *args,
            **meta
        )

        if callable(callback):
            fut = callback(entry, self)
            if asyncio.iscoroutine(fut):
                await fut

        return entry


async def get_spotify_track(loop, query):
    return await loop.run_in_executor(None, SpotifyTrack.from_query, query)


def get_certainty(query, song_name, artist_name):
    song_name_edited = re.sub(r"\(.+\)", "", song_name)

    index = song_name_edited.find("-")
    song_name_edited = song_name_edited[:index if index > 3 else len(song_name_edited)]
    song_name_edited = song_name_edited.strip().lower()

    poss = []
    poss.append(similarity(query.lower(), "{0} {1}".format(song_name_edited, artist_name)))
    poss.append(similarity(query.lower(), "{1} {0}".format(song_name_edited, artist_name)))

    return max(poss)


def model_from_url(url):
    try:
        return SpotifyTrack.from_url(url)
    except (UrlError, NotFoundError):
        pass

    try:
        return SpotifyPlaylist.from_url(url)
    except (UrlError, NotFoundError):
        pass

    return None


if __name__ == "__main__":
    start = time.time()
    print(SpotifyPlaylist.from_url("https://open.spotify.com/user/spotify/playlist/37i9dQZF1DWVcbzTgVpNRm"))
    print("it took {} seconds to get the playlist".format(time.time() - start))
