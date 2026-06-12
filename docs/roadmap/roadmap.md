# Roadmap / próximos passos — Travian (aldeia "naoimporta", ts6 América)

Atualizado em 2026-06-12. Base do que aprendemos; o `travian.py` automatiza as
partes mecânicas.

## Regra de construção (ensinada pelo usuário)

> **1 obra por vez em `dorf2` (edifícios) e 1 por vez em `dorf1` (campos).**
> São filas **separadas**: dá para ter 1 campo subindo E 1 edifício subindo ao
> mesmo tempo, mas **não** 2 edifícios nem 2 campos.

- Antes de mandar construir, checar se a fila daquele dorf já tem obra
  (`buildingList` presente na página) — senão o jogo recusa.
- **Exceção observada:** conta de jogador novo tem uma **fila de construção
  grátis** temporária, que deixou enfileirar Celeiro **+** Armazém juntos
  (sequencialmente). Quando essa fila grátis acabar, volta a valer 1 por dorf.

## Estado atual (snapshot)

- **Armazenamento sendo construído:** Celeiro (g11) e Armazém (g10), ambos vão
  para **capacidade 1200** (de 800). Custo ~80/100/70/20 cada — já debitado.
  - Celeiro pronto em ~14 min; Armazém em ~47 min (sequencial).
- **Missões:** as 4 prontas já foram **recolhidas** (Bosque, Crops, Edifício
  Principal, Ponto de reunião). Recompensa vai para o **herói** (barra azul),
  não para o armazém — **não há limite para recolher** (ver
  [aprendizado_recolher_missoes.md](../missoes/aprendizado_recolher_missoes.md)).
- **Herói:** vida **100%** e tem **1 aventura** disponível (o "!"). Regra:
  vida > 50% → pode mandar na aventura.

## Sequência recomendada (curto prazo)

1. ✅ **Celeiro + Armazém** construídos (capacidade → 1200 cada).
2. ✅ **4 missões recolhidas** (`python travian.py collect`).
3. **Mandar o herói na aventura** (o "!") — vida 100% (> 50%) → pode ir.
   Dá XP + recursos/itens. (Ainda a automatizar no `travian.py`.)
4. Seguir subindo campos/edifícios (ver médio prazo abaixo) — a cada obra,
   recolher novas missões que forem aparecendo.

## O que evoluir (médio prazo) — tarefas em aberto

As próximas tarefas progressivas pedem (e dão recompensa):

| Tarefa | Objetivo | Como avançar |
|--------|----------|--------------|
| **Embaixada 300** | construir uma Embaixada (g18) | dá pontos de cultura + população |
| **População 375** | crescer a população | subir campos/edifícios (cada nível soma pop.) |
| **Produção de pontos de cultura 375** | + cultura/dia | Edifício Principal, Embaixada, Mercado… |

Prioridades de evolução:

1. **Campos de recurso** — subir os de nível 0, começando pelo **gargalo de
   produção** (Ferro, todos nível 0; depois Cereal, que tem 6 campos e é o
   limitador de crescimento). Cada upgrade também conta para "População".
2. **Edifício Principal** — subir reduz o tempo de todas as construções.
3. **Embaixada** — destrava a tarefa e dá cultura (necessária para fundar a 2ª
   aldeia mais à frente).
4. **Armazém/Celeiro** — subir mais quando as recompensas/produção encherem de
   novo (com missões dando 600 de cada no total, a capacidade enche rápido).

## Automação (`travian.py`)

```bash
python travian.py status     # recursos, capacidade, livre, missões prontas
python travian.py collect    # recolhe só o que couber (regra de ouro)
python travian.py storage    # constrói Celeiro/Armazém se faltarem
python travian.py upgrade <slot> <gid>   # sobe um campo (ex.: ferro slot 4 gid 3)
```

> Regras já embutidas no script: não recolhe missão que não cabe; ao construir,
> detecta se a obra entrou na fila (respeita 1-por-dorf). Próximos incrementos
> sugeridos: escolher automaticamente o campo de menor nível/produção para
> subir, e mandar o herói em aventura.
