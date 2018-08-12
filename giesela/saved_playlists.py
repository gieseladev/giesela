import re

from .utils import format_time, similarity


class Playlists:

    def get_all_web_playlists(self, queue):
        if self._web_playlists_dirty or not self._cached_web_playlists:
            self._cached_web_playlists = sorted(
                [self.get_web_playlist(name, queue) for name, data in self.playlists.items() if data.get("cover_url")],
                key=lambda playlist: playlist["name"])
            self._web_playlists_dirty = False
            print("[playlists] updated cached web playlists")
        else:
            print("[playlists] using cached web playlists")

        return self._cached_web_playlists

    def get_web_playlist(self, playlist_id, queue):
        data = self.get_playlist(playlist_id, queue)

        duration = sum(entry.duration for entry in data["entries"])

        playlist_info = {
            "name": data["name"],
            "id": data["id"],
            "cover": data["cover_url"],
            "description": data["description"],
            "author": data["author"].to_dict(),
            "replay_count": data["replay_count"],
            "entries": [entry.to_web_dict(skip_calc=True) for entry in data["entries"]],
            "duration": duration,
            "human_dur": format_time(duration, max_specifications=1)
        }

        return playlist_info

    def search_entries_in_playlist(self, queue, playlist, query, certainty_threshold=None):
        if isinstance(playlist, str):
            playlist = self.get_playlist(playlist, queue)

        if isinstance(query, str):
            query_title = query_url = query
        else:
            query_title = query.title
            query_url = query.url

        entries = playlist["entries"]

        def get_similarity(entry):
            s1 = similarity(query_title, entry.title)
            s2 = 1 if query_url == entry.url else 0

            words_in_query = [re.sub(r"\W", "", w)
                              for w in query_title.lower().split()]
            words_in_query = [w for w in words_in_query if w]

            words_in_title = [re.sub(r"\W", "", w)
                              for w in entry.title.lower().split()]
            words_in_title = [w for w in words_in_title if w]

            s3 = sum(len(w) for w in words_in_query if w in entry.title.lower(
            )) / len(re.sub(r"\W", "", query_title))
            s4 = sum(len(w) for w in words_in_title if w in query_title.lower(
            )) / len(re.sub(r"\W", "", entry.title))
            s5 = (s3 + s4) / 2

            return max(s1, s2, s5)

        matched_entries = [(get_similarity(entry), entry) for entry in entries]
        if certainty_threshold:
            matched_entries = [
                el for el in matched_entries if el[0] > certainty_threshold]
        ranked_entries = sorted(
            matched_entries,
            key=lambda el: el[0],
            reverse=True
        )

        return ranked_entries
