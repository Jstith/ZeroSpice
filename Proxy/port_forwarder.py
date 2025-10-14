import socket
import threading


class PortForwarder:
    def __init__(self, local_host, local_port, remote_host, remote_port):
        self.local_host = local_host
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.server = None
        self.thread = None
        self.running = False

    def start(self):
        self.running = True

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.local_host, self.local_port))
        self.server.listen(5)

        def accept_loop():
            while self.running:
                try:
                    client, addr = self.server.accept()
                    t = threading.Thread(target=self.forward_connection, args=(client,))
                    t.daemon = True
                    t.start()
                except:
                    break

        self.thread = threading.Thread(target=accept_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        if self.server:
            self.server.close()

    def forward_connection(self, client_sock):
        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((self.remote_host, self.remote_port))

            def forward(src, dst):
                try:
                    while self.running:
                        data = src.recv(4096)
                        if not data:
                            break
                        dst.sendall(data)
                except:
                    pass
                finally:
                    try:
                        src.close()
                    except:
                        pass
                    try:
                        dst.close()
                    except:
                        pass

            t1 = threading.Thread(target=forward, args=(client_sock, remote))
            t2 = threading.Thread(target=forward, args=(remote, client_sock))
            t1.daemon = True
            t2.daemon = True
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        except Exception as e:
            print(f"Error forwarding traffic: {e}")

    ### ----------------
    ### Helper functions
    ### ----------------

    def is_running(self):
        return self.running

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.stop()
        return False
