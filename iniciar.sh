#!/usr/bin/env bash
#
# iniciar.sh — sobe todo o processo do bot Travian por terminal:
#   1) inicia o browser servidor (janela visível) se não estiver no ar
#   2) garante o login
#   3) roda o loop executor (travian.py loop)
#
# Uso:
#   ~/travian/iniciar.sh          # sobe tudo e entra no loop
#   ~/travian/iniciar.sh ciclo    # só uma passada (teste), sem loop
#   ~/travian/iniciar.sh parar    # encerra o browser servidor
#
set -u

REPO="$HOME/desenv/craudiowebot"
RAIZ="$HOME/desenv/travian_privado"
PY="$REPO/.venv/bin/python"
PORTA=9000
PROFILE="$RAIZ/profile"
export DISPLAY="${DISPLAY:-:0}"
# libxcb-cursor0 (exigida pelo Qt >=6.5) ficou fora do path padrão neste
# Debian/Qubes; aponta o linker pra ela senão o plugin 'xcb' não carrega.
LIBXCB="$HOME/.cache/unuser/lib"
# conta (servidor/usuário); travian.py também resolve sozinho se só houver uma
export TRAVIAN_ACCOUNT="${TRAVIAN_ACCOUNT:-ts6.x1.america.travian.com/wellington.aied}"

porta_no_ar() { ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORTA"; }

parar() {
  echo "==> encerrando browser servidor (porta $PORTA)"
  pkill -f "browser.py --servir $PORTA" 2>/dev/null
  echo "ok"
}

subir_browser() {
  if porta_no_ar; then
    echo "==> browser já está no ar na porta $PORTA"
    return 0
  fi
  echo "==> iniciando browser servidor (DISPLAY=$DISPLAY, perfil $PROFILE)"
  ( cd "$REPO" && LD_LIBRARY_PATH="$LIBXCB:${LD_LIBRARY_PATH:-}" \
      nohup "$PY" browser.py --servir "$PORTA" -d "$PROFILE" \
      >/tmp/travian_browser.log 2>&1 & )
  for _ in $(seq 1 40); do
    porta_no_ar && { echo "    pronto."; return 0; }
    sleep 1
  done
  echo "ERRO: browser não subiu (veja /tmp/travian_browser.log)" >&2
  return 1
}

case "${1:-loop}" in
  parar) parar; exit 0 ;;
esac

subir_browser || exit 1

echo "==> garantindo login"
"$PY" "$RAIZ/travian.py" login

case "${1:-loop}" in
  ciclo) echo "==> uma passada (ciclo)"; "$PY" "$RAIZ/travian.py" ciclo ;;
  *)     echo "==> entrando no loop (Ctrl+C para parar)"; "$PY" "$RAIZ/travian.py" loop ;;
esac
