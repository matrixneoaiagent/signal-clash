#!/usr/bin/env python3
"""Sample Signal Clash agent bot.

Creates a 2-player match against a bot (or joins an existing one), then plays
legal moves with a simple priority: attack the weakest adjacent enemy, claim an
adjacent empty cell, reinforce a low cell, otherwise charge.

Usage:
  python3 sample_bot.py --base http://localhost:8080
  python3 sample_bot.py --base https://<public-url> --game <id>
"""

from __future__ import annotations

import argparse
import random
import time

import requests


def pick(moves: list[dict]) -> dict:
    attacks = [m for m in moves if m.get("action") == "attack"]
    if attacks:
        return random.choice(attacks)
    claims = [m for m in moves if m.get("action") == "claim"]
    if claims:
        return random.choice(claims)
    reinforces = [m for m in moves if m.get("action") == "reinforce"]
    if reinforces:
        return random.choice(reinforces)
    return {"action": "charge"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--game", default=None)
    ap.add_argument("--name", default="Sample Bot")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    if args.game:
        game_id = args.game
        r = requests.post(f"{base}/api/games/{game_id}/join", json={"name": args.name}, timeout=20)
        r.raise_for_status()
        player_id = r.json()["player_id"]
    else:
        r = requests.post(f"{base}/api/games", json={"name": args.name, "players": 2}, timeout=20)
        r.raise_for_status()
        d = r.json()
        game_id, player_id = d["game_id"], d["player_id"]
        requests.post(f"{base}/api/games/{game_id}/start", json={}, timeout=20).raise_for_status()
        print(f"created {game_id}; play at {base}/ (code {game_id})")

    print(f"playing as {player_id} in {game_id}")
    waiting_printed = False
    for _ in range(500):
        s = requests.get(f"{base}/api/games/{game_id}", timeout=20).json()
        if s.get("status") == "lobby":
            if not waiting_printed:
                print("joined; waiting for the match to start")
                waiting_printed = True
            time.sleep(0.5)
            continue
        if s.get("status") != "active":
            print("finished; winner:", s.get("winner"))
            return 0
        if s.get("turn") != player_id:
            time.sleep(0.4)
            continue
        legal = requests.get(f"{base}/api/games/{game_id}/legal", params={"player_id": player_id}, timeout=20).json()
        move = pick(legal.get("moves", []))
        r = requests.post(f"{base}/api/games/{game_id}/move", json={"player_id": player_id, **move}, timeout=20)
        if not r.ok:
            print("move refused:", r.text[:300])
            time.sleep(0.5)
        else:
            print("move", move)
        time.sleep(0.2)
    print("gave up after 500 turns")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
