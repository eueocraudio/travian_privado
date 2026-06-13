#!/usr/bin/env bash
#
# interativo.sh — sobe o bot perguntando SERVER e CONTA por teclado, OU sobe
# TODAS as contas em paralelo (opção "(all)"). Cada conta ganha sua própria
# porta (9001..10000) e, portanto, seu próprio browser/perfil. Toda a lógica de
# subir browser/login/loop fica no iniciar.sh; este script só coleta as
# respostas e delega:
#
#   iniciar.sh --server <host> --account <user> --porta <livre> [ciclo|loop]
#
# Uso:
#   ./interativo.sh           # pergunta server+conta e entra no loop
#   ./interativo.sh ciclo     # pergunta server+conta e roda só uma passada
#   ./interativo.sh all       # sobe TODAS as contas em paralelo (loop)
#   ./interativo.sh all ciclo # TODAS as contas em paralelo, uma passada cada
#
# No menu interativo de server também há a opção "(all)" para subir todas.
# Ctrl+C encerra todos os loops e derruba os browsers das portas usadas.
#
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Dados de usuário (contas/perfil) ficam em ~/travian por padrão.
DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
ACC="$DADOS/account"

# Argumentos (ordem livre): "all" liga o modo paralelo; loop|ciclo é o comando.
MODO="single"; COMANDO="loop"
for a in "$@"; do
  case "$a" in
    all)        MODO="all" ;;
    loop|ciclo) COMANDO="$a" ;;
    *) echo "argumento desconhecido: $a (use: all | loop | ciclo)" >&2; exit 2 ;;
  esac
done

# Próxima porta livre acima da última atribuída (evita corrida: o browser leva
# alguns segundos para ocupar a porta, então não confiamos só no 'ss').
ULTIMA_PORTA=9000
proxima_porta() {
  local p
  for p in $(seq $((ULTIMA_PORTA + 1)) 10000); do
    ss -ltn 2>/dev/null | grep -qE "127\.0\.0\.1:$p\b" && continue
    ULTIMA_PORTA="$p"; echo "$p"; return 0
  done
  return 1
}

# Lista subdiretórios (1 nível) de um caminho, ordenados.
listar_dirs() {
  [ -d "$1" ] || return 0
  find "$1" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort
}

# Todas as contas como "server/user".
listar_todas_contas() {
  local srv usr
  for srv in $(listar_dirs "$ACC"); do
    for usr in $(listar_dirs "$ACC/$srv"); do
      echo "$srv/$usr"
    done
  done
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

# Sobe TODAS as contas em paralelo, uma porta/browser por conta.
subir_todas() {
  local contas=()
  mapfile -t contas < <(listar_todas_contas)
  [ "${#contas[@]}" -gt 0 ] || { echo "nenhuma conta em $ACC" >&2; exit 1; }
  local logdir="$DADOS/logs"; mkdir -p "$logdir"
  local pids=() portas=() conta srv usr porta log
  # Ctrl+C: além de matar os loops (mesmo grupo de processo), derruba os
  # browsers (nohup, desacoplados) das portas usadas.
  trap 'echo; echo "== encerrando: parando browsers das portas usadas ==";
        for p in "${portas[@]}"; do "$RAIZ/iniciar.sh" --porta "$p" parar \
          >/dev/null 2>&1; done' INT TERM
  echo "== modo ALL: ${#contas[@]} conta(s) em paralelo (comando: $COMANDO) =="
  for conta in "${contas[@]}"; do
    srv="${conta%%/*}"; usr="${conta#*/}"
    porta="$(proxima_porta)" || { echo "  sem porta livre p/ $conta" >&2; break; }
    log="$logdir/${srv}__${usr}.log"
    echo "  -> $conta  porta $porta  (log: $log)"
    "$RAIZ/iniciar.sh" --server "$srv" --account "$usr" --porta "$porta" \
        "$COMANDO" >"$log" 2>&1 &
    pids+=("$!"); portas+=("$porta")
    sleep 2   # respiro entre browsers (cada um é pesado)
  done
  echo "== ${#pids[@]} processo(s) no ar. Ctrl+C encerra todos. Logs: $logdir =="
  wait
}

# --- modo all direto pela linha de comando ---
if [ "$MODO" = "all" ]; then
  subir_todas
  exit 0
fi

# --- fluxo single: pergunta server (com opção (all)) e conta ---
SERVERS=()
mapfile -t SERVERS < <(listar_dirs "$ACC")
SERVER="$(escolher "server" "${SERVERS[@]}" "(all)")"
[ -n "${SERVER:-}" ] || { echo "server vazio." >&2; exit 1; }
if [ "$SERVER" = "(all)" ]; then
  subir_todas
  exit 0
fi

CONTAS=()
mapfile -t CONTAS < <(listar_dirs "$ACC/$SERVER")
ACCOUNT="$(escolher "conta" "${CONTAS[@]}")"
[ -n "${ACCOUNT:-}" ] || { echo "conta vazia." >&2; exit 1; }

PORTA="$(proxima_porta)" || { echo "sem porta livre em 9001..10000." >&2; exit 1; }
echo "==> $SERVER / $ACCOUNT  (porta $PORTA, comando $COMANDO)"
exec "$RAIZ/iniciar.sh" --server "$SERVER" --account "$ACCOUNT" --porta "$PORTA" "$COMANDO"
