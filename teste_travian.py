#!/usr/bin/env python3
"""
Script de teste em tempo de execucao contra o browser em modo --servir.

Fluxo (enviado pelo socket para o browser ja aberto):
  1. tenta carregar o travian.tar.gz da conta (se nao existir, so avisa)
  2. navega para o loginLobby do Travian
  3. informa usuario e senha
  4. clica no primeiro botao com class 'playNow'
  5. le a URL atual; se chegou em dorf1.php, salva o travian.tar.gz da conta

O perfil do browser e o backup .tar.gz ficam DENTRO do diretorio da conta:
  ~/travian/account/<server>/<user>/{profile,travian.tar.gz}
Sobrescreva o tarball com TRAVIAN_TAR (o iniciar.sh ja exporta esse caminho).

Credenciais vem de variaveis de ambiente (nunca no arquivo):
    export TRAVIAN_EMAIL=...  TRAVIAN_PASSWORD=...
    CONTA=~/travian/account/ts6.x1.america.travian.com/wellington.aied
    python3 browser.py --servir 9000 -d "$CONTA/profile" &
    python3 teste_travian.py
"""

import json
import os
import sys

from cliente import enviar

PORTA = int(os.environ.get("PORTA", "9000"))
TAR = os.environ.get(
    "TRAVIAN_TAR",
    "~/travian/account/ts6.x1.america.travian.com/wellington.aied/travian.tar.gz")
DORF1 = "https://ts6.x1.america.travian.com/dorf1.php"
EMAIL = os.environ.get("TRAVIAN_EMAIL", "")
SENHA = os.environ.get("TRAVIAN_PASSWORD", "")

# seletores descobertos na pagina de login:
#   usuario  -> <input name="name" placeholder="Email address / account name">
#   senha    -> <input name="password" type="password">
#   playNow  -> primeiro <button class="...playNow...">
XP_USUARIO = "//input[@name='name']"
XP_SENHA = "//input[@name='password']"
XP_PLAYNOW = "(//button[contains(@class,'playNow')])[1]"

LOGIN = {
    "actions": [
        {"type": "load_profile", "value": TAR},
        {"type": "navigate", "value": "https://www.travian.com/br#loginLobby"},
        {"type": "sleep", "value": 6},
        {"type": "key", "xpath": XP_USUARIO, "value": EMAIL},
        {"type": "key", "xpath": XP_SENHA, "value": SENHA},
        {"type": "click", "xpath": XP_PLAYNOW},
        {"type": "sleep", "value": 8},
        {"type": "url", "id": "apos_login"},
    ]
}


def main():
    (resp,) = enviar([json.dumps(LOGIN)], porta=PORTA)
    url = next((r["url"] for r in resp.get("resultados", [])
                if r.get("type") == "url"), None)
    print("URL apos o login:", url)

    if url and url.startswith(DORF1):
        print("Cheguei em dorf1.php -> salvando profile")
        (s,) = enviar([json.dumps({"type": "save_profile", "value": TAR})],
                      porta=PORTA)
        print(json.dumps(s, ensure_ascii=False))
    else:
        print("Nao cheguei em dorf1.php -> profile NAO salvo")
        sys.exit(1)


if __name__ == "__main__":
    main()
