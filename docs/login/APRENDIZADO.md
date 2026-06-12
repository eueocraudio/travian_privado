# Aprendizado — automação de login no Travian (craudiowebot)

Registro do que funcionou e das armadilhas ao automatizar o login no Travian
com o `browser.py` em modo `--servir` (comandos por socket em tempo de execução).
Data: 2026-06-12.

## Resumo do que funciona (fluxo validado)

Logar **direto no servidor de jogo** (não pelo lobby) e cair no `dorf1.php`:

1. `navigate` → `https://ts6.x1.america.travian.com`
2. `key` no campo usuário → `//input[@name='name']`
3. `key` no campo senha → `//input[@name='password']`
4. `click` no botão Entrar → `//button[@type='submit' and contains(@class,'buttonFramed')]`
5. `sleep` ~10s
6. `url` → confirma `https://ts6.x1.america.travian.com/dorf1.php`
7. se chegou: `save_profile` → `~/travian/travian.tar.gz`

Exemplo de lote JSON enviado ao socket (porta 9000):

```json
{"actions": [
  {"type": "navigate", "value": "https://ts6.x1.america.travian.com"},
  {"type": "key",   "xpath": "//input[@name='name']",     "value": "<email>"},
  {"type": "key",   "xpath": "//input[@name='password']", "value": "<senha>"},
  {"type": "click", "xpath": "//button[@type='submit' and contains(@class,'buttonFramed')]"},
  {"type": "sleep", "value": 10},
  {"type": "url"}
]}
```

## Seletores reais descobertos

| Onde | Elemento | XPath |
|------|----------|-------|
| Servidor de jogo (ts6...) — usuário | `<input name="name" placeholder="Endereço de e-mail / nome da conta">` | `//input[@name='name']` |
| Servidor de jogo — senha | `<input name="password" type="password">` | `//input[@name='password']` |
| Servidor de jogo — submit | `<button type="submit" class="textButtonV2 buttonFramed rectangle ...">Entrar</button>` | `//button[@type='submit' and contains(@class,'buttonFramed')]` |
| Home travian.com — usuário | `<input name="name">` | `//input[@name='name']` |
| Home travian.com — senha | `<input name="password">` | `//input[@name='password']` |
| Home travian.com — submit | `<button class="green buttonFramed withText ...">Login</button>` | `//button[contains(@class,'green') and contains(@class,'buttonFramed') and contains(@class,'withText')]` |

## Armadilhas (o que NÃO funcionou e por quê)

1. **Enter cru não loga no servidor de jogo.** O form é
   `<form action="?" method="get">`. Pressionar Enter (que dispara
   `form.requestSubmit()`) faz um **GET** e joga `?name=...&password=...` na
   URL **sem autenticar**. → Tem que **clicar no botão "Entrar"**, que aciona
   o JS de login correto. (Para o roteiro "pressionar Enter", troque por
   clicar no submit.)

2. **Pelo lobby (`lobby.legends.travian.com`) é mais frágil.** O login no
   `www.travian.com/#loginLobby` autentica e redireciona para
   `lobby.legends.travian.com/account`, mas para **entrar no mundo** é preciso
   clicar no "play" de um gameworld (token SSO). Ir **direto** ao servidor de
   jogo (`ts6.x1.america.travian.com`) e logar lá é mais simples e cai direto
   no `dorf1.php`.

3. **Headless não renderiza o lobby.** Em `QT_QPA_PLATFORM=offscreen` e sob
   `xvfb` (GL por software/SwiftShader), os bundles JS do lobby carregam mas a
   app **não monta** (`<div id="root">` fica vazio, ~12-13KB de HTML) — bate
   com os erros `GPU context lost`. O lobby usa WebGL que quebra sem GPU real.
   → Rodar com **display real** (`DISPLAY=:0`, sem offscreen/xvfb) resolve:
   a janela abre e o WebGL funciona.

4. **Consentimento de cookies (CMP) bloqueia.** No display real aparece um
   diálogo de cookies (iframes `__cmpLocator`/`__tcfapiLocator`); enquanto não
   é aceito, o conteúdo fica preso. Foi preciso **aceitar os cookies** uma vez
   (a sessão persiste no perfil depois disso).

5. **Inputs controlados por framework (React/Vue).** Setar `el.value`
   diretamente não atualiza o estado do framework (o campo "volta" a vazio).
   O `JS_ESCREVER` do browser.py foi corrigido para usar o **setter nativo**
   do protótipo (`HTMLInputElement.prototype.value`) + eventos `input`/`change`.

6. **`load_profile` só vale após REINICIAR o browser.** O Chromium lê o cookie
   store no boot; restaurar os arquivos por baixo de uma sessão viva não loga
   na hora — é preciso reiniciar o processo (não só recarregar a página).

## Perfis / persistência

- Perfil em disco (live): `~/travian/profile`
- Backup logado (tar.gz): `~/travian/travian.tar.gz` (~7.5M, contém `Cookies`,
  `Local Storage`, `Network Persistent State`).
- Ciclo validado: **logado → save_profile → apagar perfil → DESLOGADO →
  load_profile → reiniciar → LOGADO** (login preservado sem redigitar senha).

## Como rodar com janela visível

```bash
# browser visível no display real, servindo comandos na porta 9000
DISPLAY=:0 .venv/bin/python browser.py --servir 9000 -d ~/travian/profile

# em outro processo, manda o roteiro pelo socket
.venv/bin/python cliente.py -p 9000 '<json do lote>'
```

> Credenciais nunca em arquivo versionado: passar por variável de ambiente
> (`TRAVIAN_EMAIL` / `TRAVIAN_PASSWORD`) e injetar no lote, como nos `run.py`.
