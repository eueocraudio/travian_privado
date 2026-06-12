# Rotina — ler recursos e evoluir um campo no `dorf1.php`

Validado em 2026-06-12 contra `ts6.x1.america.travian.com`, com o browser em
modo `--servir` (porta 9000). Pré-requisito: já estar logado e em `dorf1.php`
(ver [APRENDIZADO.md](../login/APRENDIZADO.md) para o login).

## Mapa de tipos de campo (gid)

| gid | Recurso |
|-----|---------|
| gid1 | Madeira (lumber) |
| gid2 | Barro (clay) |
| gid3 | Ferro (iron) |
| gid4 | Cereal (crop) |

## Como LER o estado da aldeia (dorf1.php)

- **Estoque atual**: spans com `id="l1"`..`id="l4"` = Madeira, Barro, Ferro, Cereal.
- **Produção/hora**: aparece no texto do tooltip da barra, no formato
  `Madeira: 58`, `Barro: 52`, `Ferro: 48`, `Cereal: 56`.
- **Campos e níveis**: links `build.php` com classe
  `good level colorLayer resourceField gid{N} buildingSlot{S}  level{L}`.
  - `gid{N}` = tipo do recurso; `buildingSlot{S}` = slot (id do campo);
    `level{L}` = nível atual.
  - Ex. real lido: 18 campos — Madeira×4, Barro×4, Ferro×4, **Cereal×6**.

> Regra de prioridade aprendida: **Cereal é o mais importante para evoluir**
> (6 campos; manutenção de tropas/edifícios consome cereal; se a produção
> líquida zera, o crescimento trava). O **gargalo de produção** costuma ser o
> recurso de menor produção/menor nível (no caso, Ferro, todo nível 0).

## Como EVOLUIR um campo (passo a passo)

1. **Entrar no campo** (clicar): leva para `build.php?id={slot}&gid={tipo}`.
   ```
   //a[contains(@class,'gid4') and contains(@class,'buildingSlot8')]
   ```
   (troque `gid4`/`buildingSlot8` pelo recurso/slot desejado.)

2. **Clicar no botão de melhorar** (verde "Melhorar para nível N"):
   ```
   //button[contains(@class,'green') and contains(@class,'build')]
   ```
   - Se faltar recurso, o botão verde não aparece (vem um aviso de recursos
     insuficientes / link de NPC). Conferir antes de clicar.

3. **Confirmação**: a página redireciona para `dorf1.php?id=...&gid=...`, surge
   a **lista de construções** com um **timer** (segundos restantes) e os
   **recursos são debitados** (estoque cai pelo custo) — sinais de que a ordem
   foi aceita.

## Lote JSON pronto (enviar pelo socket)

```json
{"actions": [
  {"type": "click", "xpath": "//a[contains(@class,'gid4') and contains(@class,'buildingSlot8')]"},
  {"type": "sleep", "value": 5},
  {"type": "click", "xpath": "//button[contains(@class,'green') and contains(@class,'build')]"},
  {"type": "sleep", "value": 4},
  {"type": "url"},
  {"type": "html", "id": "depois_upgrade"}
]}
```

Enviar com:
```bash
.venv/bin/python cliente.py -p 9000 '<lote acima numa linha>'
```

## Execução real registrada

- Campo: Cereal, `buildingSlot8` (nível 0 → 1), `build.php?id=8&gid=4`.
- Botão: "Melhorar para nível 1" (verde, recursos suficientes).
- Resultado: construção enfileirada (timer ~145s); estoque caiu de ~800 cada
  para `800/730/710/729` (madeira/barro/ferro/cereal) = custo pago.
