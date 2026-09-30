"""Pygame client. Run: python client.py [name] [host] [port]"""
import math
import queue
import random
import socket
import sys
import threading
import time

import pygame

from common import (World, encode, decode_lines, BLOCKS, TILE, WORLD_HEIGHT, is_solid,
                    AIR, GRASS, DIRT, STONE, WOOD, LEAVES, SAND, WATER, COAL, IRON, GOLD,
                    DIAMOND, PLANKS, BEDROCK, BRICK, GLASS)

NAME = sys.argv[1] if len(sys.argv) > 1 else f"player{random.randint(100, 999)}"
HOST = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 5555

WIN_W, WIN_H = 1024, 640
GRAVITY = 32.0
JUMP_V = 11.5
WALK_SPEED = 6.0
REACH = 5.0
PLAYER_W, PLAYER_H = 0.6, 1.8

HOTBAR = [DIRT, STONE, PLANKS, WOOD, SAND, BRICK, GLASS, LEAVES, COAL]
# what you receive when breaking a block
DROPS = {GRASS: DIRT, WOOD: WOOD, LEAVES: LEAVES, STONE: STONE, COAL: COAL,
         IRON: IRON, GOLD: GOLD, DIAMOND: DIAMOND, BRICK: BRICK, GLASS: GLASS}
for _b in HOTBAR:
    DROPS.setdefault(_b, _b)


# --------------------------------------------------------------------------
# Networking
# --------------------------------------------------------------------------
class Net:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.inbox = queue.Queue()
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        try:
            while self.alive:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                msgs, buf = decode_lines(buf)
                for m in msgs:
                    self.inbox.put(m)
        except OSError:
            pass
        self.alive = False

    def send(self, msg):
        try:
            self.sock.sendall(encode(msg))
        except OSError:
            self.alive = False


# --------------------------------------------------------------------------
# Textures
# --------------------------------------------------------------------------
def make_textures():
    tex = {}
    rng = random.Random(1)
    for b, info in BLOCKS.items():
        if info["color"] is None:
            continue
        s = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        base = info["color"]
        alpha = 150 if b in (WATER, GLASS) else 255
        s.fill((*base, alpha))
        for _ in range(40):  # speckle noise
            x, y = rng.randrange(TILE), rng.randrange(TILE)
            d = rng.randint(-18, 18)
            c = tuple(max(0, min(255, v + d)) for v in base)
            pygame.draw.rect(s, (*c, alpha), (x, y, 2, 2))
        if b == GRASS:
            pygame.draw.rect(s, (134, 96, 67), (0, 8, TILE, TILE - 8))
            for _ in range(30):
                x, y = rng.randrange(TILE), rng.randrange(8, TILE)
                pygame.draw.rect(s, (134 + rng.randint(-15, 15), 96, 67), (x, y, 2, 2))
        if b == WOOD:
            for i in range(0, TILE, 8):
                pygame.draw.line(s, (80, 62, 38), (i, 0), (i, TILE))
        if b == PLANKS:
            for i in range(0, TILE, 8):
                pygame.draw.line(s, (120, 92, 55), (0, i), (TILE, i))
        if b == BRICK:
            for row, y in enumerate(range(0, TILE, 8)):
                pygame.draw.line(s, (200, 200, 200), (0, y), (TILE, y))
                off = 8 if row % 2 else 0
                for x in range(off, TILE, 16):
                    pygame.draw.line(s, (200, 200, 200), (x, y), (x, y + 8))
        if b in (COAL, IRON, GOLD, DIAMOND):
            s.fill((*BLOCKS[STONE]["color"], 255))
            for _ in range(7):
                x, y = rng.randrange(TILE - 5), rng.randrange(TILE - 5)
                pygame.draw.rect(s, base, (x, y, 5, 5))
        if b == GLASS:
            pygame.draw.rect(s, (255, 255, 255, 220), (0, 0, TILE, TILE), 2)
        pygame.draw.rect(s, (0, 0, 0, 40), (0, 0, TILE, TILE), 1)
        tex[b] = s
    return tex


def make_player_sprite(color):
    w, h = int(PLAYER_W * TILE), int(PLAYER_H * TILE)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, (222, 180, 140), (2, 0, w - 4, 14))          # head
    pygame.draw.rect(s, (60, 40, 30), (2, 0, w - 4, 5))               # hair
    pygame.draw.rect(s, (30, 30, 30), (w - 8, 6, 3, 3))               # eye
    pygame.draw.rect(s, color, (0, 14, w, 24))                        # body
    pygame.draw.rect(s, (50, 50, 140), (1, 38, w // 2 - 1, h - 38))   # legs
    pygame.draw.rect(s, (50, 50, 140), (w // 2 + 1, 38, w // 2 - 2, h - 38))
    return s


# --------------------------------------------------------------------------
# Game
# --------------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption(f"2D Minecraft - {NAME}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("dejavusansmono,consolas,monospace", 16)
        self.big = pygame.font.SysFont("dejavusansmono,consolas,monospace", 28, bold=True)
        self.tex = make_textures()

        self.net = Net(HOST, PORT)
        self.net.send(dict(t="join", name=NAME))
        self.world = None
        self.my_id = None
        self.others = {}       # id -> dict(name, x, y, f, sprite)
        self.chat = []         # (time, text)
        self.typing = None     # None or str being typed

        self.px, self.py = 0.0, 0.0   # feet-centre position (blocks)
        self.vx = self.vy = 0.0
        self.on_ground = False
        self.facing = 1
        self.cam_x = self.cam_y = 0.0
        self.inventory = {b: 0 for b in HOTBAR}
        self.creative = False
        self.slot = 0
        self.mining = None     # (x, y, progress)
        self.last_pos_send = 0
        self.my_sprite = make_player_sprite((200, 60, 60))
        self.wait_for_welcome()

    # ---------------- network ----------------
    def wait_for_welcome(self):
        deadline = time.time() + 5
        while time.time() < deadline:
            self.process_net()
            if self.world:
                return
            time.sleep(0.02)
        raise SystemExit("Server did not respond.")

    def process_net(self):
        while True:
            try:
                m = self.net.inbox.get_nowait()
            except queue.Empty:
                return
            t = m["t"]
            if t == "welcome":
                self.my_id = m["id"]
                self.world = World(m["seed"])
                for x, y, b in m["changes"]:
                    self.world.set(x, y, b)
                self.px, self.py = m["x"], m["y"]
                for pid, p in m["players"].items():
                    self.add_other(int(pid), p)
            elif t == "pos":
                if m["id"] != self.my_id:
                    self.add_other(m["id"], m)
            elif t == "set":
                self.world.set(m["x"], m["y"], m["b"])
            elif t == "leave":
                self.others.pop(m["id"], None)
            elif t == "chat":
                self.chat.append((time.time(), f"<{m['name']}> {m['msg']}"))
                self.chat = self.chat[-8:]

    def add_other(self, pid, p):
        o = self.others.get(pid)
        if o is None:
            rng = random.Random(pid)
            col = (rng.randint(60, 220), rng.randint(60, 220), rng.randint(60, 220))
            o = dict(name=p["name"], sprite=make_player_sprite(col), f=1)
            self.others[pid] = o
        o["x"], o["y"] = p["x"], p["y"]
        o["f"] = p.get("f", o["f"])

    # ---------------- physics ----------------
    def collides(self, x, y):
        x0, x1 = math.floor(x - PLAYER_W / 2), math.floor(x + PLAYER_W / 2 - 1e-6)
        y0, y1 = math.floor(y - PLAYER_H), math.floor(y - 1e-6)
        for bx in range(x0, x1 + 1):
            for by in range(y0, y1 + 1):
                if is_solid(self.world.get(bx, by)):
                    return True
        return False

    def update_physics(self, dt):
        keys = pygame.key.get_pressed()
        move = 0
        if self.typing is None:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                move -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                move += 1
            if (keys[pygame.K_SPACE] or keys[pygame.K_w] or keys[pygame.K_UP]):
                in_water = self.world.get(int(math.floor(self.px)), int(math.floor(self.py - 0.5))) == WATER
                if self.on_ground:
                    self.vy = -JUMP_V
                elif in_water:
                    self.vy = max(self.vy - 40 * dt, -4)
        if move:
            self.facing = move
        self.vx = move * WALK_SPEED
        in_water = self.world.get(int(math.floor(self.px)), int(math.floor(self.py - 0.9))) == WATER
        self.vy += GRAVITY * dt * (0.3 if in_water else 1)
        self.vy = min(self.vy, 4 if in_water else 40)

        # x movement
        nx = self.px + self.vx * dt
        if not self.collides(nx, self.py):
            self.px = nx
        else:
            # try step up one block
            if self.on_ground and not self.collides(nx, self.py - 1) and not self.collides(self.px, self.py - 1):
                self.px, self.py = nx, self.py - 1
        # y movement
        ny = self.py + self.vy * dt
        self.on_ground = False
        if not self.collides(self.px, ny):
            self.py = ny
        else:
            if self.vy > 0:
                self.py = math.floor(ny) - 1e-4   # snap feet to top of block
                self.on_ground = True
            else:
                self.py = math.ceil(ny - PLAYER_H) + PLAYER_H + 1e-4
            self.vy = 0

        if self.py > WORLD_HEIGHT + 5:  # fell out
            self.px, self.py = self.world.spawn_point(int(self.px))
            self.vy = 0

        # camera
        tx = self.px * TILE - WIN_W / 2
        ty = (self.py - PLAYER_H / 2) * TILE - WIN_H / 2
        self.cam_x += (tx - self.cam_x) * min(1, dt * 10)
        self.cam_y += (ty - self.cam_y) * min(1, dt * 10)

    # ---------------- interaction ----------------
    def mouse_block(self):
        mx, my = pygame.mouse.get_pos()
        return math.floor((mx + self.cam_x) / TILE), math.floor((my + self.cam_y) / TILE)

    def in_reach(self, bx, by):
        return math.hypot(bx + 0.5 - self.px, by + 0.5 - (self.py - PLAYER_H / 2)) <= REACH

    def update_mining(self, dt):
        buttons = pygame.mouse.get_pressed()
        if self.typing is not None or not buttons[0]:
            self.mining = None
            return
        bx, by = self.mouse_block()
        b = self.world.get(bx, by)
        hard = BLOCKS[b]["hard"]
        if b in (AIR, WATER) or hard < 0 or not self.in_reach(bx, by):
            self.mining = None
            return
        if self.mining is None or self.mining[0] != (bx, by):
            self.mining = [(bx, by), 0.0]
        self.mining[1] += dt / (hard * (0.25 if self.creative else 1))
        if self.mining[1] >= 1:
            drop = DROPS.get(b)
            if drop in self.inventory:
                self.inventory[drop] += 1
            self.world.set(bx, by, AIR)
            self.net.send(dict(t="set", x=bx, y=by, b=AIR))
            self.mining = None

    def place_block(self):
        bx, by = self.mouse_block()
        block = HOTBAR[self.slot]
        if not self.in_reach(bx, by):
            return
        if self.world.get(bx, by) not in (AIR, WATER):
            return
        if not self.creative and self.inventory[block] <= 0:
            return
        # don't place inside self or others
        if is_solid(block):
            if self.overlaps_player(bx, by, self.px, self.py):
                return
            for o in self.others.values():
                if self.overlaps_player(bx, by, o["x"], o["y"]):
                    return
        # must touch an existing block
        if not any(self.world.get(bx + dx, by + dy) not in (AIR, WATER)
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            return
        if not self.creative:
            self.inventory[block] -= 1
        self.world.set(bx, by, block)
        self.net.send(dict(t="set", x=bx, y=by, b=block))

    @staticmethod
    def overlaps_player(bx, by, px, py):
        return (bx < px + PLAYER_W / 2 and bx + 1 > px - PLAYER_W / 2 and
                by < py and by + 1 > py - PLAYER_H)

    # ---------------- drawing ----------------
    def draw(self):
        scr = self.screen
        # sky gradient
        scr.fill((120, 175, 235))
        cx, cy = int(self.cam_x), int(self.cam_y)
        x0, x1 = cx // TILE - 1, (cx + WIN_W) // TILE + 1
        y0, y1 = max(0, cy // TILE - 1), min(WORLD_HEIGHT - 1, (cy + WIN_H) // TILE + 1)
        for bx in range(x0, x1 + 1):
            surf = self.world.surface_height(bx)
            for by in range(y0, y1 + 1):
                b = self.world.get(bx, by)
                if b == AIR:
                    if by > surf:   # cave / dug-out area: dark backdrop
                        pygame.draw.rect(scr, (45, 40, 38), (bx * TILE - cx, by * TILE - cy, TILE, TILE))
                    continue
                scr.blit(self.tex[b], (bx * TILE - cx, by * TILE - cy))

        # other players
        for o in self.others.values():
            self.draw_player(o["sprite"], o["x"], o["y"], o["f"], o["name"])
        self.draw_player(self.my_sprite, self.px, self.py, self.facing, NAME)

        # mining crack + target outline
        bx, by = self.mouse_block()
        rect = pygame.Rect(bx * TILE - cx, by * TILE - cy, TILE, TILE)
        col = (255, 255, 255) if self.in_reach(bx, by) else (255, 80, 80)
        pygame.draw.rect(scr, col, rect, 2)
        if self.mining:
            p = min(1, self.mining[1])
            (mx, my) = self.mining[0]
            r = pygame.Rect(mx * TILE - cx, my * TILE - cy, TILE, TILE)
            for i in range(int(p * 8)):
                pygame.draw.line(scr, (20, 20, 20),
                                 (r.x + (i * 7) % TILE, r.y + (i * 11) % TILE),
                                 (r.x + (i * 13 + 9) % TILE, r.y + (i * 5 + 13) % TILE), 2)
            pygame.draw.rect(scr, (255, 220, 0), (r.x, r.bottom - 4, int(TILE * p), 4))

        self.draw_hud()
        pygame.display.flip()

    def draw_player(self, sprite, x, y, f, name):
        s = sprite if f >= 0 else pygame.transform.flip(sprite, True, False)
        sx = (x - PLAYER_W / 2) * TILE - self.cam_x
        sy = (y - PLAYER_H) * TILE - self.cam_y
        self.screen.blit(s, (sx, sy))
        label = self.font.render(name, True, (255, 255, 255))
        self.screen.blit(label, (sx + sprite.get_width() / 2 - label.get_width() / 2, sy - 18))

    def draw_hud(self):
        scr = self.screen
        # hotbar
        n = len(HOTBAR)
        slot_w = 44
        hx = WIN_W // 2 - n * slot_w // 2
        hy = WIN_H - 54
        for i, b in enumerate(HOTBAR):
            r = pygame.Rect(hx + i * slot_w, hy, slot_w, slot_w)
            pygame.draw.rect(scr, (40, 40, 40, 200), r)
            pygame.draw.rect(scr, (255, 255, 255) if i == self.slot else (110, 110, 110), r, 3)
            scr.blit(self.tex[b], (r.x + 6, r.y + 6))
            cnt = "∞" if self.creative else str(self.inventory[b])
            t = self.font.render(cnt, True, (255, 255, 255))
            scr.blit(t, (r.right - t.get_width() - 3, r.bottom - t.get_height() - 1))
        name = BLOCKS[HOTBAR[self.slot]]["name"]
        t = self.font.render(name, True, (255, 255, 255))
        scr.blit(t, (WIN_W // 2 - t.get_width() // 2, hy - 20))

        # info
        mode = "CREATIVE" if self.creative else "SURVIVAL"
        info = f"{mode}  x={self.px:.1f} y={self.py:.1f}  players={len(self.others) + 1}  fps={self.clock.get_fps():.0f}"
        scr.blit(self.font.render(info, True, (255, 255, 255)), (8, 8))
        if not self.net.alive:
            t = self.big.render("DISCONNECTED", True, (255, 60, 60))
            scr.blit(t, (WIN_W // 2 - t.get_width() // 2, 60))

        # chat
        now = time.time()
        y = WIN_H - 80
        for ts, text in reversed(self.chat):
            if now - ts > 12 and self.typing is None:
                continue
            t = self.font.render(text, True, (255, 255, 255))
            bg = pygame.Surface((t.get_width() + 8, t.get_height() + 2), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 120))
            scr.blit(bg, (8, y))
            scr.blit(t, (12, y + 1))
            y -= 20
        if self.typing is not None:
            t = self.font.render("> " + self.typing + "_", True, (255, 255, 0))
            bg = pygame.Surface((WIN_W - 16, t.get_height() + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            scr.blit(bg, (8, WIN_H - 100 + 70))
            scr.blit(t, (12, WIN_H - 100 + 72))

    # ---------------- main loop ----------------
    def run(self):
        while True:
            dt = min(self.clock.tick(60) / 1000, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN:
                    if self.typing is not None:
                        if e.key == pygame.K_RETURN:
                            if self.typing.strip():
                                self.net.send(dict(t="chat", msg=self.typing.strip()))
                            self.typing = None
                        elif e.key == pygame.K_ESCAPE:
                            self.typing = None
                        elif e.key == pygame.K_BACKSPACE:
                            self.typing = self.typing[:-1]
                        elif e.unicode and e.unicode.isprintable():
                            self.typing += e.unicode
                        continue
                    if e.key == pygame.K_ESCAPE:
                        return
                    if e.key == pygame.K_t:
                        self.typing = ""
                    elif e.key == pygame.K_c:
                        self.creative = not self.creative
                    elif pygame.K_1 <= e.key <= pygame.K_9:
                        self.slot = min(e.key - pygame.K_1, len(HOTBAR) - 1)
                if e.type == pygame.MOUSEWHEEL:
                    self.slot = (self.slot - e.y) % len(HOTBAR)
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3 and self.typing is None:
                    self.place_block()

            self.process_net()
            self.update_physics(dt)
            self.update_mining(dt)
            now = time.time()
            if now - self.last_pos_send > 1 / 20:
                self.last_pos_send = now
                self.net.send(dict(t="pos", x=round(self.px, 2), y=round(self.py, 2), f=self.facing))
            self.draw()


if __name__ == "__main__":
    try:
        Game().run()
    except ConnectionRefusedError:
        print(f"Could not connect to {HOST}:{PORT}. Is the server running?")
    finally:
        pygame.quit()
