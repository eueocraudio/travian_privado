# Aprendizado — recolher recompensas de missão

Atualizado em 2026-06-12 (corrigido após teste ao vivo).

## Regra correta (Travian atual)

> **NÃO há mais limite de armazenamento para recolher recompensa de missão.**
> Se há recompensa pronta, **recolhe direto, sem validar capacidade**.

Os recursos da recompensa **não vão para o armazém/celeiro do topo** — vão para
o **herói** (a "barra azul" ao lado do personagem). Por isso, ao recolher, o
estoque do topo não muda. Isso foi confirmado ao vivo: recolher 4 missões de
"150 de cada" não alterou o estoque do armazém.

> ⚠️ Correção: uma versão anterior deste doc dizia que era preciso checar se a
> recompensa "cabia" no armazém. **Isso está errado / é mecânica antiga.**

## Como recolher (seletores)

- **Botão de missões** (canto inferior direito, o "!"): `#questmasterButton`
  (classe `claimable` quando há recompensa). Abre `/tasks?t=village`.
- **Botão recolher** de cada tarefa pronta:
  `//button[contains(@class,'collect')]` (texto "Recolher").
- Recolher **todas**: clicar `(//button[contains(@class,'collect')])[1]`,
  **re-navegar** a `/tasks?t=village` (a UI remove o botão de forma assíncrona,
  então só uma releitura limpa dá a contagem certa) e repetir até não sobrar
  botão `collect`.

## No `travian.py`

```bash
python travian.py collect    # recolhe TODAS as recompensas, sem validar nada
```

Implementado em `Travian.recolher_missoes()`: laço que re-navega a `/tasks`,
conta os botões `collect`, clica um, repete até zerar (com guarda anti-laço se
a contagem não cair). Testado ao vivo: recolheu 4/4.
