#!/usr/bin/env bash
#
# jogar.sh — NÃO-INTERATIVO: sobe e joga TODAS as contas em paralelo, cada uma
# com seu próprio browser/porta/perfil. Não pergunta nada. No modo loop fica de
# supervisor: a cada ALL_INTERVALO segundos (padrão 30) relista as contas e sobe
# um novo browser para qualquer conta nova (cadastrada depois) ou que caiu.
#
# Uso:
#   ./jogar.sh          # todas as contas em loop (supervisionado)
#   ./jogar.sh ciclo    # todas as contas, uma passada cada (one-shot)
#
# Ctrl+C encerra todos os loops e derruba os browsers das portas usadas.
# Cada conta = account/<server>/<user>/ em ~/travian (TRAVIAN_DADOS).
#
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
ACC="$DADOS/account"

COMANDO="loop"
for a in "$@"; do
  case "$a" in
    loop|ciclo) COMANDO="$a" ;;
    *) echo "argumento desconhecido: $a (use: loop | ciclo)" >&2; exit 2 ;;
  esac
done

INTERVALO_ALL="${ALL_INTERVALO:-30}"   # segundos entre varreduras (modo loop)
ULTIMA_PORTA=9000                      # contador de portas (9001..10000)
declare -A ALL_PORTA=()                # conta -> porta
declare -A ALL_PID=()                  # conta -> pid do iniciar.sh

# Próxima porta livre acima da última atribuída (evita corrida: o browser leva
# alguns segundos para ocupar a porta, então não confiamos só no 'ss').
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

# Todas as contas como "server/user".
listar_todas_contas() {
  local srv usr
  for srv in $(listar_dirs "$ACC"); do
    for usr in $(listar_dirs "$ACC/$srv"); do
      echo "$srv/$usr"
    done
  done
}

# Ctrl+C: derruba os browsers (nohup, desacoplados) das portas que subimos.
_limpar_all() {
  echo; echo "== encerrando: parando browsers das portas usadas =="
  local c
  for c in "${!ALL_PORTA[@]}"; do
    "$RAIZ/iniciar.sh" --porta "${ALL_PORTA[$c]}" parar >/dev/null 2>&1
  done
  exit 0
}

# Sobe UMA conta em paralelo (browser/porta próprios) e registra pid/porta.
_subir_conta() {
  local conta="$1" srv usr porta log
  srv="${conta%%/*}"; usr="${conta#*/}"
  porta="$(proxima_porta)" || { echo "  sem porta livre p/ $conta" >&2; return 1; }
  log="$DADOS/logs/${srv}__${usr}.log"
  echo "  + subindo $conta  porta $porta  (log: $log)"
  "$RAIZ/iniciar.sh" --server "$srv" --account "$usr" --porta "$porta" \
      "$COMANDO" >>"$log" 2>&1 &
  ALL_PID[$conta]="$!"; ALL_PORTA[$conta]="$porta"
  sleep 2   # respiro entre browsers (cada um é pesado)
}

mkdir -p "$DADOS/logs"
[ -n "$(listar_todas_contas)" ] || { echo "nenhuma conta em $ACC" >&2; exit 1; }
trap _limpar_all INT TERM
echo "== jogar TODAS as contas (comando: $COMANDO) =="

while true; do
  novas=0
  while IFS= read -r conta; do
    [ -n "$conta" ] || continue
    if [ -n "${ALL_PORTA[$conta]:-}" ]; then
      # já lançada: se o processo ainda vive, nada a fazer.
      kill -0 "${ALL_PID[$conta]:-0}" 2>/dev/null && continue
      # caiu -> derruba o browser antigo e relança numa porta nova.
      "$RAIZ/iniciar.sh" --porta "${ALL_PORTA[$conta]}" parar >/dev/null 2>&1
      echo "  ! $conta caiu -> relançando"
    fi
    _subir_conta "$conta" && novas=$((novas + 1))
  done < <(listar_todas_contas)
  if [ "$COMANDO" = "ciclo" ]; then
    wait; break                       # uma passada só: não faz sentido vigiar
  fi
  [ "$novas" -gt 0 ] && echo "  (${#ALL_PORTA[@]} no ar; vigiando contas novas a cada ${INTERVALO_ALL}s; Ctrl+C encerra)"
  sleep "$INTERVALO_ALL"
done
