import asyncio
import time
from socket import *
from threading import Thread

from .spotify import SpotifyTrack


class SocketServer:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.host = ""
        self.port = 5005
        self.buf_size = 1024
        self.max_connections = 10
        self.connections = []
        self.server_ids = {}
        self.stop_threads = False
        self.awaiting_registeration = {}

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
            response = "USERINFORMATION;{};{}".format(server_id, author_id)
            sck.sendall("{}=={}".format(
                len(response), response).encode("utf-8"))
            return True

    def threaded_broadcast_information(self):
        work_thread = Thread(target=self._broadcast_information)
        work_thread.start()

    def _broadcast_information(self):
        to_delete = []
        for sock, server_id in self.server_ids.items():
            try:
                response = "INFORMATION;{artist};{song_title};{play_status};{cover_url};{progress};{duration};{volume}"

                artist, song_title, cover_url, playing, duration, progress, volume = self.get_player_values(
                    server_id)

                response = response.format(artist=artist, song_title=song_title, play_status=playing,
                                           cover_url=cover_url, progress=progress, duration=duration, volume=volume)
                #print("I sent\n\n{}\n\n========".format(response))
                #print("[SOCKETSERVER] Broadcasted information")
                sock.sendall("{}=={}".format(
                    len(response), response).encode("utf-8"))
            except:
                raise
                to_delete.append(sock)

        for key in to_delete:
            print("[SOCKETSERVER] Socket didn't want to receive my broadcast!")
            self.server_ids.pop(key)

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
                print("[SOCKETSERVER] Connected to {}".format(connected_address))
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
            #print("[SOCKETSERVER] Socket received message: {}".format(msg))
            try:
                parts = msg.split(";")
                request = parts[0]
                server_id = parts[1]
                author_id = parts[2]
                leftover = parts[3:]
                if server_id.lower() not in ["USER_IDENTIFICATION"]:
                    self.server_ids[c_socket] = server_id
            except:
                print("[SOCKETSERVER] Socket received malformed message")
                break

            if request == "REQUEST" and len(leftover) > 0 and leftover[0] == "SEND_INFORMATION":
                response = "INFORMATION;{artist};{song_title};{play_status};{cover_url};{progress};{duration};{volume}"

                artist, song_title, cover_url, playing, duration, progress, volume = self.get_player_values(
                    server_id)

                response = response.format(artist=artist, song_title=song_title, play_status=playing,
                                           cover_url=cover_url, progress=progress, duration=duration, volume=volume)
                #print("[SOCKETSERVER] Socket sent data")
                c_socket.sendall("{}=={}".format(
                    len(response), response).encode("utf-8"))
            elif request == "REQUEST" and server_id == "USER_IDENTIFICATION":
                token = leftover[author_id]
                print("[SOCKETSERVER] requested a user identification with token " + token)
                self.awaiting_registeration[c_socket] = token.lower()

            elif request == "COMMAND":
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                else:
                    player = None

                if leftover[0] == "SUMMON":
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.musicbot.socket_summon(server_id), self.musicbot.loop)
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
                        print("[SOCKETSERVER] " + author_id + " Changed volume from {} to {}".format(
                            before_vol, player.volume))

        to_delete = None
        for i in range(len(self.connections)):
            if self.connections[i][1] == c_socket:
                to_delete = self.connections[i]
                print("[SOCKETSERVER] " + author_id + " Shutting down connection: " +
                      str(self.connections[i][2]))

        if to_delete is not None:
            self.connections.remove(to_delete)
        else:
            print("[SOCKETSERVER] " + author_id + " Couldn't remove this connection from list")

        self.server_ids.pop(c_socket, None)
        c_socket.shutdown(SHUT_RDWR)
        c_socket.close()

    def get_player_values(self, server_id):
        artist = " "
        song_title = "NOT CONNECTED TO A CHANNEL"
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
                artist = "STREAM"
                song_title = player.current_entry.title.upper()
                playing = "PLAYING" if player.is_playing else "PAUSED"
                progress = str(round(player.progress, 2))
            else:
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

            volume = str(round(player.volume, 2))

        return artist, song_title, cover_url, playing, duration, progress, volume
