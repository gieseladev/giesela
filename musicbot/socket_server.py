import asyncio
import re
import time
from datetime import datetime, timedelta
from socket import *
from threading import Thread

from .radio import Radio
from .spotify import SpotifyTrack
from .utils import parse_timestamp


class SocketServer:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.host = ""
        self.port = 5005
        self.buf_size = 1024
        self.max_connections = 10
        self.connections = []
        self.server_ids = ***REMOVED******REMOVED***
        self.stop_threads = False
        self.awaiting_registeration = ***REMOVED******REMOVED***
        self.sockets_by_user = ***REMOVED******REMOVED***

        try:
            main_socket = socket(AF_INET, SOCK_STREAM)
            main_socket.bind((self.host, self.port))
            main_socket.listen(1)
            self.main_socket = main_socket
            self.main_thread = Thread(target=self.connection_accepter)
            self.main_thread.start()
        except:
            print("[SOCKETSERVER] Can't connect. Address already in use.")

    def shutdown(self):
        self.stop_threads = True
        try:
            self.main_socket.shutdown(SHUT_RDWR)
        except:
            pass

        self.main_socket.close()
        print("[SOCKETSERVER] Shutdown!")

    async def register_handler(self, token, server_id, author_id):
        sck = None

        for sock, tok in self.awaiting_registeration.items():
            if tok.lower() == token.lower():
                sck = sock
                break

        if sck is None:
            return False
        else:
            self.awaiting_registeration.pop(sck)
            response = "USERINFORMATION;***REMOVED******REMOVED***;***REMOVED******REMOVED***".format(server_id, author_id)
            sck.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                len(response), response).encode("utf-8"))
            return True

    def threaded_broadcast_information(self):
        work_thread = Thread(target=self._broadcast_information)
        work_thread.start()

    def _broadcast_information(self):
        to_delete = []
        for sock, server_id in self.server_ids.items():
            try:
                response = "INFORMATION;***REMOVED***artist***REMOVED***;***REMOVED***song_title***REMOVED***;***REMOVED***video_id***REMOVED***;***REMOVED***play_status***REMOVED***;***REMOVED***cover_url***REMOVED***;***REMOVED***progress***REMOVED***;***REMOVED***duration***REMOVED***;***REMOVED***volume***REMOVED***"

                artist, song_title, video_id, cover_url, playing, duration, progress, volume = self.get_player_values(
                    server_id)

                response = response.format(artist=artist, song_title=song_title, video_id=video_id,
                                           play_status=playing, cover_url=cover_url, progress=progress, duration=duration, volume=volume)
                #print("I sent\n\n***REMOVED******REMOVED***\n\n========".format(response))
                #print("[SOCKETSERVER] Broadcasted information")
                sock.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                    len(response), response).encode("utf-8"))
            except:
                raise
                to_delete.append(sock)

        for key in to_delete:
            print("[SOCKETSERVER] Socket didn't want to receive my broadcast!")
            self.server_ids.pop(key)

    def broadcast_message(self, message):
        to_delete = []
        for author in self.sockets_by_user:
            if not self.send_message(author, message):
                to_delete.append(author)

        for key in to_delete:
            self.sockets_by_user.pop(key, None)

    def send_message(self, author_id, message):
        s = self.sockets_by_user.get(str(author_id), None)
        if s is None:
            return None

        try:
            msg = "MESSAGE;***REMOVED******REMOVED***".format(message)
            s.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(len(msg), msg).encode("utf-8"))
            return True
        except:
            return False

    def connection_accepter(self):
        print("[SOCKETSERVER] Listening!")
        while not self.stop_threads:
            # print(len(self.connections))
            if len(self.connections) >= self.max_connections:
                print("[SOCKETSERVER] Too many parallel connections!")
                time.sleep(5)
            else:
                try:
                    (connected_socket, connected_address) = self.main_socket.accept()
                except:
                    print("[SOCKETSERVER] Can't use this socket")
                    continue

                thread = Thread(target=self.connection_maintainer,
                                args=(connected_socket,))
                thread.start()
                self.connections.append(
                    (thread, connected_socket, connected_address))
                print("[SOCKETSERVER] Connected to ***REMOVED******REMOVED***".format(connected_address))
        print("[SOCKETSERVER] Stopping accepter thread")

    def connection_maintainer(self, *args):
        c_socket = args[0]
        while not self.stop_threads:
            try:
                data = c_socket.recv(self.buf_size)
            except:
                break
            if data is None:
                break

            msg = data.decode("utf-8")
            if msg in ["exit", "sdown", ""]:
                break

            if msg == "ping":
                c_socket.sendall("4==pong".encode("utf-8"))
                continue
            #print("[SOCKETSERVER] Socket received message: ***REMOVED******REMOVED***".format(msg))
            try:
                parts = msg.split(";")
                request = parts[0]
                server_id = parts[1]
                author_id = parts[2]
                leftover = parts[3:]
                if server_id.lower() not in ["USER_IDENTIFICATION"]:
                    self.server_ids[c_socket] = server_id
                    self.sockets_by_user[author_id] = c_socket
            except:
                print("[SOCKETSERVER] Socket received malformed message")
                break

            if request == "REQUEST" and len(leftover) > 0 and leftover[0] == "SEND_INFORMATION":
                response = "INFORMATION;***REMOVED***artist***REMOVED***;***REMOVED***song_title***REMOVED***;***REMOVED***video_id***REMOVED***;***REMOVED***play_status***REMOVED***;***REMOVED***cover_url***REMOVED***;***REMOVED***progress***REMOVED***;***REMOVED***duration***REMOVED***;***REMOVED***volume***REMOVED***"

                artist, song_title, video_id, cover_url, playing, duration, progress, volume = self.get_player_values(
                    server_id)

                response = response.format(artist=artist, song_title=song_title, video_id=video_id,
                                           play_status=playing, cover_url=cover_url, progress=progress, duration=duration, volume=volume)
                #print("[SOCKETSERVER] Socket sent data")
                c_socket.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                    len(response), response).encode("utf-8"))
            elif request == "REQUEST" and server_id == "USER_IDENTIFICATION":
                token = author_id
                print(
                    "[SOCKETSERVER] requested a user identification with token " + token)
                self.awaiting_registeration[c_socket] = token.lower()
            elif request == "REQUEST" and len(leftover) > 0 and leftover[0] == "SEND_PLAYLISTS":
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                else:
                    continue

                response = "INFORMATION;PLAYLISTS;***REMOVED******REMOVED***".format(
                    self.get_playlists_string(player, server_id))
                c_socket.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                    len(response), response).encode("utf-8"))

            elif request == "COMMAND":
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                else:
                    player = None

                if leftover[0] == "SUMMON":
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.musicbot.socket_summon(server_id, author_id), self.musicbot.loop)
                    except:
                        pass

                if player is not None:
                    if leftover[0] == "PLAY_PAUSE":
                        if player.is_paused:
                            player.resume()
                            print("[SOCKETSERVER] " + author_id + " Resumed")
                        elif player.is_playing:
                            player.pause()
                            print("[SOCKETSERVER] " + author_id + " Paused")
                    elif leftover[0] == "SKIP":
                        player.skip()
                        print("[SOCKETSERVER] " + author_id + " Skipped")
                    elif leftover[0] == "VOLUMECHANGE":
                        before_vol = player.volume
                        player.volume = float(leftover[1])
                        print("[SOCKETSERVER] " + author_id + " Changed volume from ***REMOVED******REMOVED*** to ***REMOVED******REMOVED***".format(
                            before_vol, player.volume))
                    elif leftover[0] == "PLAY":
                        video_url = leftover[1]
                        try:
                            asyncio.run_coroutine_threadsafe(
                                player.playlist.add_entry(video_url), self.musicbot.loop)
                        except WrongEntryTypeError:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    player.playlist.import_from(video_url), self.musicbot.loop)
                            except:
                                print("[SOCKETSERVER] " + author_id +
                                      " Could not play \"***REMOVED******REMOVED***\"".format(video_url))

                        print("[SOCKETSERVER] " + author_id +
                              " Playing \"***REMOVED******REMOVED***\"".format(video_url))
                    elif leftover[0] == "RADIO":
                        radio_name = leftover[1]
                        asyncio.run_coroutine_threadsafe(self.musicbot.socket_radio(
                            player, radio_name), self.musicbot.loop)
                        print("[SOCKETSERVER] ***REMOVED******REMOVED*** Radio station ***REMOVED******REMOVED***".format(
                            author_id, radio_name))
                    elif leftover[0] == "PLAYLIST":
                        playlist_name = leftover[1]
                        asyncio.run_coroutine_threadsafe(self.musicbot.socket_playlist_load(
                            player, playlist_name), self.musicbot.loop)
                        print("[SOCKETSERVER] ***REMOVED******REMOVED*** Playlist ***REMOVED******REMOVED***".format(
                            author_id, playlist_name))

        if self.sockets_by_user.pop(author_id, None) is None:
            print("[SOCKETSERVER] failed to remove ***REMOVED******REMOVED*** (***REMOVED******REMOVED***) from sockets_by_user list".format(
                str(c_socket), author_id))

        to_delete = None
        for i in range(len(self.connections)):
            if self.connections[i][1] == c_socket:
                to_delete = self.connections[i]
                print("[SOCKETSERVER] " + author_id + " Shutting down connection: " +
                      str(self.connections[i][2]))

        if to_delete is not None:
            self.connections.remove(to_delete)
        else:
            print("[SOCKETSERVER] " + author_id +
                  " Couldn't remove this connection from list")

        self.server_ids.pop(c_socket, None)
        c_socket.shutdown(SHUT_RDWR)
        c_socket.close()

    def get_player_values(self, server_id):
        artist = " "
        song_title = "NOT CONNECTED TO A CHANNEL"
        video_id = " "
        cover_url = "http://i.imgur.com/nszu54A.jpg"
        playing = "UNCONNECTED"
        duration = "0"
        progress = "0"
        volume = ".5"

        if server_id in self.musicbot.players:
            player = self.musicbot.players[server_id]
            if player.current_entry is None:
                song_title = "NONE"
                playing = "STOPPED"
            elif type(player.current_entry).__name__ == "StreamPlaylistEntry":
                if Radio.has_station_data(player.current_entry.title):
                    current_entry = asyncio.run_coroutine_threadsafe(Radio.get_current_song(
                        self.musicbot.loop, player.current_entry.title), self.musicbot.loop).result()
                    if current_entry is not None:
                        progress = str(current_entry["progress"])
                        duration = str(current_entry["duration"])
                        playing = "PLAYING"
                        song_title = current_entry["title"]
                        cover_url = current_entry["cover"]
                        artist = current_entry["artist"]
                        matches = re.search(
                            r"(?:[?&]v=|\/embed\/|\/1\/|\/v\/|https:\/\/(?:www\.)?youtu\.be\/)([^&\n?#]+)", current_entry["youtube"])
                        video_id = matches.group(
                            1) if matches is not None else " "
                        volume = str(round(player.volume, 2))

                        return artist, song_title, video_id, cover_url, playing, duration, progress, volume

                if player.current_entry.radio_station_data is not None:
                    station_data = player.current_entry.radio_station_data
                    artist = "RADIO"
                    song_title = station_data.name.upper()
                    cover_url = station_data.cover
                else:
                    artist = "STREAM"
                    song_title = player.current_entry.title.upper()

                playing = "PLAYING" if player.is_playing else "PAUSED"
                progress = str(round(player.progress, 2))
                matches = re.search(
                    r"(?:[?&]v=|\/embed\/|\/1\/|\/v\/|https:\/\/(?:www\.)?youtu\.be\/)([^&\n?#]+)", player.current_entry.url)
                video_id = matches.group(1) if matches is not None else " "
            elif type(player.current_entry).__name__ == "URLPlaylistEntry":
                spotify_track = SpotifyTrack.from_query(
                    player.current_entry.title)
                if spotify_track.certainty > .4:
                    artist = spotify_track.artist
                    song_title = spotify_track.song_name
                    cover_url = spotify_track.cover_url
                else:
                    song_title = spotify_track.query.upper()

                playing = "PLAYING" if player.is_playing else "PAUSED"
                duration = str(player.current_entry.duration)
                progress = str(round(player.progress, 2))
                matches = re.search(
                    r"(?:[?&]v=|\/embed\/|\/1\/|\/v\/|https:\/\/(?:www\.)?youtu\.be\/)([^&\n?#]+)", player.current_entry.url)
                video_id = matches.group(1) if matches is not None else " "

            volume = str(round(player.volume, 2))

        return artist, song_title, video_id, cover_url, playing, duration, progress, volume

    def get_playlists_string(self, player, server_id):
        base_playlist_layout = "***REMOVED***name***REMOVED***;***REMOVED***author***REMOVED***;***REMOVED***replays***REMOVED***;***REMOVED***entry_count***REMOVED***;***REMOVED***playtime***REMOVED***"
        playlists = self.musicbot.playlists.get_all_playlists(player.playlist)
        workString = "***REMOVED******REMOVED***;".format(len(playlists))
        playlist_strings = []
        for playlist in playlists:
            values = ***REMOVED******REMOVED***
            values["name"] = playlist[0]
            values["author"] = self.musicbot.get_server(
                server_id).get_member(playlist[1].get("author")).name
            values["replays"] = playlist[1].get("replay_count")
            values["entry_count"] = playlist[1].get("entry_count")
            values["playtime"] = str(
                sum([x.duration for x in playlist[1].get("entries")]))
            playlist_strings.append(base_playlist_layout.format(**values))

        workString += ";".join(playlist_strings)
        return workString
