# Signal Clash

A compact 2–4 player turn-based strategy game for **humans and agents in the
same match**. Humans play in a browser; agents use a small HTTP/JSON API. The
server is one Python file with no dependencies beyond the standard library.

**Live:** https://xhtml-thus-establishment-crimes.trycloudflare.com

**Repo:** https://github.com/matrixneoaiagent/signal-clash

## Rules, in one paragraph

Each player starts with one home cell on a 5×5 grid and 3 energy. On your turn,
choose one action: **Claim** an adjacent empty cell (1 energy), **Reinforce**
one of your cells up to strength 5 (1 energy), **Attack** an adjacent enemy
cell from one of your cells (2 energy; your strength + a 1–3 roll must beat the
defender, otherwise the attacker loses 1 strength), or **Charge** (+2 energy,
max 5). A successful attack captures the cell at strength 1. Energy comes only
from Charging, so every Claim, Reinforce, and Attack is a trade-off. The first
player to control 10 of the 25 cells, or the player with the most cells after
15 rounds (ties: total strength, then energy; if still tied, the match is a
draw). Empty seats are filled by simple bots, so a human can start a two-player
match alone.

## Run locally

```bash
python3 server.py            # http://localhost:8080
PORT=8090 python3 server.py  # or pick another port
```

The server uses only the Python standard library. No database; games live in
memory and one process serves the API and the browser UI.

## Play in the browser

Open the site, enter a name, choose 2–4 players, and click **Create match**.
The match code appears in the game panel. Share it with another human or an
agent; when everyone has joined, click **Start match** (or **Quick play vs
bots**) to fill any empty seats with bots and begin. Click a cell, then choose
Claim, Reinforce, or Attack; Charge is always available. The board auto-refreshes
so a second browser sees the other player's turns without reloading.

## Play with an agent

Create a match in the browser, copy the match code, then:

```bash
python3 -m pip install requests   # sample bot only; the server has no deps
python3 sample_bot.py --base http://localhost:8080 --game <match-code>
```

The sample bot joins, waits for its turn, and plays legal moves. Start the match
in the browser after the bot joins. With no `--game`, the bot creates its own
2-player match against a bot and starts it immediately.

### Minimal agent loop

1. `POST /api/games/{id}/join` with `{"name":"My Agent"}` → save `player_id`.
2. Poll `GET /api/games/{id}` until `status == "active"` and `turn == player_id`.
3. `GET /api/games/{id}/legal?player_id=...` → pick any move from `moves`.
4. `POST /api/games/{id}/move` with that move plus `player_id`.
5. Repeat until `status == "finished"`; read `winner` or `GET /api/games/{id}/log`.

Bots move synchronously, so after a human move the response already contains
the bots' replies. A finished game exposes the full log at `/log` for replay.

## API

All responses are JSON. CORS is open (`Access-Control-Allow-Origin: *`).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/games` | `{"name": "Ada", "players": 2}` | `game_id`, `join_code`, `player_id`, `state` |
| POST | `/api/games/{id}/join` | `{"name": "Bot"}` | `player_id`, `state` |
| POST | `/api/games/{id}/start` | `{}` | `state` (fills empty seats with bots) |
| GET | `/api/games/{id}` | — | full public state (`status`, `round`, `turn`, `win_cells`, `players`, `cells`, `winner`, `log_tail`) |
| GET | `/api/games/{id}/legal?player_id=p1` | — | `{"moves":[...], "status":..., "turn":..., "win_cells":10}` |
| POST | `/api/games/{id}/move` | `{"player_id":"p1","action":"claim","cell":"1,2"}` | `{"ok":true,"state":...}` |
| GET | `/api/games/{id}/log` | — | full match log |
| GET | `/api/health` | — | `{"ok":true,"games":N}` |

Move actions:

```json
{"player_id":"p1","action":"claim","cell":"1,2"}
{"player_id":"p1","action":"reinforce","cell":"1,2"}
{"player_id":"p1","action":"attack","cell":"2,2","source":"1,2"}
{"player_id":"p1","action":"charge"}
```

Cells are `"row,col"` with both coordinates 0–4. `source` is required for
attacks and must be one of your cells adjacent to the target. Invalid moves
return `400` with `{"error": "..."}`.

`winner` is a player id, or `null` for a draw: after 15 rounds, if players are
tied on cells, total strength, and energy, the match is a draw. The `/log`
entry with `kind: "finish"` records the reason (`majority`, `rounds`) and the
winner (or `null`).

### Quick curl

```bash
BASE=http://localhost:8080
GAME=$(curl -s -X POST $BASE/api/games -H 'content-type: application/json' \
  -d '{"name":"Ada","players":2}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["game_id"])')
curl -s -X POST $BASE/api/games/$GAME/start -H 'content-type: application/json' -d '{}'
curl -s "$BASE/api/games/$GAME/legal?player_id=p1"
curl -s -X POST $BASE/api/games/$GAME/move -H 'content-type: application/json' \
  -d '{"player_id":"p1","action":"charge"}'
```

## Design notes

- Perfect information; no hidden state. The only randomness is an attack roll,
  which is shown in the public log.
- Energy is the pacing resource: Charge is the only way to refill it, so a
  Claim costs you a future action and an Attack costs two. More cells give you
  more attack routes, but not more energy.
- Attack strength is capped at 5, and a failed attack weakens the attacker, so
  a defended cell is not free to take.
- Bots fill empty seats with a simple attack/claim/reinforce policy, so a match
  always starts and always ends.

## Files

| File | Purpose |
|---|---|
| `server.py` | game engine, JSON API, static UI server |
| `index.html` | browser UI (create/join/start/play) |
| `sample_bot.py` | sample agent that plays legal moves |
| `pitch.md` | TaskMarket submission text |

MIT licensed.
