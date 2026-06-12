# Documentação — bot Travian (`~/travian`)

Aprendizados organizados por tema. Cada pasta documenta o que foi descoberto
ao vivo e como o `travian.py` automatiza.

| Tema | Doc | Conteúdo |
|------|-----|----------|
| **login** | [login/APRENDIZADO.md](login/APRENDIZADO.md) | login no servidor de jogo, armadilhas (Enter cru, lobby, headless, cookies, setter React, load_profile) |
| **construcao** | [construcao/rotina_evoluir_recurso.md](construcao/rotina_evoluir_recurso.md) | subir campos (dorf1) e edifícios (dorf2), botão verde, gids |
| **missoes** | [missoes/aprendizado_recolher_missoes.md](missoes/aprendizado_recolher_missoes.md) | recolher recompensas (vão pro herói, sem limite de storage) |
| **heroi** | [heroi/aprendizado_heroi.md](heroi/aprendizado_heroi.md) | transferir do herói (≤80%, 2º botão), aventura (vida>50%, "tropas saindo") |
| **oasis-mapa** | [oasis-mapa/aprendizado_oasis_ataque.md](oasis-mapa/aprendizado_oasis_ataque.md) | APIs do mapa (`eval`), oásis (aldeia≠oásis), página de ataque (assalto) |
| **roadmap** | [roadmap/roadmap.md](roadmap/roadmap.md) | próximos passos, regras de construção/herói |

## Onde fica o quê

```
~/travian/
├── travian.py        # automação (classe Travian + CLI)
├── iniciar.sh        # sobe o browser + login + loop, por terminal
├── docs/<tema>/      # estes aprendizados
├── profile/          # perfil vivo do browser (login persistente)
├── travian.tar.gz    # backup do perfil logado
└── account/<servidor>/<usuario>/
        ├── .env          # credenciais + config (HEROI_ATRIBUTO, OASIS_*)
        └── travian.sqlite # histórico (ver tabelas abaixo)
```

## Comandos do `travian.py`

`status` · `collect` · `transfer` · `adventure` · `hero` · `evolve [dorf1|dorf2]`
· `storage` · `reports` · `daily` · `scan` (1×/dia) · `movimentos` · `ciclo`
· `loop` (executor) · `login`

## Tabelas no SQLite da conta

`acoes` (tudo que o bot faz) · `estado` (snapshots de recursos) · `relatorios`
(batalha/aventura) · `mapa_tiles` (todos os tiles) · `oasis` (detalhe + rodízio
por `data_ultima_consulta`) · `meta` (ex.: último scan) · `construcoes` (gate de
construção por dorf) · `movimentos` (ataques/tropas saindo).

## Executor (loop)

`ciclo` faz uma passada: lê o `dorf1` uma vez e só age no pendente (indicadores)
ou na hora certa (horários no SQLite). `loop` repete, dormindo até o próximo
evento relevante (fim de obra / chegada de tropa) — evita navegar à toa.
Iniciar tudo por terminal: `~/travian/iniciar.sh`.
