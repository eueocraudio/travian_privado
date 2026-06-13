# Tarefas diárias (Daily Quests) — aprendizado

Reverse-engineering do diálogo de tarefas diárias (validado ao vivo em
2026-06-13, conta `ptr.x3.international.travian.com/segundo`).

## Indicador no dorf1

O botão fica no dorf1 e mostra um `!` quando há algo a fazer/coletar:

```html
<a class="dailyQuests" href="#" accesskey="7"
   onclick="Travian.React.openDailyQuestsDialog(); return false;">
  <div class="indicator">!</div>
</a>
```

`Travian.tem_tarefas_diarias(html)` = existe `dailyQuests` + `indicator` não vazio.
Abrir o diálogo: clicar `//a[contains(@class,"dailyQuests")]` (o `onclick` chama
`Travian.React.openDailyQuestsDialog()`). **Atenção:** o clique simulado nem
sempre dispara o `onclick` inline de forma consistente (timing do React).

## Estrutura do diálogo

Barra de progresso com checkpoints; cada um é um `div.rewardImage`:

```
div.rewardImage.reward25.achieved   -> atingido, COLETÁVEL
div.rewardImage.reward50.locked     -> ainda não atingido
div.rewardImage.reward75.locked
...
(após coletar: .completed)
```

- **Coletar um checkpoint:** clicar no `div.rewardImage.achieved` → abre um popup
  com o botão `button.collect.collectable` (data-text-collected="Coletadas") →
  clicar nele coleta (o checkpoint vira `.completed`, o indicador do dorf1 some).
  *Validado: reward25 achieved → clique → collectable → coletado.*
- **Botão "Coletar recompensas":** `button.collectRewards` dentro de
  `#dailyQuestsRewardScreen`. **Não tem `id` próprio** — usar a classe
  `collectRewards` (interna, não traduzida) + `not(@disabled)`. Aparecem 2 ativos
  + 1 disabled (telas/abas distintas).

## Status do script

`Travian.recolher_diario()` existe (abre o diálogo e tenta coletar checkpoints
`achieved` e o botão `collectRewards`). **WIP / NÃO integrado no ciclo:** a
condição de PARADA ainda está furada — num estado sem nada a coletar fez 12
cliques (bateu o máximo), porque um checkpoint `achieved` permanece no DOM e/ou o
botão `collectRewards` fica sempre ativo. Falta distinguir "coletável" de "já
coletado/nada" antes de plugar no loop. Hoje o ciclo só **lê** as diárias
(`ler_tarefas_diarias`), não coleta.
