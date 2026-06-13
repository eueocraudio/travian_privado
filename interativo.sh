#!/usr/bin/env bash
#
# interativo.sh — sobe o bot perguntando SERVER e CONTA por teclado.
#
# Cada conta escolhida ganha sua própria porta (9001..10000) e, portanto, seu
# próprio browser/perfil — então dá pra abrir um terminal por conta e rodar
# várias em paralelo. Toda a lógica de subir browser/login/loop fica no
# iniciar.sh; este script só coleta as respostas e delega:
#
#   iniciar.sh --server <host> --account <user> --porta <livre> [ciclo|loop]
#
# Uso:
#   ./interativo.sh           # pergunta tudo e entra no loop
#   ./interativo.sh ciclo     # pergunta tudo e roda só uma passada
#
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Dados de usuário (contas/perfil) ficam em ~/travian por padrão.
DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
ACC="$DADOS/account"
COMANDO="${1:-loop}"

# Pergunta escolhendo de uma lista (ou digitando). $1 = rótulo, demais = opções.
escolher() {
  local rotulo="$1"; shift
  local opcoes=("$@")
  local escolha
  if [ "${#opcoes[@]}" -eq 0 ]; then
    printf 'Nenhum %s encontrado. Digite o valor: ' "$rotulo" >&2
    read -r escolha
    echo "$escolha"; return
  fi
  echo "Escolha o $rotulo:" >&2
  select escolha in "${opcoes[@]}" "(outro: digitar)"; do
    [ -n "${escolha:-}" ] || continue
    if [ "$escolha" = "(outro: digitar)" ]; then
      printf 'Digite o %s: ' "$rotulo" >&2
      read -r escolha
    fi
    break
  done
  echo "$escolha"
}

# Lista subdiretórios (1 nível) de um caminho, ordenados.
listar_dirs() {
  [ -d "$1" ] || return 0
  find "$1" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort
}

# 1) SERVER
mapfile -t SERVERS < <(listar_dirs "$ACC")
SERVER="$(escolher "server" "${SERVERS[@]}")"
[ -n "${SERVER:-}" ] || { echo "server vazio." >&2; exit 1; }

# 2) CONTA dentro do server
mapfile -t CONTAS < <(listar_dirs "$ACC/$SERVER")
ACCOUNT="$(escolher "conta" "${CONTAS[@]}")"
[ -n "${ACCOUNT:-}" ] || { echo "conta vazia." >&2; exit 1; }

# 3) primeira porta livre em 9001..10000
porta_livre() {
  local p
  for p in $(seq 9001 10000); do
    ss -ltn 2>/dev/null | grep -qE "127\.0\.0\.1:$p\b" || { echo "$p"; return 0; }
  done
  return 1
}
PORTA="$(porta_livre)" || { echo "sem porta livre em 9001..10000." >&2; exit 1; }

echo "==> $SERVER / $ACCOUNT  (porta $PORTA, comando $COMANDO)"
exec "$RAIZ/iniciar.sh" --server "$SERVER" --account "$ACCOUNT" --porta "$PORTA" "$COMANDO"
