#!/usr/bin/env python3
"""Signal Clash — a small turn-based strategy game for humans and agents.

2-4 players claim, reinforce and attack cells on a 5x5 grid. Humans play in a
browser; agents use the JSON API. State is in memory; run one process.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))
MAX_ROUNDS = 15
WIN_CELLS = 10
MAX_ENERGY = 5
COLORS = ["#5eead4", "#f9a8d4", "#fcd34d", "#93c5fd"]
BOT_NAMES = ["Bot Aurora", "Bot Basalt", "Bot Cinder"]
START = {
    2: [(0, 0), (4, 4)],
    3: [(0, 0), (4, 0), (2, 4)],
    4: [(0, 0), (4, 0), (0, 4), (4, 4)],
}

GAMES: dict[str, dict] = {}
LOCK = threading.Lock()


def cell_key(r: int, c: int) -> str:
    return f"{r},{c}"


def parse_cell(key: str):
    try:
        r, c = key.split(",")
        r, c = int(r), int(c)
        if 0 <= r < 5 and 0 <= c < 5:
            return r, c
    except Exception:
        pass
    return None


def adjacent(a: str, b: str) -> bool:
    pa, pb = parse_cell(a), parse_cell(b)
    if not pa or not pb:
        return False
    return abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) == 1


def empty_board() -> dict[str, dict]:
    """All 25 cells exist from turn one; empty cells have no owner and 0 strength."""
    return {cell_key(r, c): {"owner": None, "strength": 0} for r in range(5) for c in range(5)}


def ensure_board(game: dict) -> None:
    """Backfill missing cells (keeps games created by older versions playable)."""
    for r in range(5):
        for c in range(5):
            game["cells"].setdefault(cell_key(r, c), {"owner": None, "strength": 0})


def owned_cells(game: dict, pid: str) -> list[str]:
    return [k for k, v in game["cells"].items() if v["owner"] == pid]


def player(game: dict, pid: str):
    return next((p for p in game["players"] if p["id"] == pid), None)


def current(game: dict):
    return game["players"][game["turn"] % len(game["players"])]


def legal_moves(game: dict, pid: str) -> list[dict]:
    if game["status"] != "active" or current(game)["id"] != pid:
        return []
    p = player(game, pid)
    if not p:
        return []
    moves = [{"action": "charge"}]
    owned = owned_cells(game, pid)
    empty = [k for k, v in game["cells"].items() if v["owner"] is None]
    for src in owned:
        for dst in empty:
            if adjacent(src, dst) and p["energy"] >= 1:
                moves.append({"action": "claim", "cell": dst, "source": src})
        if game["cells"][src]["strength"] < 5 and p["energy"] >= 1:
            moves.append({"action": "reinforce", "cell": src})
        for dst, v in game["cells"].items():
            if v["owner"] is not None and v["owner"] != pid and adjacent(src, dst) and p["energy"] >= 2:
                moves.append({"action": "attack", "cell": dst, "source": src})
    return moves


def auto_bot_move(game: dict):
    """A simple, decent bot: attack the weakest adjacent enemy, else claim, else reinforce/charge."""
    pid = current(game)["id"]
    p = player(game, pid)
    owned = owned_cells(game, pid)
    attacks = []
    for src in owned:
        for dst, v in game["cells"].items():
            if v["owner"] not in (None, pid) and adjacent(src, dst):
                attacks.append((v["strength"], src, dst))
    if attacks and p["energy"] >= 2:
        attacks.sort()
        _, src, dst = attacks[0]
        return apply_move(game, pid, "attack", dst, src)
    empty = [k for k, v in game["cells"].items() if v["owner"] is None]
    claims = []
    for src in owned:
        for dst in empty:
            if adjacent(src, dst):
                claims.append((dst, src))
    if claims and p["energy"] >= 1:
        claims.sort()
        dst, src = claims[0]
        return apply_move(game, pid, "claim", dst, src)
    if owned and p["energy"] >= 1:
        low = min(owned, key=lambda k: game["cells"][k]["strength"])
        if game["cells"][low]["strength"] < 5:
            return apply_move(game, pid, "reinforce", low, None)
    return apply_move(game, pid, "charge", None, None)


def finish(game: dict, reason: str):
    game["status"] = "finished"
    if reason == "rounds":
        game["round"] = MAX_ROUNDS
    best_score = None
    leaders = []
    for p in game["players"]:
        cells = owned_cells(game, p["id"])
        strength = sum(game["cells"][k]["strength"] for k in cells)
        score = (len(cells), strength, p["energy"])
        if best_score is None or score > best_score:
            best_score, leaders = score, [p]
        elif score == best_score:
            leaders.append(p)
    # A genuine tie after cells, strength and energy is a draw.
    game["winner"] = leaders[0]["id"] if len(leaders) == 1 else None
    game["log"].append({"at": int(time.time()), "kind": "finish", "reason": reason, "winner": game["winner"]})


def apply_move(game: dict, pid: str, action: str, cell: str | None, source: str | None):
    if game["status"] != "active":
        raise ValueError("game is not active")
    if current(game)["id"] != pid:
        raise ValueError("not your turn")
    p = player(game, pid)
    if not p:
        raise ValueError("unknown player")
    if action == "charge":
        p["energy"] = min(MAX_ENERGY, p["energy"] + 2)
        game["log"].append({"at": int(time.time()), "round": game["round"], "player": pid, "action": "charge", "energy": p["energy"]})
    elif action == "claim":
        if not cell or not parse_cell(cell):
            raise ValueError("cell required")
        if game["cells"][cell]["owner"] is not None:
            raise ValueError("cell is not empty")
        owned = owned_cells(game, pid)
        if not any(adjacent(src, cell) for src in owned):
            raise ValueError("cell is not adjacent to your territory")
        if p["energy"] < 1:
            raise ValueError("not enough energy")
        game["cells"][cell] = {"owner": pid, "strength": 1}
        p["energy"] -= 1
        game["log"].append({"at": int(time.time()), "round": game["round"], "player": pid, "action": "claim", "cell": cell})
    elif action == "reinforce":
        if not cell or game["cells"].get(cell, {}).get("owner") != pid:
            raise ValueError("reinforce needs one of your cells")
        if game["cells"][cell]["strength"] >= 5:
            raise ValueError("cell is already at max strength")
        if p["energy"] < 1:
            raise ValueError("not enough energy")
        game["cells"][cell]["strength"] += 1
        p["energy"] -= 1
        game["log"].append({"at": int(time.time()), "round": game["round"], "player": pid, "action": "reinforce", "cell": cell})
    elif action == "attack":
        if not cell or not source:
            raise ValueError("attack needs cell and source")
        if game["cells"].get(source, {}).get("owner") != pid:
            raise ValueError("source must be your cell")
        if game["cells"].get(cell, {}).get("owner") in (None, pid):
            raise ValueError("target must be an enemy cell")
        if not adjacent(source, cell):
            raise ValueError("target must be adjacent to source")
        if p["energy"] < 2:
            raise ValueError("not enough energy")
        roll = random.randint(1, 3)
        src_strength = game["cells"][source]["strength"]
        dst_strength = game["cells"][cell]["strength"]
        won = src_strength + roll > dst_strength
        if won:
            game["cells"][cell] = {"owner": pid, "strength": 1}
        else:
            game["cells"][source]["strength"] = max(1, src_strength - 1)
        p["energy"] -= 2
        game["log"].append({"at": int(time.time()), "round": game["round"], "player": pid, "action": "attack", "cell": cell, "source": source, "roll": roll, "won": won})
    else:
        raise ValueError("unknown action")

    # Win check: control WIN_CELLS of the 25 cells, or every opponent has no cells.
    my_cells = len(owned_cells(game, pid))
    opponents = [x for x in game["players"] if x["id"] != pid]
    if my_cells >= WIN_CELLS or all(len(owned_cells(game, x["id"])) == 0 for x in opponents):
        finish(game, "majority")
        return snapshot(game)
    # Advance past eliminated players; the round rolls over when turn 0 is reached.
    for _ in range(len(game["players"]) * 2):
        game["turn"] = (game["turn"] + 1) % len(game["players"])
        if game["turn"] == 0:
            game["round"] += 1
        if owned_cells(game, current(game)["id"]):
            break
    if game["round"] > MAX_ROUNDS:
        finish(game, "rounds")
        return snapshot(game)
    # Run bots until it is a human's turn (or the game ends).
    guard = 0
    while game["status"] == "active" and current(game)["bot"] and guard < 20:
        guard += 1
        auto_bot_move(game)
    return snapshot(game)


def snapshot(game: dict):
    return {
        "id": game["id"],
        "code": game["code"],
        "status": game["status"],
        "round": game["round"],
        "max_rounds": MAX_ROUNDS,
        "win_cells": WIN_CELLS,
        "turn": current(game)["id"] if game["status"] == "active" else None,
        "players": [
            {
                "id": p["id"],
                "name": p["name"],
                "color": p["color"],
                "energy": p["energy"],
                "cells": len(owned_cells(game, p["id"])),
                "strength": sum(game["cells"][k]["strength"] for k in owned_cells(game, p["id"])),
                "bot": p["bot"],
            }
            for p in game["players"]
        ],
        "cells": game["cells"],
        "winner": game["winner"],
        "log_tail": game["log"][-20:],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SignalClash/1.0"

    def _send(self, status: int, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode())
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"")

    def _body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (ROOT / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send(200, {"ok": True, "games": len(GAMES)})
            return
        if path.startswith("/api/games/"):
            parts = path.strip("/").split("/")
            gid = parts[2] if len(parts) > 2 else ""
            game = GAMES.get(gid)
            if not game:
                self._send(404, {"error": "game not found"})
                return
            if len(parts) == 3:
                self._send(200, snapshot(game))
                return
            if len(parts) == 4 and parts[3] == "log":
                self._send(200, {"id": gid, "log": game["log"]})
                return
            if len(parts) == 4 and parts[3] == "legal":
                qs = parse_qs(urlparse(self.path).query)
                pid = (qs.get("player_id") or [""])[0]
                if not pid:
                    self._send(400, {"error": "player_id query parameter is required"})
                    return
                if not player(game, pid):
                    self._send(404, {"error": "unknown player"})
                    return
                self._send(200, {
                    "moves": legal_moves(game, pid),
                    "status": game["status"],
                    "turn": current(game)["id"] if game["status"] == "active" else None,
                    "win_cells": WIN_CELLS,
                })
                return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            self._post()
        except Exception as exc:  # keep the API JSON even on an unexpected bug
            print(f"POST {self.path} failed: {exc!r}")
            self._send(500, {"error": "internal server error"})

    def _post(self):
        path = urlparse(self.path).path
        body = self._body()
        with LOCK:
            if not isinstance(body, dict):
                self._send(400, {"error": "body must be a JSON object"})
                return
            if path == "/api/games":
                try:
                    players = int(body.get("players", 2))
                except (TypeError, ValueError):
                    self._send(400, {"error": "players must be 2, 3, or 4"})
                    return
                players = max(2, min(4, players))
                name = str(body.get("name") or "Player")[:32]
                gid = secrets.token_urlsafe(6)
                code = gid
                colors = COLORS[:players]
                starts = START[players]
                cells = empty_board()
                cells[cell_key(*starts[0])] = {"owner": "p1", "strength": 1}
                game = {
                    "id": gid,
                    "code": code,
                    "max_players": players,
                    "status": "lobby",
                    "round": 1,
                    "turn": 0,
                    "players": [
                        {"id": "p1", "name": name, "color": colors[0], "energy": 3, "bot": False}
                    ],
                    "cells": cells,
                    "log": [],
                    "winner": None,
                }
                GAMES[gid] = game
                self._send(200, {"game_id": gid, "join_code": code, "player_id": "p1", "state": snapshot(game)})
                return
            if path.startswith("/api/games/") and path.endswith("/join"):
                gid = path.strip("/").split("/")[2]
                game = GAMES.get(gid)
                if not game:
                    self._send(404, {"error": "game not found"})
                    return
                if game["status"] != "lobby":
                    self._send(400, {"error": "game already started"})
                    return
                if len(game["players"]) >= game["max_players"]:
                    self._send(400, {"error": "game is full"})
                    return
                ensure_board(game)
                pid = f"p{len(game['players']) + 1}"
                color = COLORS[len(game["players"])]
                start = START[game["max_players"]][len(game["players"])]
                game["players"].append({"id": pid, "name": str(body.get("name") or f"Player {pid}")[:32], "color": color, "energy": 3, "bot": False})
                game["cells"][cell_key(*start)] = {"owner": pid, "strength": 1}
                self._send(200, {"game_id": gid, "player_id": pid, "state": snapshot(game)})
                return
            if path.startswith("/api/games/") and path.endswith("/start"):
                gid = path.strip("/").split("/")[2]
                game = GAMES.get(gid)
                if not game:
                    self._send(404, {"error": "game not found"})
                    return
                if game["status"] != "lobby":
                    self._send(400, {"error": "game already started"})
                    return
                ensure_board(game)
                while len(game["players"]) < game["max_players"]:
                    pid = f"p{len(game['players']) + 1}"
                    color = COLORS[len(game["players"])]
                    start = START[game["max_players"]][len(game["players"])]
                    used = {p["name"] for p in game["players"]}
                    bot_name = next((n for n in BOT_NAMES if n not in used), f"Bot {pid.upper()}")
                    game["players"].append({"id": pid, "name": bot_name, "color": color, "energy": 3, "bot": True})
                    game["cells"][cell_key(*start)] = {"owner": pid, "strength": 1}
                for p in game["players"]:
                    if not owned_cells(game, p["id"]):
                        # Give late joiners a home cell (should not happen, but keep the game playable).
                        free = [k for k, v in game["cells"].items() if v["owner"] is None]
                        if free:
                            game["cells"][random.choice(free)] = {"owner": p["id"], "strength": 1}
                game["status"] = "active"
                game["turn"] = 0
                game["round"] = 1
                while game["status"] == "active" and current(game)["bot"]:
                    auto_bot_move(game)
                self._send(200, {"game_id": gid, "state": snapshot(game)})
                return
            if path.startswith("/api/games/") and path.endswith("/move"):
                gid = path.strip("/").split("/")[2]
                game = GAMES.get(gid)
                if not game:
                    self._send(404, {"error": "game not found"})
                    return
                try:
                    state = apply_move(game, str(body.get("player_id") or ""), str(body.get("action") or ""), body.get("cell"), body.get("source"))
                    self._send(200, {"ok": True, "state": state})
                except ValueError as exc:
                    self._send(400, {"ok": False, "error": str(exc)})
                return
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"Signal Clash listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
