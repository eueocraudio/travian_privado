# Aprendizado — mapa, oásis e página de ataque

Validado ao vivo em 2026-06-12 (`ts6.x1.america.travian.com`, aldeia 19|114).

## APIs internas do mapa (via action `eval` do browser.py)

O `/karte.php` é canvas/JS — os tiles **não** estão no DOM. Os dados vêm de
duas APIs (POST JSON, mesma origem/cookies). Chamadas por XHR síncrono dentro
da action `eval` (que rodamos no contexto da página):

1. **`POST /api/v1/map/position`** — corpo
   `{"data":{"x":X,"y":Y,"zoomLevel":3,"ignorePositions":[]}}` → `{"tiles":[...]}`.
   Cada tile: `position {x,y}`, `title`, `text`. Classificação pelo `title`:
   - `{k.dt} <nome>` = **aldeia** · `{k.fo}` = **oásis livre (desocupado)** ·
     resto (`{k.vt} {k.fN}`, Floresta, Lago, Barro, Montanha…) = **terreno**.
   - zoomLevel 3 ≈ 961 tiles (31×31).
2. **`POST /api/v1/map/tile-details`** — corpo `{"x":X,"y":Y}` →
   `{"html":"<div id=\"tileDetails\" class=\"oasis oasis-N\">..."}`. Traz:
   "Oásis **desocupado**", **bônus** (ex.: 25% Madeira, 25% Cereal), e
   **"Tropas nenhum(a)"** quando não há defesa (senão lista os animais).

No `travian.py`: `mapa_posicao()`, `oasis_detalhe()`, `escanear_mapa()` (salva
em `mapa_tiles` e `oasis`), comando `scan` (1×/dia, com trava no `meta`).

## Ir até uma coordenada pela UI (ensinado pelo usuário)

`karte.php` → preencher `#xCoordInputMap` / `#yCoordInputMap` → clicar OK
(`#mapCoordEnter`) → o mapa centraliza → clicar no **tile central**. (Usado
para abrir o popup do alvo / iniciar ações pela interface.)

## Página de ATAQUE (ponto de encontro)

URL: **`build.php?id=39&gid=16&tt=2`** (id 39 = slot do ponto de encontro,
gid 16, tt=2 = aba enviar tropas).

- **Coordenada destino:** `#xCoordInput` (name `x`) e `#yCoordInput` (name `y`).
- **Tropas:** inputs `name="troop[t1]".."troop[t11]"`. **`troop[t11]` = HERÓI**
  (os demais ficam `disabled` quando você não tem aquela unidade). Herói em
  casa = `troop[t11]` habilitado.
- **Tipo de envio:** radio `name="eventType"`:
  - **value=4 → Assalto (raid)** ← oásis é SEMPRE assalto.
  - value=3 → Ataque Normal · value=5 → Reforços.
- Botão **"Enviar"** = `#ok` → vai para a **confirmação**.
- **Confirmação:** botão **"Confirmar"** = `#confirmSendTroops` (e "Editar"
  = `#back`).

### Sequência validada (assalto só com herói num oásis sem defesa)
1. `navigate build.php?id=39&gid=16&tt=2`
2. `key #xCoordInput=18`, `key #yCoordInput=113`
3. `key troop[t11]=1` (herói)
4. `click //input[@name="eventType" and @value="4"]` (Assalto)
5. `click #ok` (Enviar) → 6. `click #confirmSendTroops` (Confirmar)
7. dorf1 "tropas saindo" passa a mostrar "1 Ataque em H:MM:SS".

## Regras do raid de oásis (acumuladas)

1. Só atacar se houver **tropa de exército** (config; o herói sozinho foi só
   para aprender o layout). `OASIS_HEROI_OBRIGATORIO` (true/false) no `.env`.
2. Alvo **desocupado** (`{k.fo}` / "Oásis desocupado").
3. **Confirmar a defesa ANTES** (tile-details) — animais nascem com o tempo.
4. Atacar só se a **defesa < minha força**, com **força máxima**, tipo
   **Assalto**.
