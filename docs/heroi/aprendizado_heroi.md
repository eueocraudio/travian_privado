# Aprendizado — herói: inventário→armazém e aventuras

Validado ao vivo em 2026-06-12 (`ts6.x1.america.travian.com`).

## 1. Transferir recursos do herói para o armazém/celeiro

As recompensas de missão/aventura ficam no **inventário do herói** (não no
armazém). Para usá-las, transferir para o armazém/celeiro — mantendo cada
recurso em **no máximo 80% da capacidade** (deixa folga para a produção).

**Cálculo por recurso:** `transferir = min(qtd_no_herói, 80%×capacidade − estoque)`.

### Como ler (em `/hero/inventory`)
- Slots de recurso: `div.heroItem.consumable` com `<div class="item itemNNN">`:
  - **item145 = Madeira, 146 = Barro, 147 = Ferro, 148 = Cereal**.
  - Quantidade no `<div class="count">N</div>` do slot.
- Estoque/capacidade: barra do topo (`id=l1..l4` e classes `warehouse`/`granary`).

### Como transferir
1. Clicar num slot de recurso (`//div[contains(@class,"heroItem consumable") and @data-placeid="1"]`)
   → abre o diálogo `resourceTransferDialog`.
2. O diálogo tem **4 inputs**: `name="lumber"`, `clay`, `iron`, `crop`.
   Preencher cada um com o valor calculado.
3. **Clicar no SEGUNDO botão "Transferência"** — `(//button[contains(.,"Transferência")])[2]`.
   > ⚠️ O **1º** botão é "**Transferência máxima**", que **ignora os valores e
   > enche até 100%** (fura a regra dos 80%). É SEMPRE o segundo botão.

No script: `python travian.py transfer` (`Travian.transferir_recursos(limite=0.80)`).
Testado: estoque foi a ~960 (80% de 1200), não a 1200.

## 2. Mandar o herói em aventura

### Regras (todas precisam valer)
1. **Herói não pode já estar em aventura.** No `dorf1.php`, a seção
   **"tropas saindo"** mostra "**Aventura em H:MM:SS**" quando o herói está
   fora. Se aparecer, NÃO enviar.
   - Selo: `re.search(r'tropas saindo.{0,80}?Aventura', texto)`.
2. **Tem que haver aventura disponível (> 0).** O número fica no botão de
   aventura: `<a class="...adventure...">​<div class="content">N</div></a>`.
3. **Vida do herói > 50%.** Lê em `/hero/attributes` ("Saúde N") — o número
   está dentro de um `<svg>`, então **remover `<style>/<script>` antes** do
   strip de tags, senão o CSS fica entre "Saúde" e o número.

### Como enviar
- Ir para `/hero/adventures` (lista as aventuras: distância, tempo, dificuldade).
- Cada aventura tem um botão **"Explorar"**
  (`textButtonV2 buttonFramed rectangle withText green`). Clicar
  `(//button[contains(.,"Explorar")])[1]` **envia direto** (sem confirmação
  extra). O herói passa a "a caminho de uma aventura".
- Atenção: o **contador (3)** é o nº de aventuras no mapa e **não cai** só por
  enviar; para saber se o herói foi, olhar o status (dorf1 "tropas saindo").

No script: `python travian.py adventure` (`Travian.fazer_aventura(vida_minima=50)`).
Testado: enviou com vida 100%; depois recusou ("já a caminho de uma aventura").

## Herói disponível: classe `heroHome` (validado ao vivo 2026-06-13)

Forma confiável (independe de idioma) de saber se o herói está **em casa /
disponível**: no dorf1, o ícone do herói é um link cujo `<i>` tem a classe
`heroHome` quando ele está na aldeia:

```html
<a href="/build.php?...id=39...&tt=2" class=""><i class="heroHome"></i></a>
```

Quando o herói está fora a classe muda (`heroRunning` a caminho/voltando, etc.).
`Travian.heroi_em_casa(html)` testa `class="...heroHome..."`; `heroi_em_aventura`
virou "não está em casa". O ciclo e `fazer_aventura` só agem com `heroHome`
presente — substitui o antigo texto frágil "tropas saindo Aventura".
