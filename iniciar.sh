#!/usr/bin/env bash
#
# iniciar.sh — sobe TODO o processo do bot Travian por terminal, do zero:
#   0) instala o que faltar (venv + PySide6 do browser servidor)
#   1) garante a libxcb-cursor0 (exigida pelo Qt) no caminho do linker
#   2) restaura credenciais (account/.env + sqlite) se sumiram da árvore
#   3) inicia o browser servidor (janela visível) se não estiver no ar
#   4) garante o login
#   5) roda o loop executor (travian.py loop)
#
# Não precisa de NENHUM outro comando antes: rode e pronto.
#
# Uso:
#   ./iniciar.sh                                       # conta default, porta 9000, loop
#   ./iniciar.sh --server <host> --account <user> [--porta N] [ciclo|loop]
#   ./iniciar.sh [--porta N] parar                     # encerra o browser daquela porta
#
# Sem --server/--account usa a conta default e o perfil plano (profile/),
# preservando a sessão já logada. Com server/account cada conta ganha um perfil
# isolado em profile/<server>/<user> e (via interativo.sh) sua própria porta
# 9001..10000 — assim dá pra rodar várias contas/browsers em paralelo.
# Para a UI interativa que pergunta server/conta por teclado, use interativo.sh.
set -u

# Raiz do bot = onde este script está (funciona chamado de qualquer lugar).
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo do browser servidor (sobrescrevível por env).
REPO="${CRAUDIOWEBOT:-$HOME/desenv/craudiowebot}"
PY="$REPO/.venv/bin/python"          # python do browser (PySide6)
PY_BOT="${PYTHON:-python3}"          # python do bot (só stdlib)
# Dados de usuário (contas/perfil/tarball) ficam FORA do checkout, em ~/travian
# por padrão. Exportado p/ o travian.py herdar (resolve as contas a partir daqui).
export TRAVIAN_DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
DADOS="$TRAVIAN_DADOS"
export DISPLAY="${DISPLAY:-:0}"
# libxcb-cursor0 (exigida pelo Qt >=6.5) ficou fora do path padrão neste
# Debian/Qubes; aponta o linker pra ela senão o plugin 'xcb' não carrega.
LIBXCB="${LIBXCB_DIR:-$HOME/.cache/unuser/lib}"

# --- parâmetros por linha de comando -------------------------------------
SERVER=""; ACCOUNT=""; PORTA_CLI=""; COMANDO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --server)  SERVER="${2:-}";  shift 2 ;;
    --account) ACCOUNT="${2:-}"; shift 2 ;;
    --porta)   PORTA_CLI="${2:-}"; shift 2 ;;
    parar|ciclo|loop|abrir) COMANDO="$1"; shift ;;
    *) echo "ERRO: argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done
COMANDO="${COMANDO:-loop}"

# Conta: --server/--account têm prioridade; senão cai no env/default antigo.
if [ -n "$SERVER" ] || [ -n "$ACCOUNT" ]; then
  if [ -z "$SERVER" ] || [ -z "$ACCOUNT" ]; then
    echo "ERRO: informe --server E --account juntos." >&2; exit 2
  fi
  export TRAVIAN_ACCOUNT="$SERVER/$ACCOUNT"
else
  # conta default; travian.py também resolve sozinho se só houver uma.
  export TRAVIAN_ACCOUNT="${TRAVIAN_ACCOUNT:-ts6.x1.america.travian.com/wellington.aied}"
fi
# Cada conta é autocontida: o perfil vivo do browser e o backup .tar.gz ficam
# DENTRO do diretório da conta, ao lado do .env e do travian.sqlite.
CONTA_DIR="$DADOS/account/$TRAVIAN_ACCOUNT"
PROFILE="$CONTA_DIR/profile"
export TRAVIAN_TAR="$CONTA_DIR/travian.tar.gz"

# Porta: --porta > env PORTA > 9000. Exportada p/ o travian.py (lê PORTA do env).
export PORTA="${PORTA_CLI:-${PORTA:-9000}}"

porta_no_ar() { ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORTA"; }

# libxcb-cursor já visível ao linker (cache do ldconfig ou paths padrão)?
xcb_no_path() {
  ldconfig -p 2>/dev/null | grep -q "libxcb-cursor.so" && return 0
  for d in /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu /lib/x86_64-linux-gnu; do
    ls "$d"/libxcb-cursor.so.* >/dev/null 2>&1 && return 0
  done
  return 1
}

# Monta o LD_LIBRARY_PATH do browser: só injeta o diretório alternativo se a
# lib não estiver no caminho padrão E existir lá.
ld_browser() {
  if ! xcb_no_path && ls "$LIBXCB"/libxcb-cursor.so.* >/dev/null 2>&1; then
    echo "$LIBXCB:${LD_LIBRARY_PATH:-}"
  else
    echo "${LD_LIBRARY_PATH:-}"
  fi
}

parar() {
  echo "==> encerrando browser servidor (porta $PORTA)"
  pkill -f "browser.py --servir $PORTA" 2>/dev/null
  echo "ok"
}

# 0) Instala o browser (venv + PySide6) se ainda não dá pra importar QtWebEngine.
garantir_instalacao() {
  if [ -x "$PY" ] && \
     QT_QPA_PLATFORM=offscreen "$PY" -c \
       "from PySide6.QtWebEngineWidgets import QWebEngineView" >/dev/null 2>&1; then
    echo "==> dependências do browser OK"
    return 0
  fi
  echo "==> instalando dependências do browser (primeira vez)"
  if [ ! -x "$REPO/install.sh" ]; then
    echo "ERRO: não achei $REPO/install.sh (defina CRAUDIOWEBOT=...)." >&2
    return 1
  fi
  ( cd "$REPO" && ./install.sh ) || {
    echo "ERRO: install.sh falhou (provável falta de libs de sistema; veja acima)." >&2
    return 1
  }
  # revalida
  QT_QPA_PLATFORM=offscreen "$PY" -c \
    "from PySide6.QtWebEngineWidgets import QWebEngineView" >/dev/null 2>&1 || {
      echo "ERRO: QtWebEngine ainda não importa após o install." >&2
      return 1
    }
}

# 2) Garante que existem credenciais (.env) da conta nos dados de usuário.
garantir_conta() {
  local env="$DADOS/account/$TRAVIAN_ACCOUNT/.env"
  if [ -f "$env" ]; then return 0; fi
  echo "ERRO: sem credenciais em $env" >&2
  echo "       crie account/<server>/<user>/.env em $DADOS" >&2
  return 1
}

subir_browser() {
  if porta_no_ar; then
    echo "==> browser já está no ar na porta $PORTA"
    return 0
  fi
  echo "==> iniciando browser servidor (DISPLAY=$DISPLAY, perfil $PROFILE)"
  mkdir -p "$PROFILE"
  ( cd "$REPO" && LD_LIBRARY_PATH="$(ld_browser)" \
      nohup "$PY" browser.py --servir "$PORTA" -d "$PROFILE" \
      >/tmp/travian_browser.log 2>&1 & )
  for _ in $(seq 1 40); do
    porta_no_ar && { echo "    pronto."; return 0; }
    sleep 1
  done
  echo "ERRO: browser não subiu (veja /tmp/travian_browser.log)" >&2
  return 1
}

if [ "$COMANDO" = "parar" ]; then
  parar; exit 0
fi

echo "==> conta $TRAVIAN_ACCOUNT | porta $PORTA | perfil $PROFILE"
garantir_instalacao || exit 1
garantir_conta      || exit 1
subir_browser       || exit 1

echo "==> garantindo login"
"$PY_BOT" "$RAIZ/travian.py" login || exit 1

case "$COMANDO" in
  abrir) echo "==> browser aberto e logado (em dorf1) na porta $PORTA — não entra no loop." ;;
  ciclo) echo "==> uma passada (ciclo)"; "$PY_BOT" "$RAIZ/travian.py" ciclo ;;
  *)     echo "==> entrando no loop (Ctrl+C para parar)"; "$PY_BOT" -u "$RAIZ/travian.py" loop ;;
esac
