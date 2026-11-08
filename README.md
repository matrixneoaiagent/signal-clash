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
max 5). A successful attack captures the cell at strength 1. The first player
to control 13 of the 25 cells, or the player with the most cells after 15
rounds (ties: total strength, then energy), wins. Empty seats are filled by
simple bots, so a human can start a two-player match alone.

## Run locally

```bash
python3 server.py
# open http://localhost:8080
```

No dependencies, no database. Games live in memory; one process serves the API
and the browser UI.

## Play with an agent

Create a match in the browser, copy the match code, then:

```bash
python3 sample_bot.py --base http://localhost:8080 --game <match-code>
```

The sample bot joins, waits for its turn, and plays legal moves. It uses only
`requests`.

## API

All responses are JSON. CORS is open (`Access-Control-Allow-Origin: *`).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/games` | `{"name": "Ada", "players": 2}` | `game_id`, `join_code`, `player_id`, `state` |
| POST | `/api/games/{id}/join` | `{"name": "Bot"}` | `player_id`, `state` |
| POST | `/api/games/{id}/start` | `{}` | `state` (fills empty seats with bots) |
| GET | `/api/games/{id}` | — | full public state |
| GET | `/api/games/{id}/legal?player_id=p1` | — | `{"moves": [...]}` |
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
- Energy is the pacing resource: claiming grows your income of cells but
  spends the energy you need to defend; attacking can flip a cell but costs 2.
- Attack strength is capped at 5, so a defended cell is not free to take.
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
