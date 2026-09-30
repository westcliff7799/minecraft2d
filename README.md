# 2D Multiplayer Minecraft (Python + pygame)

A small side-view Minecraft clone with an authoritative TCP server and a pygame client.
Infinite procedurally generated world (hills, lakes, trees, caves, ores), block mining
and placing synced between all players, and in-game chat.

## Requirements

```
pip install pygame
```

## Running

Start the server (default port 5555, random seed):

```
python server.py [port] [seed]
```

Then start one client per player:

```
python client.py [name] [host] [port]
# e.g.
python client.py Steve 127.0.0.1 5555
```

Other machines on the LAN connect with the server's IP address as `host`.

## Controls

| Key / Mouse          | Action                              |
|----------------------|-------------------------------------|
| A / D or ← / →       | Move                                |
| Space / W / ↑        | Jump (swim in water)                |
| Left mouse (hold)    | Mine block under the cursor         |
| Right mouse          | Place selected block                |
| 1–9 / mouse wheel    | Select hotbar slot                  |
| C                    | Toggle creative mode (infinite blocks, fast mining) |
| T                    | Open chat (Enter to send, Esc to cancel) |
| Esc                  | Quit                                |

Mined blocks go into your inventory (shown as counts on the hotbar); ores like coal,
iron, gold and diamond are collected too. Bedrock cannot be broken.

## Files

- `common.py` – block definitions, deterministic world generator, JSON-lines protocol
- `server.py` – threaded TCP server; tracks players, validates and broadcasts block edits and chat
- `client.py` – pygame client: rendering, physics, mining/placing, networking thread

## How it works

The world is generated from a seed identical on server and clients, so only the seed and
the list of player edits are transmitted when joining. Afterwards every block change is
sent to the server, which checks reach and broadcasts it to all players. Player positions
are sent 20 times per second.
