#!/usr/bin/env python3
"""Fast tests for Signal Clash. Run: python3 -m unittest -v test_game.py"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import server


def make_game(p1_cells=None, p2_cells=None):
    cells = server.empty_board()
    for cell in p1_cells or ["0,0"]:
        cells[cell] = {"owner": "p1", "strength": 1}
    for cell in p2_cells or ["4,4"]:
        cells[cell] = {"owner": "p2", "strength": 1}
    return {
        "id": "test",
        "code": "test",
        "max_players": 2,
        "status": "active",
        "round": 1,
        "turn": 0,
        "players": [
            {"id": "p1", "name": "Ada", "color": "#5eead4", "energy": 3, "bot": False},
            {"id": "p2", "name": "Bot", "color": "#f9a8d4", "energy": 3, "bot": False},
        ],
        "cells": cells,
        "log": [],
        "winner": None,
    }


class EngineTests(unittest.TestCase):
    def setUp(self):
        server.GAMES.clear()

    def test_board_has_all_cells_and_claims_are_legal(self):
        game = make_game()
        self.assertEqual(len(game["cells"]), 25)
        moves = server.legal_moves(game, "p1")
        claims = [m for m in moves if m["action"] == "claim"]
        self.assertIn("0,1", {m["cell"] for m in claims})

    def test_claim_takes_cell_and_energy(self):
        game = make_game()
        state = server.apply_move(game, "p1", "claim", "0,1", None)
        self.assertEqual(game["cells"]["0,1"], {"owner": "p1", "strength": 1})
        p1 = server.player(game, "p1")
        self.assertEqual(p1["energy"], 2)
        self.assertEqual(state["status"], "active")

    def test_successful_attack_captures(self):
        game = make_game(p1_cells=["0,0"], p2_cells=["0,1", "4,4"])
        game["cells"]["0,0"]["strength"] = 3
        game["players"][0]["energy"] = 2
        with patch.object(server.random, "randint", return_value=3):
            server.apply_move(game, "p1", "attack", "0,1", "0,0")
        self.assertEqual(game["cells"]["0,1"], {"owner": "p1", "strength": 1})

    def test_failed_attack_weakens_attacker(self):
        game = make_game(p1_cells=["0,0"], p2_cells=["0,1", "4,4"])
        game["cells"]["0,0"]["strength"] = 2
        game["cells"]["0,1"]["strength"] = 5
        game["players"][0]["energy"] = 2
        with patch.object(server.random, "randint", return_value=1):
            server.apply_move(game, "p1", "attack", "0,1", "0,0")
        self.assertEqual(game["cells"]["0,0"]["strength"], 1)
        self.assertEqual(game["cells"]["0,1"]["owner"], "p2")

    def test_ten_cells_wins(self):
        p1_cells = [f"0,{c}" for c in range(5)] + [f"1,{c}" for c in range(4)]
        game = make_game(p1_cells=p1_cells, p2_cells=["4,4"])
        game["players"][0]["energy"] = 3
        state = server.apply_move(game, "p1", "claim", "1,4", "1,3")
        self.assertEqual(state["status"], "finished")
        self.assertEqual(state["winner"], "p1")
        self.assertEqual(len(server.owned_cells(game, "p1")), 10)

    def test_human_vs_bot_finishes(self):
        game = make_game()
        game["players"][1]["bot"] = True
        for _ in range(200):
            if game["status"] != "active":
                break
            cur = server.current(game)
            moves = server.legal_moves(game, cur["id"])
            self.assertTrue(moves)
            pick = next((m for m in moves if m["action"] == "attack"), None)
            pick = pick or next((m for m in moves if m["action"] == "claim"), None)
            pick = pick or next((m for m in moves if m["action"] == "reinforce"), None)
            pick = pick or {"action": "charge"}
            server.apply_move(game, cur["id"], pick["action"], pick.get("cell"), pick.get("source"))
        self.assertEqual(game["status"], "finished")
        self.assertIn(game["winner"], {"p1", "p2", None})
        self.assertTrue(any(e.get("kind") == "finish" for e in game["log"]))

    def test_exact_tie_is_a_draw(self):
        game = make_game(p1_cells=["0,0"], p2_cells=["4,4"])
        server.finish(game, "rounds")
        self.assertEqual(game["status"], "finished")
        self.assertIsNone(game["winner"])

    def test_attack_roll_is_in_public_log(self):
        game = make_game(p1_cells=["0,0"], p2_cells=["0,1", "4,4"])
        game["players"][0]["energy"] = 2
        with patch.object(server.random, "randint", return_value=2):
            server.apply_move(game, "p1", "attack", "0,1", "0,0")
        entry = game["log"][-1]
        self.assertEqual(entry["action"], "attack")
        self.assertIn(entry["roll"], (1, 2, 3))
        self.assertIn("won", entry)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.GAMES.clear()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_lobby_start_and_claim(self):
        status, created = self.call("POST", "/api/games", {"name": "Ada", "players": 2})
        self.assertEqual(status, 200)
        gid = created["game_id"]
        self.assertEqual(len(created["state"]["cells"]), 25)

        status, started = self.call("POST", f"/api/games/{gid}/start", {})
        self.assertEqual(status, 200)
        self.assertEqual(started["state"]["status"], "active")
        self.assertTrue(started["state"]["players"][1]["bot"])

        status, legal = self.call("GET", f"/api/games/{gid}/legal?player_id=p1")
        self.assertEqual(status, 200)
        self.assertTrue(any(m["action"] == "claim" for m in legal["moves"]))
        self.assertEqual(legal["win_cells"], server.WIN_CELLS)

        status, moved = self.call(
            "POST", f"/api/games/{gid}/move",
            {"player_id": "p1", "action": "claim", "cell": "0,1"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(moved["ok"])
        self.assertEqual(moved["state"]["cells"]["0,1"]["owner"], "p1")

    def test_bad_input_is_json_400(self):
        status, body = self.call("POST", "/api/games", {"name": "Ada", "players": "many"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        status, created = self.call("POST", "/api/games", {"name": "Ada", "players": 2})
        self.assertEqual(status, 200)
        status, body = self.call("GET", f"/api/games/{created['game_id']}/legal")
        self.assertEqual(status, 400)
        self.assertIn("player_id", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
