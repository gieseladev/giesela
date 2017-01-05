import time
from socket import *
from threading import Thread


class SocketServer:

    def __init__(self, musicbot, loop):
        self.musicbot = musicbot
        self.loop = loop
        self.host = ""
        self.port = 5005
        self.buf_size = 1024
        self.max_connections = 10
        self.connections = []
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
            print("[SOCKETSERVER] Socket received message: ***REMOVED******REMOVED***".format(msg))
            try:
                parts = msg.split(";")
                request = parts[0]
                server_id = parts[1]
                leftover = parts[2:]
            except:
                print("[SOCKETSERVER] Socket sent malformed message")
                break

            if request == "REQUEST" and leftover[0] == "SEND_INFORMATION":
                response = "INFORMATION;***REMOVED***artist***REMOVED***;***REMOVED***song_title***REMOVED***;***REMOVED***play_status***REMOVED***;***REMOVED***cover_url***REMOVED***;***REMOVED***progress***REMOVED***;***REMOVED***duration***REMOVED***;***REMOVED***volume***REMOVED***"
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                    if player.current_entry is None:
                        playing = "STOPPED"
                        duration = "0"
                        progress = "0"
                    else:
                        playing = "PLAYING" if player.is_playing else "PAUSED"
                        duration = str(player.current_entry.duration)
                        progress = str(player.progress)

                    volume = player.volume

                response = response.format(artist="AVICII", song_title="FOR A BETTER DAY", play_status=playing,
                                           cover_url="https://i.scdn.co/image/1e95e13d082e43c547dadd93808dceeb99f589cf", progress=progress, duration=duration, volume=volume)
                print("[SOCKETSERVER] Socket sent data")
                c_socket.send(response.encode("utf-8"))
            elif request == "COMMAND":
                if server_id in self.musicbot.players:
                    player = self.musicbot.players[server_id]
                else:
                    player = None

                if player is not None:
                    if leftover[0] == "PLAY_PAUSE":
                        if player.is_paused:
                            player.resume()
                        elif player.is_playing:
                            player.pause()
                    elif leftover[0] == "SKIP":
                        player.skip()
                    elif leftover[0] == "VOLUMECHANGE":
                        player.volume = float(leftover[1])

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

        c_socket.shutdown(SHUT_RDWR)
        c_socket.close()
