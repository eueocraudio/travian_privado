#!/usr/bin/env bash
#
# Demonstracao VISIVEL do save_profile/load_profile preservando o login real.
# Sinal observavel: ao navegar para o lobby, a URL fica em '/account' quando
# logado, e cai para a tela de login quando deslogado.
#
#   logado -> save_profile -> apaga perfil -> DESLOGADO
#          -> load_profile (do .tar.gz) -> reinicia -> LOGADO de novo
#
set -u
# Perfil e backup vivem dentro do diretorio da conta (sobrescreviveis por env).
CONTA="${TRAVIAN_CONTA:-$HOME/travian/account/ts6.x1.america.travian.com/wellington.aied}"
PROF="${TRAVIAN_PROFILE:-$CONTA/profile}"
TAR="${TRAVIAN_TAR:-$CONTA/travian.tar.gz}"
PORT=9000
PY=.venv/bin/python
LOBBY="https://lobby.legends.travian.com/account"

start() {
  xvfb-run -a -s "-screen 0 1280x1024x24" \
    "$PY" browser.py --servir "$PORT" -d "$PROF" >/tmp/demo_srv.log 2>&1 &
  for _ in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORT" && { sleep 1; return 0; }
    sleep 1
  done
  echo "  !! servidor nao subiu"; return 1
}
stop() { pkill -f "browser.py --servir $PORT" 2>/dev/null; pkill Xvfb 2>/dev/null; sleep 2; }

estado_login() {   # navega ao lobby e diz LOGADO/DESLOGADO + a URL
  "$PY" cliente.py -p "$PORT" \
    "{\"actions\":[{\"type\":\"navigate\",\"value\":\"$LOBBY\"},{\"type\":\"sleep\",\"value\":8},{\"type\":\"url\"}]}" \
    2>/dev/null | "$PY" -c 'import sys,json
d=json.load(sys.stdin)
u=[x["url"] for x in d["resultados"] if x["type"]=="url"][0]
print("  URL:", u)
print("  ESTADO:", "LOGADO" if "/account" in u else "DESLOGADO")'
}

echo "######## FASE 1: sessao atual + salvar perfil ########"
start || exit 1
echo "[1a] estado inicial (perfil em disco tem os cookies):"
estado_login
echo "[1b] save_profile -> $TAR (cria ~/profiles se faltar):"
"$PY" cliente.py -p "$PORT" "{\"type\":\"save_profile\",\"value\":\"$TAR\"}" 2>/dev/null | grep -E '"ok"'
stop
echo "[1c] tarball gerado:"; ls -lh "$TAR" 2>&1 | awk '{print "  "$5, $9}'
echo "      contem cookies?"; tar tzf "$TAR" 2>/dev/null | grep -i '^Cookies$' | sed 's/^/      /'

echo
echo "######## FASE 2: apagar perfil -> deve DESLOGAR ########"
rm -rf "$PROF"; echo "  perfil apagado: $PROF"
start || exit 1
echo "[2a] estado com perfil vazio:"
estado_login
echo "[2b] load_profile <- $TAR (restaura os arquivos):"
"$PY" cliente.py -p "$PORT" "{\"type\":\"load_profile\",\"value\":\"$TAR\"}" 2>/dev/null | grep -E '"ok"'
stop

echo
echo "######## FASE 3: reiniciar com perfil restaurado -> deve LOGAR ########"
start || exit 1
echo "[3a] estado apos restaurar do tarball:"
estado_login
stop
echo
echo "######## fim ########"
