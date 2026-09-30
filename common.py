"""Shared code between server and client: block types, world generation, protocol."""
import json
import math
import random

WORLD_HEIGHT = 64
SEA_LEVEL = 34
TILE = 32

# Block ids
AIR, GRASS, DIRT, STONE, WOOD, LEAVES, SAND, WATER, COAL, IRON, GOLD, DIAMOND, PLANKS, BEDROCK, BRICK, GLASS = range(16)

BLOCKS = {
    AIR:     dict(name="Air",     color=None,            solid=False, hard=0),
    GRASS:   dict(name="Grass",   color=(95, 159, 53),   solid=True,  hard=0.5),
    DIRT:    dict(name="Dirt",    color=(134, 96, 67),   solid=True,  hard=0.5),
    STONE:   dict(name="Stone",   color=(125, 125, 125), solid=True,  hard=1.2),
    WOOD:    dict(name="Wood",    color=(102, 81, 50),   solid=False, hard=0.9),
    LEAVES:  dict(name="Leaves",  color=(48, 120, 40),   solid=True,  hard=0.2),
    SAND:    dict(name="Sand",    color=(219, 211, 160), solid=True,  hard=0.5),
    WATER:   dict(name="Water",   color=(50, 90, 210),   solid=False, hard=0),
    COAL:    dict(name="Coal",    color=(60, 60, 60),    solid=True,  hard=1.6),
    IRON:    dict(name="Iron",    color=(190, 170, 150), solid=True,  hard=2.0),
    GOLD:    dict(name="Gold",    color=(235, 200, 60),  solid=True,  hard=2.2),
    DIAMOND: dict(name="Diamond", color=(90, 230, 230),  solid=True,  hard=2.6),
    PLANKS:  dict(name="Planks",  color=(178, 142, 88),  solid=True,  hard=0.8),
    BEDROCK: dict(name="Bedrock", color=(30, 30, 30),    solid=True,  hard=-1),
    BRICK:   dict(name="Brick",   color=(150, 70, 60),   solid=True,  hard=1.4),
    GLASS:   dict(name="Glass",   color=(200, 230, 240), solid=True,  hard=0.3),
}

def is_solid(b):
    return BLOCKS[b]["solid"]


# --------------------------------------------------------------------------
# World generation (deterministic from seed; identical on server and clients)
# --------------------------------------------------------------------------
def _hash(seed, *vals):
    """Integer mixing hash (murmur3-style finalizer) - well distributed."""
    M = 0xFFFFFFFF
    h = (seed * 0x9E3779B1) & M
    for v in vals:
        h ^= v & M
        h = (h * 0x85EBCA6B) & M
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & M
        h ^= h >> 16
    return h

def _noise1(seed, x, freq):
    """Smooth 1D value noise in [-1, 1]."""
    xf = x / freq
    x0 = math.floor(xf)
    t = xf - x0
    t = t * t * (3 - 2 * t)
    a = (_hash(seed, x0) % 10000) / 5000 - 1
    b = (_hash(seed, x0 + 1) % 10000) / 5000 - 1
    return a + (b - a) * t


class World:
    def __init__(self, seed):
        self.seed = seed
        self.columns = {}   # x -> list of block ids (index 0 = top)
        self.changes = {}   # (x, y) -> block id  (player edits)

    def surface_height(self, x):
        h = SEA_LEVEL - 5          # y grows downward: smaller = higher
        h += _noise1(self.seed, x, 40) * 12
        h += _noise1(self.seed + 1, x, 12) * 4
        h += _noise1(self.seed + 2, x, 5) * 1.5
        return int(h)

    def _gen_column(self, x):
        col = [AIR] * WORLD_HEIGHT
        top = self.surface_height(x)
        rng = random.Random(_hash(self.seed, x, 777))
        for y in range(WORLD_HEIGHT):
            depth = y - top
            if y >= WORLD_HEIGHT - 1 or (y >= WORLD_HEIGHT - 3 and rng.random() < 0.5):
                col[y] = BEDROCK
            elif depth < 0:
                col[y] = WATER if y >= SEA_LEVEL else AIR
            elif depth == 0:
                col[y] = SAND if top >= SEA_LEVEL - 1 else GRASS
            elif depth < 4:
                col[y] = SAND if top >= SEA_LEVEL - 1 else DIRT
            else:
                r = rng.random()
                if depth > 20 and r < 0.008:
                    col[y] = DIAMOND
                elif depth > 12 and r < 0.02:
                    col[y] = GOLD
                elif depth > 6 and r < 0.05:
                    col[y] = IRON
                elif r < 0.10:
                    col[y] = COAL
                else:
                    col[y] = STONE
                # caves
                c = _noise1(self.seed + 5, x * 3 + y * 7, 6) + _noise1(self.seed + 6, x + y * 13, 9)
                if depth > 5 and c > 0.9 and col[y] != BEDROCK:
                    col[y] = AIR
        self.columns[x] = col
        # trees (placed into neighbouring columns as well)
        if col[top] == GRASS and rng.random() < 0.12:
            self._tree(x, top)

    def _tree(self, x, top):
        h = 4 + (_hash(self.seed, x, 99) % 3)
        for dy in range(1, h + 1):
            self._set_gen(x, top - dy, WOOD)
        for dx in range(-2, 3):
            for dy in range(h - 1, h + 3):
                if abs(dx) == 2 and dy == h + 2:
                    continue
                if dx == 0 and dy <= h:
                    continue
                self._set_gen(x + dx, top - dy, LEAVES)

    def _set_gen(self, x, y, b):
        if 0 <= y < WORLD_HEIGHT:
            if x not in self.columns:
                self._gen_column(x)
            if self.columns[x][y] == AIR:
                self.columns[x][y] = b

    def get(self, x, y):
        if y < 0 or y >= WORLD_HEIGHT:
            return AIR if y < 0 else BEDROCK
        if (x, y) in self.changes:
            return self.changes[(x, y)]
        if x not in self.columns:
            self._gen_column(x)
        return self.columns[x][y]

    def set(self, x, y, b):
        if 0 <= y < WORLD_HEIGHT:
            self.changes[(x, y)] = b

    def spawn_point(self, x=0):
        # walk outward until we find dry land
        for d in range(0, 200):
            for sx in (x + d, x - d):
                if self.surface_height(sx) < SEA_LEVEL - 1:
                    return sx + 0.5, self.surface_height(sx) - 0.01
        return x + 0.5, self.surface_height(x) - 0.01


# --------------------------------------------------------------------------
# Protocol: newline-delimited JSON
# --------------------------------------------------------------------------
def encode(msg):
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode()

def decode_lines(buffer):
    """Split a bytes buffer into complete JSON messages; returns (msgs, remainder)."""
    msgs = []
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        if line.strip():
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return msgs, buffer
