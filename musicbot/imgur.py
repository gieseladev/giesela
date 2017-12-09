from io import BytesIO

from imgurpython import ImgurClient
from imgurpython.helpers.error import (ImgurClientError,
                                       ImgurClientRateLimitError)

client_id = "a2ef870c9cfc5c0"
client_secret = "9006ebbaed1dd639ef79de176ae10419664ac4c6"
access_token = "2028c849e4a68badd5fe83b4a7a54115f5a5e86c"
refresh_token = "9c874d1b9418b380c1cb373749c462a2750ec610"

client = ImgurClient(client_id, client_secret, access_token, refresh_token)


def delete_previous_playlist_cover(file_name):
    album = client.get_album("Duyku")
    for img in album.images:
        if file_name == img["name"]:
            client.album_remove_images("Duyku", [img["id"]])
            client.delete_image(img["id"])
            return


def _upload_playlist_cover(playlist_name, url):
    file_name = playlist_name.strip().lower().replace(" ", "_")
    name = playlist_name.replace("_", " ").title()

    delete_previous_playlist_cover(file_name)

    config = {
        "album": "liSNPNU2S6NR4AS",
        "name": file_name,
        "title": name,
        "description": "The cover for the playlist " + name
    }

    try:
        if isinstance(url, BytesIO):
            resp = client.upload(url, config=config)
        else:
            resp = client.upload_from_url(url, config=config)
    except ImgurClientError:
        return False
    except ImgurClientRateLimitError:
        print("[IMGUR] RATE LIMIT!")
        return False

    return resp.get("link")


async def upload_playlist_cover(loop, name, url):
    return await loop.run_in_executor(None, _upload_playlist_cover, name, url)


def delete_previous_song_image(album_id, file_name):
    album = client.get_album(album_id)
    for img in album.images:
        if file_name == img["name"]:
            client.album_remove_images(album_id, [img["id"]])
            client.delete_image(img["id"])
            return


def ensure_album(album_name):
    albums = client.get_account_albums("Giesela")
    for album in albums:
        if album.title == album_name:
            return album.id, album.deletehash

    fields = {
        "title": album_name,
        "description": "All the images related to the playlist " + album_name
    }

    resp = client.create_album(fields)
    return resp["id"], resp["deletehash"]


def _upload_song_image(playlist_name, identifier, url):
    album_name = playlist_name.replace("_", " ").title()

    album_id, edit_id = ensure_album(album_name)
    delete_previous_song_image(album_id, identifier)

    config = {
        "album": edit_id,
        "name": identifier,
        "title": identifier,
        "description": "The {2} for the entry {0}".format(*identifier.partition(" "))
    }

    try:
        resp = client.upload_from_url(url, config=config)
    except ImgurClientError:
        return False
    except ImgurClientRateLimitError:
        print("[IMGUR] RATE LIMIT!")
        return False

    return resp.get("link")


async def upload_song_image(loop, playlist_name, identifier, url):
    identifier = identifier.replace("_", " ").replace("url", "").strip().title()
    return await loop.run_in_executor(None, _upload_song_image, playlist_name, identifier, url)

# print(client.credits)
# _upload_song_image("simonisanerd", "HiJaKl2 thumbnail",
#                    "https://lh3.googleusercontent.com/CbCjzp0eJoLIm0OmfJ5-xTB8namB7Pvw95hvhBZq-CbnkbF0tvig9XTOt8EFHiBgaBVb")
