import time
from socket import *
from threading import Thread

from .spotify import SpotifyTrack


class SocketServer:

    def __init__(self, musicbot, loop):
        self.musicbot = musicbot
        self.loop = loop
        self.host = ""
        self.port = 5005
        self.buf_size = 1024
        self.max_connections = 10
        self.connections = []
        self.server_ids = ***REMOVED******REMOVED***
        self.stop_threads = False

        main_socket = socket(AF_INET, SOCK_STREAM)
        main_socket.bind((self.host, self.port))
        main_socket.listen(1)

        self.main_socket = main_socket
        self.main_thread = Thread(target=self.connection_accepter)
        self.main_thread.start()

    def shutdown(self):
        self.main_socket.shutdown(SHUT_RDWR)
        self.main_socket.close()
        self.stop_threads = True

    def threaded_broadcast_information(self):
        work_thread = Thread(target=self._broadcast_information)
        work_thread.start()

    def _broadcast_information(self):
        for sock, server_id in self.server_ids.items():
            response = "INFORMATION;***REMOVED***artist***REMOVED***;***REMOVED***song_title***REMOVED***;***REMOVED***play_status***REMOVED***;***REMOVED***cover_url***REMOVED***;***REMOVED***progress***REMOVED***;***REMOVED***duration***REMOVED***;***REMOVED***volume***REMOVED***"

            artist, song_title, cover_url, playing, duration, progress, volume = self.get_player_values(
                server_id)

            response = response.format(artist=artist, song_title=song_title, play_status=playing,
                                       cover_url=cover_url, progress=progress, duration=duration, volume=volume)
            #print("I sent\n\n***REMOVED******REMOVED***\n\n========".format(response))
            #print("[SOCKETSERVER] Broadcasted information")
            sock.sendall("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                len(response), response).encode("utf-8"))

    def connection_accepter(self):
        while not self.stop_threads:
            # print(len(self.connections))
            if len(self.connections) >= self.max_connections:
                print("[SOCKETSERVER] Too many parallel connections!")
                time.sleep(5)
            else:
                (connected_socket, connected_address) = self.main_socket.accept()
                thread = Thread(target=self.connection_maintainer,
                                args=(connected_socket,))
                thread.start()
                self.connections.append(
                    (thread, connected_socket, connected_address))
                print("[SOCKETSERVER] Connected to ***REMOVED******REMOVED***".format(connected_address))

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
            #print("[SOCKETSERVER] Socket received message: ***REMOVED******REMOVED***".format(msg))
            try:
                parts = msg.split(";")
                request = parts[0]
                server_id = parts[1]
                self.server_ids[c_socket] = server_id
                leftover = parts[2:]
            except:
                print("[SOCKETSERVER] Socket received malformed message")
                break

            if request == "REQUEST" and leftover[0] == "SEND_INFORMATION":
                response = "INFORMATION;***REMOVED***artist***REMOVED***;***REMOVED***song_title***REMOVED***;***REMOVED***play_status***REMOVED***;***REMOVED***cover_url***REMOVED***;***REMOVED***progress***REMOVED***;***REMOVED***duration***REMOVED***;***REMOVED***volume***REMOVED***"

                artist, song_title, cover_url, playing, duration, progress, volume = self.get_player_values(
                    server_id)

                response = response.format(artist=artist, song_title=song_title, play_status=playing,
                                           cover_url=cover_url, progress=progress, duration=duration, volume=volume)
                #print("[SOCKETSERVER] Socket sent data")
                c_socket.send("***REMOVED******REMOVED***==***REMOVED******REMOVED***".format(
                    len(response), response).encode("utf-8"))
            elif request == "COMMAND":
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                else:
                    player = None

                if player is not None:
                    if leftover[0] == "PLAY_PAUSE":
                        if player.is_paused:
                            player.resume()
                            print("[SOCKETSERVER] Resumed")
                        elif player.is_playing:
                            player.pause()
                            print("[SOCKETSERVER] Paused")
                    elif leftover[0] == "SKIP":
                        player.skip()
                        print("[SOCKETSERVER] Skipped")
                    elif leftover[0] == "VOLUMECHANGE":
                        before_vol = player.volume
                        player.volume = float(leftover[1])
                        print("[SOCKETSERVER] Changed volume from ***REMOVED******REMOVED*** to ***REMOVED******REMOVED***".format(
                            before_vol, player.volume))

        to_delete = None
        for i in range(len(self.connections)):
            if self.connections[i][1] == c_socket:
                to_delete = self.connections[i]
                print("[SOCKETSERVER] Shutting down connection: " +
                      str(self.connections[i][2]))

        if to_delete is not None:
            self.connections.remove(to_delete)
        else:
            print("[SOCKETSERVER] Couldn't remove this connection from list")

        self.server_ids.pop(c_socket, None)
        c_socket.shutdown(SHUT_RDWR)
        c_socket.close()

    def get_player_values(self, server_id):
        if server_id in self.musicbot.players:
            player = self.musicbot.players[server_id]
            if player.current_entry is None:
                artist = " "
                song_title = "None"
                cover_url = "http://i.imgur.com/nszu54A.jpg"
                playing = "STOPPED"
                duration = "0"
                progress = "0"
            elif type(player.current_entry).__name__ == "StreamPlaylistEntry":
                artist = "STREAM"
                song_title = player.current_entry.title.upper()
                cover_url = "http://i.imgur.com/nszu54A.jpg"
                playing = "PLAYING" if player.is_playing else "PAUSED"
                duration = "0"
                progress = str(round(player.progress, 2))
            else:
                spotify_track = SpotifyTrack.from_query(
                    player.current_entry.title)
                if spotify_track.certainty > .4:
                    artist = spotify_track.artist
                    song_title = spotify_track.song_name
                    cover_url = spotify_track.cover_url
                else:
                    artist = " "
                    song_title = spotify_track.song_name
                    cover_url = "http://i.imgur.com/nszu54A.jpg"

                playing = "PLAYING" if player.is_playing else "PAUSED"
                duration = str(player.current_entry.duration)
                progress = str(round(player.progress, 2))

            volume = str(round(player.volume, 2))

        return artist, song_title, cover_url, playing, duration, progress, volume
