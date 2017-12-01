import json
import re
import traceback

import discogs_client
from discogs_client.exceptions import HTTPError
from giesela.constants import VERSION
from giesela.spotify import get_certainty
from giesela.utils import similarity

client = discogs_client.Client("Giesela/{}".format(VERSION), user_token="vrzQalQXQdNAZYnwYlWunuJSyMjFlcGKXwglcITo")


class DiscogsException:

    class TrackNotFound(Exception):
        pass

    class NoResults(Exception):
        pass

    class ArtistNotFound(Exception):
        pass

    class WrongTrack(Exception):
        pass


def _extract_song_title(release, query):
    tracks = release.tracklist

    clean_query = re.sub(r"\W", "", query).strip()

    song_title = None
    similarities = []

    for track in tracks:
        title = track.title
        clean_title = re.sub(r"\W", "", title).strip()
        sim = similarity(clean_title, clean_query)

        if sim > .7:
            song_title = title
            break
        else:
            similarities.append((sim, title))
    else:
        sim, song_title = sorted(similarities, key=lambda el: el[0], reverse=True)[0]

        if sim < .3:
            raise DiscogsException.TrackNotFound

    return song_title


def _extract_artist_image(release):
    if not release.artists:
        raise DiscogsException.ArtistNotFound

    try:
        images = release.artists[0].images
    except HTTPError:
        raise DiscogsException.ArtistNotFound

    if not images:
        raise DiscogsException.ArtistNotFound

    choices = []

    for img in images:
        if img["height"] == img["width"]:
            return img["uri"]

        dimension = max(img["height"], img["width"])
        difference = abs(img["height"] - img["width"])

        choices.append((img["uri"], difference / dimension))

    return sorted(choices, key=lambda el: el[1])[0][0]


def _get_entry(query):
    fields = {}

    results = client.search(query, type="release")

    if not results:
        raise DiscogsException.NoResults

    release = results[0]

    if not release.artists:
        raise DiscogsException.ArtistNotFound

    fields["song_title"] = _extract_song_title(release, query)
    fields["artist"] = release.artists[0].name
    fields["album"] = release.title

    fields["cover"] = release.images[0]["uri"]
    fields["artist_image"] = _extract_artist_image(release)

    if get_certainty(query, fields["song_title"], fields["artist"]) < .6:
        raise DiscogsException.WrongTrack

    return fields


async def get_entry(loop, query):
    try:
        return await loop.run_in_executor(None, _get_entry, query)
    except (DiscogsException.TrackNotFound, DiscogsException.NoResults, DiscogsException.ArtistNotFound, DiscogsException.WrongTrack):
        return None
    except:
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print(json.dumps(_get_entry("77 bombay street - up in the sky"), indent=4))
