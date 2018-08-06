import re

import requests

from giesela.utils import similarity

base_url = "http://vgmdb.info/"


class VGMException:
    class NoResults(Exception):
        pass

    class TrackNotFound(Exception):
        pass

    class ArtistNotComplete(Exception):
        pass


def _search_album(query):
    params = {
        "q": query
    }
    resp = requests.get(base_url + "search/albums", params=params)

    albums = resp.json()["results"]["albums"]

    if not albums:
        raise VGMException.NoResults

    return albums


def _extract_artist(data):
    artist = data["performers"][0]
    artist_name = artist["names"]["en"]

    if "link" not in artist:
        raise VGMException.ArtistNotComplete

    resp = requests.get(base_url + artist["link"])
    data = resp.json()

    artist_image = data["picture_full"]

    return artist_name, artist_image


def _extract_song_title(data, query):
    disc = data["discs"][0]

    clean_query = re.sub(r"\W", "", query).strip()

    similarities = []

    for track in disc["tracks"]:
        title = list(track["names"].values())[0]
        clean_title = re.sub(r"\W", "", title).strip()
        sim = similarity(clean_title, clean_query)

        if sim > .7:
            song_title = title
            break
        else:
            similarities.append((sim, title))
    else:
        sim, song_title = sorted(similarities, key=lambda el: el[0], reverse=True)[0]

        if sim < .5:
            raise VGMException.TrackNotFound

    return song_title


def _get_entry(query):
    albums = _search_album(query)
    fields = {}

    album = albums[0]
    album_name = list(album["titles"].values())[0]
    fields["album"] = album_name

    resp = requests.get(base_url + album["link"])
    data = resp.json()

    song_title = _extract_song_title(data, query)

    fields["song_title"] = song_title

    cover = data["picture_full"]
    fields["cover"] = cover

    artist, artist_image = _extract_artist(data)
    fields["artist"] = artist
    fields["artist_image"] = artist_image

    return fields


async def get_entry(loop, query):
    try:
        return await loop.run_in_executor(None, _get_entry, query)
    except (VGMException.ArtistNotComplete, VGMException.TrackNotFound, VGMException.NoResults):
        return None
    except Exception:
        return None
