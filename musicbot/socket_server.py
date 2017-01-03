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

    def shutdown(self):
        self.main_socket.shutdown(SHUT_RDWR)
        self.main_socket.close()
        self.stop_threads = True

    def connection_accepter(self):
        while not self.stop_threads:
            print(len(self.connections))
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

            print(msg)

        to_delete = None
        for i in range(len(self.connections)):
            if self.connections[i][1] == c_socket:
                to_delete = self.connections[i]
                print("[SOCKETSERVER] Shutting down connection: " + str(self.connections[i][2]))

        if to_delete is not None:
            self.connections.remove(to_delete)
        else:
            print("[SOCKETSERVER] Couldn't remove this connection from list")

        c_socket.shutdown(SHUT_RDWR)
        c_socket.close()
