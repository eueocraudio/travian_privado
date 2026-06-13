#!/usr/bin/env bash
#
# cadastrar.sh — cadastra uma NOVA conta do bot: cria
# ~/travian/account/<server>/<user>/.env a partir do .env.template, preenchendo
# servidor, e-mail e senha. As demais chaves ficam com os defaults do template
# (a verificação do iniciar.sh então passa sem avisos).
#
# Uso:
#   ./cadastrar.sh                       # pergunta tudo por teclado
#   ./cadastrar.sh --server ts6.x1.america.travian.com --email voce@x.com \
#                  [--user fulano] [--senha ****] [--base https://...] [--force]
#
# A senha, se não vier por --senha, é lida sem aparecer na tela. Depois é só
# rodar ./interativo.sh (a nova conta aparece no menu) ou
# TRAVIAN_ACCOUNT="<server>/<user>" python3 travian.py status.
#
set -u

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DADOS="${TRAVIAN_DADOS:-$HOME/travian}"
ACC="$DADOS/account"
TEMPLATE="$RAIZ/.env.template"

SERVER=""; USERN=""; EMAIL=""; SENHA=""; BASE=""; FORCE=0; SENHA_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="${2:-}"; shift 2 ;;
    --user)   USERN="${2:-}";  shift 2 ;;
    --email)  EMAIL="${2:-}";  shift 2 ;;
    --senha)  SENHA="${2:-}"; SENHA_SET=1; shift 2 ;;
    --base)   BASE="${2:-}";   shift 2 ;;
    --force)  FORCE=1; shift ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

# Pergunta com default opcional; ecoa o valor escolhido no stdout.
perguntar() {
  local rotulo="$1" def="${2:-}" v
  if [ -n "$def" ]; then printf '%s [%s]: ' "$rotulo" "$def" >&2
  else                   printf '%s: ' "$rotulo" >&2
  fi
  read -r v
  echo "${v:-$def}"
}

[ -n "$SERVER" ] || SERVER="$(perguntar "Servidor (host, ex: ts6.x1.america.travian.com)")"
[ -n "$SERVER" ] || { echo "servidor vazio." >&2; exit 1; }
[ -n "$EMAIL" ]  || EMAIL="$(perguntar "E-mail de login")"
[ -n "$EMAIL" ]  || { echo "e-mail vazio." >&2; exit 1; }
[ -n "$USERN" ]  || USERN="$(perguntar "Usuário (nome da pasta da conta)" "${EMAIL%@*}")"
[ -n "$USERN" ]  || { echo "usuário vazio." >&2; exit 1; }
[ -n "$BASE" ]   || BASE="https://$SERVER"
if [ "$SENHA_SET" -eq 0 ]; then
  printf 'Senha (não aparece): ' >&2; read -rs SENHA; echo >&2
fi
[ -n "$SENHA" ] || { echo "senha vazia." >&2; exit 1; }

DEST="$ACC/$SERVER/$USERN"
ENVF="$DEST/.env"
if [ -f "$ENVF" ] && [ "$FORCE" -eq 0 ]; then
  printf 'Já existe %s. Sobrescrever? [s/N]: ' "$ENVF" >&2
  read -r r; case "$r" in s|S|sim|Sim|y|Y) ;; *) echo "cancelado." >&2; exit 1 ;; esac
fi

mkdir -p "$DEST"
# Gera o .env do template trocando só as 3 credenciais (Python evita problemas
# de escaping com senhas que tenham / & etc.; valores vão por env, não por argv,
# pra senha não vazar em 'ps').
TRAVIAN_BASE="$BASE" TRAVIAN_EMAIL="$EMAIL" TRAVIAN_PASSWORD="$SENHA" \
TEMPLATE="$TEMPLATE" python3 - >"$ENVF" <<'PY'
import os, re
t = os.environ.get("TEMPLATE", "")
tpl = open(t, encoding="utf-8").read() if os.path.isfile(t) else ""
vals = {k: os.environ[k] for k in ("TRAVIAN_BASE", "TRAVIAN_EMAIL",
                                   "TRAVIAN_PASSWORD")}
out, vistos = [], set()
for linha in tpl.splitlines():
    m = re.match(r'^([A-Z0-9_]+)=', linha)
    if m and m.group(1) in vals:
        out.append("%s=%s" % (m.group(1), vals[m.group(1)])); vistos.add(m.group(1))
    else:
        out.append(linha)
faltam = [k for k in vals if k not in vistos]
if faltam or not tpl:
    out = ["# Conta cadastrada por cadastrar.sh"] + \
          ["%s=%s" % (k, vals[k]) for k in faltam] + out
print("\n".join(out))
PY
chmod 600 "$ENVF" 2>/dev/null || true

echo "== conta cadastrada =="
echo "  dir  : $DEST"
echo "  base : $BASE"
echo "  email: $EMAIL"
echo "Rode: ./interativo.sh   (a conta aparece no menu)"
echo "  ou: TRAVIAN_ACCOUNT=\"$SERVER/$USERN\" python3 \"$RAIZ/travian.py\" status"
