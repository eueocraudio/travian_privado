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
  See `Travian.enviar()` at `travian.py:113`.
- **Action vocabulary** (interpreted by the browser server, not here):
  `navigate`, `sleep`, `url`, `html`, `key` (xpath+value), `click` (xpath),
  `eval` (run JS, returns result), plus `save_profile` / `load_profile`
  (tar the profile dir). Map/oasis reads use `eval` to fire same-origin XHRs
  against Travian's internal `/api/v1/map/*` JSON endpoints (`_xhr_post()` at
  `travian.py:424`; `mapa_posicao()` / `oasis_detalhe()` at `travian.py:477`).
- **No HTML parser dependency.** Every page is scraped with regex against the
  raw HTML string. Travian injects bidi marks (`‭`/`‬`) into numbers — `_num()`
  strips them; many parsers re-strip them inline.
- **Human-like pacing is intentional.** `ir()` sleeps a random 1–5s *before*
  every navigation; `SLEEP_TOQUE` is 1s between touches on the same screen.
  Do not remove these — they mimic a human to avoid detection.
- **Multi-account.** User data lives **outside the checkout**, under `~/travian/`
  by default (override with `TRAVIAN_DADOS`); the code resolves it via
  `DIR_DADOS`/`DIR_CONTAS` (`travian.py:891`). Each account is a self-contained
  dir `~/travian/account/<server>/<user>/` containing:
  - `.env` — `TRAVIAN_BASE`, `TRAVIAN_EMAIL`, `TRAVIAN_PASSWORD`, plus config
    like `HEROI_ATRIBUTO` (forca|ataque|defesa|producao), `ESTRATEGIA` and
    `OASIS_*`. The checked-in **`.env.template`** is the canonical key list; at
    startup `conferir_env_template()` warns (doesn't abort) about keys the
    account `.env` is missing relative to it. New accounts are created with
    **`./cadastrar.sh`** (asks server/email/password, fills the `.env` from the
    template; other keys keep their defaults).
  - `travian.sqlite` — history/state (see tables below).
  - `profile/` — the live browser profile for this account.
  - `travian.tar.gz` — saved-profile backup (login session) for this account.
  Account is selected by `TRAVIAN_ACCOUNT="<server>/<user>"`; if exactly one
  account exists it's auto-selected (`resolver_conta()` at `travian.py:921`).
- **SQLite is the bot's memory and scheduler.** Tables (`abrir_db()`,
  `travian.py:940`): `acoes` (every command run), `estado` (resource
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

- `ciclo()` (`travian.py:1175`) is one pass: it reads `dorf1` once and only acts
  on what's pending (indicators in the HTML) or due (timestamps in SQLite).
- **Three priority tiers** (see comment at `travian.py:1149`):
  1. **imediato** — a one-shot script in `meta['proximo_imediato']`, run at the
     very start of the next cycle ahead of everything, then cleared. Any script
     enqueues the next via `agendar_imediato(db, "<nome>")`; dispatched by
     `_exec_script()` (`travian.py:1161`).
  2. **agendados** — run when their time/event gate is reached (build finish,
     daily map scan ≥23h, oásis check). Scheduled tiers take priority over loop.
  3. **loop** — the indicator-driven obligatory steps that run every cycle
     (missions, reports, daily tasks, adventure+hero, troop movements).
- `loop` repeats `ciclo`, sleeping until the next relevant event (build finish /
  troop arrival) via `proximo_evento_seg()` (`travian.py:1129`), clamped to
  [5min, 30min] — but if an `imediato` script is queued it sleeps only ~1min.
- Build scheduling is gated through SQLite: `evoluir_controlado()`
  (`travian.py:1014`) won't build in a dorf until the recorded finish time of
  the last build there has passed, and records the new finish time after
  building.
- **`transferir_recursos` never runs inline in the cycle.** It only enters via
  the `imediato` slot, queued (+~1min) when a build fails for lack of resources;
  `meta['transfer_vazio']` records when the hero was empty so it isn't re-queued
  uselessly. (See the *transferir-recursos-condicional* and *arquitetura-tipos-
  script* memories.)
- **Tribe-aware build queues.** Romans get two independent queues (1 dorf1 field
  + 1 dorf2 building), so the cycle calls `evoluir_controlado()` for *both*;
  other tribes get one combined call. Tribe is detected once and cached via
  `tribo_conta()` (`travian.py:1054`).
- **Oásis attacks auto-enable.** `oasis_habilitado()` (`travian.py:1097`) caches
  `meta['tem_exercito']` and re-checks at most every `OASIS_CHECK_H` hours while
  there are no troops; once an army is detected the bot starts raiding oases via
  `atacar_oasis()`. Adventure always runs before oásis in the cycle (see the
  *aventura-antes-oasis* memory).
- **Esconderijo (cranny)** is built/upgraded inside dorf2 with a probability
  gate (`prob_esconderijo()` at `travian.py:1064`) — see the *esconderijo-design*
  memory.
- **Muro (wall).** `decidir_dorf2()` prioritizes the wall over everything else
  while beginner protection is still running, until `MURO_NIVEL_ALVO` (5). The
  wall lives only in the fixed dorf2 slot **40** (`subir_muro()`); its gid is
  tribe-specific (`gid_muro()`: roman 31 / teuton 32 / gaul 33 / egyptian 42 /
  hun 43, override via `MURO_GID`). Protection time left is read from dorf1 by
  `protecao_restante_seg()`.
- **Attack strategy (`ESTRATEGIA` in `.env`).** `montar_estrategia()` runs once
  at startup (`main`), reading the `relatorios` table, and stores the result in
  `cfg["_estrategia"]` (used by `oasis_habilitado`/`atacar_oasis`): `sem_perdas`
  (default) only raids undefended oases (`ocupado=0 AND sem_tropas=1`) and skips
  coords the report history flags as risky; `agressivo` raids any free oasis even
  with defense; `defensivo` never attacks. On shutdown the `loop` calls
  `recolher_relatorios()` to fetch unread attack reports before closing (so the
  next session's strategy sees them). `recolher_relatorios()` is the shared
  "read only new `rid`s" helper used by both the cycle and shutdown.
- **Army training (agressivo only).** When the strategy is `agressivo`,
  `decidir_dorf2()` makes sure a Barracks (gid 19) gets built, and the per-cycle
  `treinar_exercito()` trains a small batch (`EXERCITO_LOTE`) of `EXERCITO_TROPA`
  until the home army reaches `EXERCITO_PCT_POP`% of the village population
  (`Travian.populacao()`). `populacao()`/`treinar_tropa()` selectors are not yet
  validated live — see the *exercito-agressivo* / *validar-seletores-vivo*
  memories.
- **Hot-reload loop.** The `loop` re-imports `travian.py` every cycle via
  `_recarregar_modulo()` (fresh `travian_live` module), re-reads `.env`, rebuilds
  the strategy and recreates `t`, then calls `mod.ciclo(...)`. This picks up code
  and `.env` edits without restarting — the session lives in the browser server,
  so recreating `t` doesn't log out; `db` is kept. A bad reload (syntax error)
  falls back to the previous version. See the *hot-reload-loop* memory.
- **Cycle hygiene knobs (recent).** `ir()` skips the reload when already on the
  target URL (re-reads HTML only) unless `recarregar=True`; the `loop` navigates
  to `google.com` while sleeping (stays off the game between cycles); reports are
  only opened when the unread indicator > 0 **and** the `rid` isn't already in
  the `relatorios` table; oásis enablement first tries to detect an army from the
  dorf1 HTML (`exercito_no_dorf1()`) before falling back to the send page; every
  cycle sets the browser window `title` to `{SERVER}.{ACCOUNT}` (`rotulo_conta()`)
  and emits a `comment` action before each script; `ciclo()` returns a multi-line
  `resumo_geral()` (resources / builds / next event / actions).

## Running it

```bash
# Full stack by terminal: starts the browser server (if down), logs in, loops.
./iniciar.sh                 # default account, port 9000, browser + login + loop
./iniciar.sh ciclo           # one pass only (testing), no loop
./iniciar.sh --porta 9000 parar          # kill the browser on that port

# Pick account + port on the command line (one browser/profile per account):
./iniciar.sh --server <host> --account <user> [--porta N] [ciclo|loop]

# Interactive: asks server + account by keyboard, picks a free port 9001..10000,
# then delegates to iniciar.sh. Run one terminal per account to go parallel.
./interativo.sh              # ask + loop
./interativo.sh ciclo        # ask + one pass
./interativo.sh all          # bring up EVERY account in parallel (one browser/
                             # port each); also the "(all)" item in the menu.
                             # Ctrl+C stops all loops and the browsers it started.

# Direct CLI (assumes the browser server is already up on PORTA=9000):
python3 travian.py status    # resources/capacity/missions (+ DB snapshot)
python3 travian.py <cmd>     # status|login|collect|transfer|adventure|hero
                             # evolve [dorf1|dorf2]|storage|reports|daily|oasis
                             # scan [force]|movimentos|ciclo|loop|upgrade <slot> <gid>
                             # (`evolve` also accepts the alias `evoluir`)

# Pick a non-default account:
TRAVIAN_ACCOUNT="ts6.x1.america.travian.com/wellington.aied" python3 travian.py status
```

`iniciar.sh` expects the browser repo at `~/desenv/craudiowebot` with a venv at
`.venv`. The bot **code** runs from this checkout (`$RAIZ/travian.py`), but all
**user data** (accounts, profiles, tarballs) lives under `~/travian/` — i.e.
`TRAVIAN_DADOS` (default `~/travian`), exported by `iniciar.sh` so `travian.py`
inherits it. `iniciar.sh` derives `PROFILE` and `TRAVIAN_TAR` per account from
`$TRAVIAN_DADOS/account/<server>/<user>/`.

## Testing / verification

There is no unit test suite. `teste_travian.py` is a **live** smoke test: it
loads the account's saved profile tarball (`TRAVIAN_TAR`, default the
`travian.tar.gz` inside the account dir), logs into the lobby, and saves the
profile if it reaches `dorf1.php`. It imports `cliente` from the `craudiowebot` repo, so
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
