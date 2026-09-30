"""Authoritative game server. Run: python server.py [port] [seed]"""
import socket
import sys
import threading
import time
import random

from common import World, encode, decode_lines, BLOCKS, BEDROCK, AIR

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else random.randrange(1 << 30)


class Server:
    def __init__(self):
        self.world = World(SEED)
        self.clients = {}       # id -> Client
        self.lock = threading.Lock()
        self.next_id = 1

    def broadcast(self, msg, exclude=None):
        data = encode(msg)
        with self.lock:
            targets = [c for c in self.clients.values() if c.id != exclude]
        for c in targets:
            c.send_raw(data)

    def handle_client(self, sock, addr):
        client = Client(self, sock, addr)
        client.run()


class Client:
    def __init__(self, server, sock, addr):
        self.server = server
        self.sock = sock
        self.addr = addr
        self.id = None
        self.name = "?"
        self.x, self.y = 0.0, 0.0
        self.send_lock = threading.Lock()

    def send(self, msg):
        self.send_raw(encode(msg))

    def send_raw(self, data):
        try:
            with self.send_lock:
                self.sock.sendall(data)
        except OSError:
            pass

    def run(self):
        srv = self.server
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                msgs, buf = decode_lines(buf)
                for m in msgs:
                    self.handle(m)
        except (ConnectionResetError, OSError):
            pass
        finally:
            self.disconnect()

    def handle(self, m):
        srv = self.server
        t = m.get("t")
        if t == "join":
            self.name = str(m.get("name", "player"))[:16]
            with srv.lock:
                self.id = srv.next_id
                srv.next_id += 1
                others = {c.id: dict(name=c.name, x=c.x, y=c.y)
                          for c in srv.clients.values()}
                srv.clients[self.id] = self
            self.x, self.y = srv.world.spawn_point(random.randint(-8, 8))
            self.send(dict(t="welcome", id=self.id, seed=srv.world.seed,
                           x=self.x, y=self.y,
                           changes=[[x, y, b] for (x, y), b in srv.world.changes.items()],
                           players=others))
            srv.broadcast(dict(t="pos", id=self.id, name=self.name,
                               x=self.x, y=self.y), exclude=self.id)
            srv.broadcast(dict(t="chat", name="*", msg=f"{self.name} joined"))
            print(f"[+] {self.name} ({self.addr[0]}) joined as #{self.id}")
        elif self.id is None:
            return
        elif t == "pos":
            self.x, self.y = float(m["x"]), float(m["y"])
            srv.broadcast(dict(t="pos", id=self.id, name=self.name,
                               x=self.x, y=self.y, f=m.get("f", 1)), exclude=self.id)
        elif t == "set":
            x, y, b = int(m["x"]), int(m["y"]), int(m["b"])
            if b not in BLOCKS:
                return
            cur = srv.world.get(x, y)
            if cur == BEDROCK:
                return
            # reach check: must be within 6 blocks of player
            if abs(x + 0.5 - self.x) > 6 or abs(y + 0.5 - self.y) > 6:
                return
            srv.world.set(x, y, b)
            srv.broadcast(dict(t="set", x=x, y=y, b=b))
        elif t == "chat":
            msg = str(m.get("msg", ""))[:120]
            if msg:
                srv.broadcast(dict(t="chat", name=self.name, msg=msg))

    def disconnect(self):
        srv = self.server
        try:
            self.sock.close()
        except OSError:
            pass
        if self.id is not None:
            with srv.lock:
                srv.clients.pop(self.id, None)
            srv.broadcast(dict(t="leave", id=self.id))
            srv.broadcast(dict(t="chat", name="*", msg=f"{self.name} left"))
            print(f"[-] {self.name} left")


def main():
    srv = Server()
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind((HOST, PORT))
    ls.listen()
    print(f"Server listening on {HOST}:{PORT}  (seed {SEED})")
    try:
        while True:
            sock, addr = ls.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=srv.handle_client, args=(sock, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
