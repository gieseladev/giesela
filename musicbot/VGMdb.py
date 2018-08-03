import re
import traceback

import requests

from musicbot.utils import similarity

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

    song_title = None
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
    except:
        traceback.print_exc()
        return None


if __name__ == "__main__":
    def test():
        tests = [
            "3-Nen E-Gumi Utatan - QUESTION",
            "3-nen E-gumi Utatan - Bye Bye YESTERDAY",
            "3-nen E-gumi Utatan - Jiriki Hongan Revolution",
            "AAA - Wake up!",
            "Aimer - Dareka Umi Wo",
            "Angela - Sidonia",
            "Anonymuz - Evangelion X",
            "Aoi Tada - Yake Ochinai Tsubasa",
            "Aya Hirano - Bouken Desho Desho?",
            "Aya Hirano - God Knows...",
            "Aya Hirano - Lost My Music",
            "Aya Hirano - Super Driver",
            "BOYSTYLE - Kokoro no Chizu",
            "BoA - Masayume Chasing",
            "Boku Dake Ga Inai Machi Ending",
            "Boku Dake Ga Inai Machi Re",
            "Boku No Hero Academia 僕のヒーローアカデミア",
            "Chieko Kawabe - Be Your Girl",
            "Chihiro Yonekura - Fairy Tail ~Yakusoku No Hi~",
            "Cinema Staff - Great Escape",
            "Code Geass R2 Worlds End",
            "EGOIST - Departures",
            "Eir Aoi - Ignite",
            "FLOW - Colors",
            "Fairy Tail - Fairy Tail's Is Born 2016",
            "Fairy Tail - Kizuna",
            "Fairy Tail 2014 Strike Back",
            "Fate - Stay Night - Kishi Ou No Hokori フェイト - ステイナイト",
            "Faylan - Dead END",
            "Fullmetal Alchemist Brotherhood - Again",
            "Funkist - Snow Fairy",
            "Fuwa Fuwa Time Mio",
            "Greatest Battle Music OF All Times - Rule The Battlefield",
            "HERO - Tenohira",
            "HI-FI CAMP - Kono Te Nobashite",
            "Haruna Luna - Startear",
            "Hiroyuki Oshima - Blood History",
            "Hiroyuki Sawano & Cyua - Vogel Im Kafig",
            "Hiroyuki Sawano & MPI - The Reluctant Heroes",
            "Hiroyuki Sawano - U & Cloud",
            "Hiroyuki Sawano - Vogel im Käfig",
            "Hiroyuki Sawano - theDOGS",
            "Hiroyuki Sawano - Κronё",
            "Hitomi Kuroishi - Innocent Days",
            "Ho-kago Tea Time - NO, Thank You!",
            "Katherine Liner - On My Own",
            "Kenzie Smith Piano - Continued Story (From \"Code Geass\")",
            "Kensuke Ushio - Lit",
            "Konomi Suzuki - This Game",
            "Kuroishi Hitomi - Stories",
            "Kōtarō Nakagawa - Madder Sky",
            "LiSA - Ichiban no Takaramono",
            "LiSA - Shirushi",
            "Lia - Bravely You",
            "Linked Horizon - Guren No Yumiya",
            "Linked Horizon - Jiyuu No Tsubasa",
            "Linked Horizon - Opfert eure Herzen!",
            "Luna Haruna - Overfly",
            "MONORAL - Kiri",
            "Man With a Mission - Database",
            "Monkey Majik - Sunshine",
            "Mosaic Kakera - Sunset Swish",
            "My Soul Your Beats 高音質",
            "Myth & Roid - STYX HELIX",
            "Nano - No Pain, No Game",
            "Naruto Shippuden",
            "Nevereverland - Nano",
            "Nomizu Iori - Black † White",
            "Noragami - Hello Sleepwalkers",
            "Noragami Goya No Machiawase",
            "ONE OK ROCK - Clock Strikes",
            "Orange Range - Asterisk",
            "Oratorio The World God Only Knows - God Only Knows W",
            "OxT - Clattanoia",
            "PelleK - Hands Up! (One Piece Opening 16)",
            "Penguin Research - Button",
            "Period - Chemistry",
            "RADWIMPS - Nandemonaiya",
            "ROOKiEZ is PUNK'D - Complication",
            "ROOKiEZ is PUNK'D - In My World",
            "Rika Mayama - Liar Mask",
            "Sakurasou No Pet Na Kanojo Ed DAYS of DASH",
            "Sankarea - Nano RIPE - Esoragoto",
            "Sapphire & None Like Joshua - Don't Lose Your Way (Feat. NoneLikeJoshua)",
            "Sayuri - Rura",
            "Shiver - the Gazette",
            "Angela - Kishi Shinkoukyoku",
            "Sword Of The Stranger - Ihojin No Yaiba Battle",
            "Tekken 7 - Aloneness",
            "The Oral Cigarettes - Hey Kids",
            "Wakaba - Ashita, Boku wa Kimi ni Ai ni Iku",
            "We're the Stars - Fairy Tail ENDING 14",
            "White Silence - Tokyo Ghoul Thaisub",
            "Yasuharu Takanashi - Absolute Zero Silver",
            "Yasuharu Takanashi - Fairy's Challenge",
            "Yasuharu Takanashi - Mavis",
            "Yasuharu Takanashi - Multiflora No",
            "Yasuharu Takanashi - Seigi No Chikara",
            "Yasuharu Takanashi - Shukumei",
            "Yojou-Han Shinwa Taikai Ed",
            "Yoko Kanno - Living Inside the Shell",
            "Yousei Teikoku - Kuusou Mesorogiwi",
            "Yuka Iguchi - Platinum Disco",
            "Yukari Hashimoto - Lost My Pieces",
            "Yuki Kajiura - Luminous Sword",
            "Yuki Kajiura - Tragedy and Fate",
            "Yuzu - Nagareboshi Kirari",
            "Zaq - Sparkling Daydream",
            "moumoon - Hello, shooting-star",
            "Radwimps - Sparkle",
            "僕のヒーローアカデミア Boku No Hero Academia Ed HEROES",
            "Radwimps - Zen Zen Zense"
        ]

        found = 0

        for test in tests:
            try:
                entry = _get_entry(test)
                print("{}: {}".format(test, entry["song_title"]))
                found += 1
            except (VGMException.NoResults, VGMException.TrackNotFound, VGMException.ArtistNotComplete):
                pass
            except:
                print("There was an error with {}".format(test))
                raise

        print("Found {}%".format(round(100 * found / len(tests))))

    test()
    # _get_entry("Cinema Staff - Great Escape")
