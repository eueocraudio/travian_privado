# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Travian (browser MMO) automation bot, written in Portuguese. It does not drive
a browser directly — it talks over a socket to a separate **`craudiowebot`**
browser server (located at `~/desenv/craudiowebot`) running in `--servir` mode.
All game logic lives in a single module, `travian.py` (class `Travian` + a CLI).

## Architecture

- **Two processes.** `craudiowebot/browser.py --servir 9000 -d <profile>` owns a
  real, visible Chromium-like browser with a persistent profile. `travian.py`
  connects to `127.0.0.1:9000` and sends batches of *actions* as NDJSON
  (one JSON object per line: `{"actions":[...]}` → `{"resultados":[...]}`).
  See `Travian.enviar()` at `travian.py:82`.
- **Action vocabulary** (interpreted by the browser server, not here):
  `navigate`, `sleep`, `url`, `html`, `key` (xpath+value), `click` (xpath),
  `eval` (run JS, returns result), plus `save_profile` / `load_profile`
  (tar the profile dir). Map/oasis reads use `eval` to fire same-origin XHRs
  against Travian's internal `/api/v1/map/*` JSON endpoints (`travian.py:339`).
- **No HTML parser dependency.** Every page is scraped with regex against the
  raw HTML string. Travian injects bidi marks (`‭`/`‬`) into numbers — `_num()`
  strips them; many parsers re-strip them inline.
- **Human-like pacing is intentional.** `ir()` sleeps a random 1–5s *before*
  every navigation; `SLEEP_TOQUE` is 1s between touches on the same screen.
  Do not remove these — they mimic a human to avoid detection.
- **Multi-account.** Each account is `account/<server>/<user>/` containing:
  - `.env` — `TRAVIAN_BASE`, `TRAVIAN_EMAIL`, `TRAVIAN_PASSWORD`, plus config
    like `HEROI_ATRIBUTO` (forca|ataque|defesa|producao) and `OASIS_*`.
  - `travian.sqlite` — history/state (see tables below).
  Account is selected by `TRAVIAN_ACCOUNT="<server>/<user>"`; if exactly one
  account exists it's auto-selected (`resolver_conta()` at `travian.py:733`).
- **SQLite is the bot's memory and scheduler.** Tables (`abrir_db()`,
  `travian.py:752`): `acoes` (every command run), `estado` (resource
  snapshots), `relatorios` (battle/adventure reports), `mapa_tiles`,
  `oasis` (detail + round-robin via `data_ultima_consulta`), `meta`
  (key/value, e.g. last map scan), `construcoes` (per-dorf build gate),
  `movimentos` (outgoing troop movements). The schema self-migrates with
  `ALTER TABLE ... ADD COLUMN` wrapped in try/except.

## Core game rules baked into the code

- **One build at a time per dorf.** `dorf1` = resource fields, `dorf2` =
  buildings; the two queues are independent. The presence of `buildingList`
  in a dorf's HTML means its queue is occupied. `_subir_verde()` only clicks
  the green "Melhorar/build" button when it's enabled — the game only enables
  it when there's a free queue slot *and* enough resources, so this is the
  source of truth rather than guessing.
- **Mission rewards have no storage cap** — they go to the hero ("barra azul"),
  so `recolher_missoes()` collects everything unconditionally, re-reading
  `/tasks` after each collect (the UI removes buttons asynchronously).
- **Hero → warehouse transfers cap at 80%** of capacity to leave room for
  production. The confirm button is the **second** "Transferência" button (the
  first is "max", which ignores the typed amounts).
- **Adventures** require hero not already out, an available adventure, and
  health > 50%.

## The executor

- `ciclo()` (`travian.py:851`) is one pass: it reads `dorf1` once and only acts
  on what's pending (indicators in the HTML) or due (timestamps in SQLite).
- `loop` repeats `ciclo`, sleeping until the next relevant event (build finish /
  troop arrival) via `proximo_evento_seg()`, clamped to [5min, 30min].
- Build scheduling is gated through SQLite: `evoluir_controlado()` won't build
  in a dorf until the recorded finish time of the last build there has passed,
  and records the new finish time after building.

## Running it

```bash
# Full stack by terminal: starts the browser server (if down), logs in, loops.
./iniciar.sh                 # browser + login + loop
./iniciar.sh ciclo           # one pass only (testing), no loop
./iniciar.sh parar           # kill the browser server

# Direct CLI (assumes the browser server is already up on PORTA=9000):
python3 travian.py status    # resources/capacity/missions (+ DB snapshot)
python3 travian.py <cmd>     # status|login|collect|transfer|adventure|hero
                             # evolve [dorf1|dorf2]|storage|reports|daily
                             # scan [force]|movimentos|ciclo|loop|upgrade <slot> <gid>

# Pick a non-default account:
TRAVIAN_ACCOUNT="ts6.x1.america.travian.com/wellington.aied" python3 travian.py status
```

`iniciar.sh` expects the browser repo at `~/desenv/craudiowebot` with a venv at
`.venv`, and the bot deployed under `~/travian` (it runs `~/travian/travian.py`).
Paths in `iniciar.sh`/`demo_profile.sh` assume that `~/travian` deploy layout,
not this source checkout — adjust if running in place.

## Testing / verification

There is no unit test suite. `teste_travian.py` is a **live** smoke test: it
loads the saved profile tarball, logs into the lobby, and saves the profile if
it reaches `dorf1.php`. It imports `cliente` from the `craudiowebot` repo, so
that repo must be on `PYTHONPATH`. `demo_profile.sh` is a live demo proving
`save_profile`/`load_profile` preserves the logged-in session (uses `xvfb-run`).
Both require credentials via `TRAVIAN_EMAIL` / `TRAVIAN_PASSWORD` env vars and a
running browser server — they hit the real game server.

## Conventions

- Code, comments, docstrings, and commit messages are in **Portuguese** — match
  that. Function/variable names are Portuguese (`evoluir`, `recolher_missoes`,
  `coords_aldeia`, etc.).
- Each subsystem has a learning doc under `docs/<tema>/` capturing the
  reverse-engineered selectors, API shapes, and gotchas (login, construcao,
  missoes, heroi, oasis-mapa, roadmap). Read the relevant doc before changing a
  scraper — the regexes encode hard-won details about Travian's DOM.
- Never put credentials in code; they come from the account `.env` or env vars.
