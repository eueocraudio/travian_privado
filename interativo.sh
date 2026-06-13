#!/usr/bin/env bash
#
# interativo.sh — sobe o bot perguntando SERVER e CONTA por teclado. Cada conta
# ganha sua própria porta (9001..10000) e, portanto, seu próprio browser/perfil.
# Toda a lógica de subir browser/login/loop fica no iniciar.sh; este script só
# coleta as respostas e delega:
#
#   iniciar.sh --server <host> --account <user> --porta <livre> [ciclo|loop]
#
# Para subir TODAS as contas de uma vez (sem perguntar), use o jogar.sh — a
# opção "(all)" no menu (ou o argumento "all") apenas delega para ele.
#
# Uso:
#   ./interativo.sh           # pergunta server+conta e entra no loop
#   ./interativo.sh ciclo     # pergunta server+conta e roda só uma passada
#   ./interativo.sh all       # delega ao jogar.sh (todas as contas em paralelo)
#
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Dados de usuário (contas/perfil) ficam em ~/travian por padrão.
DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
ACC="$DADOS/account"

# Argumentos (ordem livre): "all" delega ao jogar.sh; loop|ciclo é o comando.
MODO="single"; COMANDO="loop"
for a in "$@"; do
  case "$a" in
    all)        MODO="all" ;;
    loop|ciclo) COMANDO="$a" ;;
    *) echo "argumento desconhecido: $a (use: all | loop | ciclo)" >&2; exit 2 ;;
  esac
done

# Próxima porta livre acima da última atribuída (no fluxo single, basta a 1ª).
ULTIMA_PORTA=9000
proxima_porta() {
  local p
  for p in $(seq $((ULTIMA_PORTA + 1)) 10000); do
    ss -ltn 2>/dev/null | grep -qE "127\.0\.0\.1:$p\b" && continue
    ULTIMA_PORTA="$p"; echo "$p"; return 0
  done
  return 1
}

# Subdiretórios (1 nível) de um caminho, ordenados.
listar_dirs() {
  [ -d "$1" ] || return 0
  find "$1" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort
}

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

# --- all: delega ao script não-interativo jogar.sh ---
if [ "$MODO" = "all" ]; then
  exec "$RAIZ/jogar.sh" "$COMANDO"
fi

# --- fluxo single: pergunta server (com opção (all)) e conta ---
SERVERS=()
mapfile -t SERVERS < <(listar_dirs "$ACC")
SERVER="$(escolher "server" "${SERVERS[@]}" "(all)")"
[ -n "${SERVER:-}" ] || { echo "server vazio." >&2; exit 1; }
if [ "$SERVER" = "(all)" ]; then
  exec "$RAIZ/jogar.sh" "$COMANDO"
fi

CONTAS=()
mapfile -t CONTAS < <(listar_dirs "$ACC/$SERVER")
ACCOUNT="$(escolher "conta" "${CONTAS[@]}")"
[ -n "${ACCOUNT:-}" ] || { echo "conta vazia." >&2; exit 1; }

PORTA="$(proxima_porta)" || { echo "sem porta livre em 9001..10000." >&2; exit 1; }
echo "==> $SERVER / $ACCOUNT  (porta $PORTA, comando $COMANDO)"
exec "$RAIZ/iniciar.sh" --server "$SERVER" --account "$ACCOUNT" --porta "$PORTA" "$COMANDO"
