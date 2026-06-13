#!/usr/bin/env python3
"""
travian.py — automação do Travian sobre o craudiowebot (modo --servir).

Pré-requisito: o browser rodando como servidor (ver iniciar.sh):

    DISPLAY=:0 .venv/bin/python browser.py --servir 9000 -d <perfil>

Este módulo fala com esse servidor por socket (NDJSON) e implementa a lógica
de jogo aprendida em docs/. O executor (ciclo/loop) tem 3 níveis de prioridade
de scripts (ver o registro SCRIPTS abaixo):
  1) IMEDIATO  — slot one-shot meta['proximo_imediato'] (ex.: transferir após
     um build falhar por falta de recurso); roda na frente de tudo no ciclo;
  2) AGENDADOS — disparam por horário/evento (gate de tempo no SQLite): obras
     de dorf1/dorf2, scan do mapa (1x/dia), transferir, esconderijo, oásis;
  3) LOOP      — a cada ciclo: missões, relatórios, tarefas diárias, herói
     (aventura + atributos), movimentos de tropa.

Construção: NÃO navega à tela de construção se o SQLite mostra obra em
andamento naquele dorf (fim ainda no futuro); a fila de construção do jogo é
GLOBAL, então fim_construcao classifica cada item por nome (campo x edifício).

Multi-server / multi-user. Cada conta vive em:
    account/<servidor>/<usuario>/
        .env            -> TRAVIAN_BASE/EMAIL/PASSWORD + config (HEROI_ATRIBUTO,
                           DORF2_PCT_NOVO, DORF2_NOVOS, CRANNY_NIVEL_ALVO,
                           OASIS_ATIVO, OASIS_HEROI_OBRIGATORIO)
        travian.sqlite  -> histórico (acoes, estado, construcoes, oasis, ...)
A conta é escolhida por TRAVIAN_ACCOUNT="<servidor>/<usuario>"; se houver só
uma conta, é usada automaticamente. Todo comando é registrado no SQLite.

Uso: python3 travian.py <comando>
    status | login | collect | storage | adventure | transfer | hero [estrat]
    evolve [dorf1|dorf2] | upgrade <slot> <gid>
    daily | reports | scan [force] | movimentos | oasis
    ciclo            # uma passada do executor
    loop             # executor contínuo (dorme até o próximo evento)

    # outra conta:  TRAVIAN_ACCOUNT="ts6.x1.america.travian.com/wellington.aied" \\
    #               python3 travian.py status
"""

import json
import os
import random
import re
import socket
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from glob import glob

HOST = "127.0.0.1"
PORTA = int(os.environ.get("PORTA", "9000"))
# comportamento humano: pausa aleatória entre navegações e fixa entre toques
SLEEP_NAV_MIN, SLEEP_NAV_MAX = 1, 5   # segundos (aleatório) entre navegações
SLEEP_TOQUE = 1                       # segundo entre toques na mesma tela
# fallbacks (a conta resolvida do account/<server>/<user>/.env tem prioridade)
BASE = os.environ.get("TRAVIAN_BASE", "https://ts6.x1.america.travian.com")
EMAIL = os.environ.get("TRAVIAN_EMAIL", "")
SENHA = os.environ.get("TRAVIAN_PASSWORD", "")

# gid dos edifícios de armazenamento (usados em garantir_armazenamento)
GID_CELEIRO = 11
GID_ARMAZEM = 10
RECURSOS = ["madeira", "barro", "ferro", "cereal"]
IDS_ESTOQUE = {"madeira": "l1", "barro": "l2", "ferro": "l3", "cereal": "l4"}

# Registro de TODOS os scripts (tarefas) do bot. Prioridade (maior -> menor):
#   1) IMEDIATO  -> slot one-shot meta['proximo_imediato']; roda já no próximo
#                   ciclo, na frente de tudo (agendar_imediato(db, "nome")).
#   2) "agendado"-> dispara em horário/evento (gate de tempo).
#   3) "loop"    -> roda a cada passada do ciclo().
# 'feito' = já implementado em travian.py; False = planejado (ainda não existe).
SCRIPTS = {
    # ---- agendados (prioridade sobre os de loop) ----
    "construir_dorf1": {"tipo": "agendado", "feito": True},   # subir campo
    "construir_dorf2": {"tipo": "agendado", "feito": True},   # subir edifício
    "scan_mapa":       {"tipo": "agendado", "feito": True},   # 1x/dia
    # dispara +1min DEPOIS de um build (dorf1/dorf2) falhar por FALTA DE
    # RECURSO — leva recurso do herói p/ o depósito e a obra entra no próximo
    # ciclo. NÃO roda todo ciclo (era 'loop'; reclassificado para agendado).
    "transferir_recursos": {"tipo": "agendado", "feito": True},
    # esconderijo: realizado DENTRO de construir_dorf2 (decidir_dorf2). Rampa
    # probabilística "na sorte" sobe com o fim da proteção; alvo ~2000 de cap.
    "esconderijo":     {"tipo": "agendado", "feito": True},
    # atacar_oasis: assalto a oásis sem defesa (gated por OASIS_ATIVO no .env;
    # aventura SEMPRE roda antes no ciclo). Conservador: só sem_tropas=1.
    "atacar_oasis":    {"tipo": "agendado", "feito": True},
    # ---- loop (a cada ciclo) ----
    "recolher_missoes":  {"tipo": "loop", "feito": True},
    "ler_relatorios":    {"tipo": "loop", "feito": True},
    "tarefas_diarias":   {"tipo": "loop", "feito": True},
    "aventura":          {"tipo": "loop", "feito": True},
    "evoluir_heroi":     {"tipo": "loop", "feito": True},
    "ler_movimentos":    {"tipo": "loop", "feito": True},
}


def _num(s):
    """Extrai inteiro de uma string (descarta pontuação e marcas bidi ‭ ‬)."""
    return int(re.sub(r"[^0-9]", "", s or "") or 0)


class Travian:
    def __init__(self, host=HOST, porta=PORTA, base=BASE, email=EMAIL, senha=SENHA):
        self.host, self.porta, self.base = host, porta, base
        self.email, self.senha = email, senha

    # ---- ponte com o servidor (socket NDJSON) --------------------------
    def enviar(self, actions):
        """Manda um lote de actions e devolve a lista de 'resultados'."""
        with socket.create_connection((self.host, self.porta)) as s:
            arq = s.makefile("rw", encoding="utf-8", newline="\n")
            arq.write(json.dumps({"actions": actions}, ensure_ascii=False) + "\n")
            arq.flush()
            return json.loads(arq.readline()).get("resultados", [])

    def ir(self, url, espera=5):
        """Navega e devolve (url_final, html). Faz uma pausa aleatória
        (SLEEP_NAV_MIN..MAX) ANTES de navegar — comportamento humano — e
        depois espera 'espera' s para a página carregar/renderizar."""
        time.sleep(random.randint(SLEEP_NAV_MIN, SLEEP_NAV_MAX))
        r = self.enviar([
            {"type": "navigate", "value": url},
            {"type": "sleep", "value": espera},
            {"type": "url"},
            {"type": "html"},
        ])
        u = next((x["url"] for x in r if x["type"] == "url"), None)
        h = next((x["html"] for x in r if x["type"] == "html"), "")
        return u, h

    def url_atual(self):
        r = self.enviar([{"type": "url"}])
        return next((x["url"] for x in r if x["type"] == "url"), None)

    # ---- login ---------------------------------------------------------
    def login(self):
        """Loga direto no servidor de jogo (clicar 'Entrar', não Enter cru)."""
        u, _ = self.ir(self.base, 6)
        self.enviar([
            {"type": "key", "xpath": "//input[@name='name']", "value": self.email},
            {"type": "key", "xpath": "//input[@name='password']", "value": self.senha},
            {"type": "click",
             "xpath": "//button[@type='submit' and contains(@class,'buttonFramed')]"},
            {"type": "sleep", "value": 10},
        ])
        return self.url_atual()

    # ---- leitura de estado --------------------------------------------
    def estado(self):
        """Estoque, capacidade e espaço livre de cada recurso (lê o dorf1)."""
        _, html = self.ir(self.base + "/dorf1.php", 5)
        return self.parse_estado(html)

    def parse_estado(self, html):
        est = {"estoque": {}, "capacidade": {}, "livre": {}}
        for nm, i in IDS_ESTOQUE.items():
            m = re.search(r'id="' + i + r'"[^>]*>([^<]*)', html)
            est["estoque"][nm] = _num(m.group(1)) if m else 0
        cap_arm = self._capacidade(html, "warehouse")
        cap_cel = self._capacidade(html, "granary")
        for nm in ["madeira", "barro", "ferro"]:
            est["capacidade"][nm] = cap_arm
        est["capacidade"]["cereal"] = cap_cel
        for nm in RECURSOS:
            est["livre"][nm] = est["capacidade"][nm] - est["estoque"][nm]
        return est

    def _capacidade(self, html, classe):
        """Capacidade do armazém ('warehouse') ou celeiro ('granary')."""
        for m in re.finditer(r'class="[^"]*' + classe + r'[^"]*"', html):
            seg = html[m.start():m.start() + 400]
            cap = re.search(r'class="value"[^>]*>([0-9.,‭‬]+)', seg)
            if cap:
                return _num(cap.group(1))
        return 0

    # ---- herói: vida e aventuras --------------------------------------
    def vida_heroi(self):
        """Saúde do herói em % (lê /hero/attributes). O valor fica num <svg>;
        é preciso remover o conteúdo de <style>/<script> antes do strip."""
        _, html = self.ir(self.base + "/hero/attributes", 6)
        txt = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt).replace("‭", "").replace("‬", "")
        m = re.search(r"Sa[úu]de\D{0,60}?([0-9]{1,3})\b", txt)
        return int(m.group(1)) if m else None

    def num_aventuras(self, html=None):
        """Quantidade de aventuras disponíveis (o número no botão 'adventure')."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 4)
        m = re.search(r'class="[^"]*\badventure\b[^"]*"[^>]*>\s*'
                      r'(?:<[^>]+>\s*)*<div class="content">\s*([0-9]+)',
                      html, re.S)
        return int(m.group(1)) if m else 0

    def heroi_em_aventura(self, html=None):
        """True se o herói já está a caminho de uma aventura. Regra: no dorf1,
        a seção 'tropas saindo' mostra 'Aventura' quando o herói está fora."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 4)
        txt = re.sub(r"<[^>]+>", " ", html)
        return bool(re.search(r"tropas saindo.{0,80}?Aventura", txt, re.S | re.I))

    def fazer_aventura(self, vida_minima=50):
        """Envia o herói à 1ª aventura se: ele NÃO está já em aventura (dorf1
        'tropas saindo' não mostra 'Aventura'), há aventura disponível (>0) e a
        vida está boa (> vida_minima)."""
        if self.heroi_em_aventura():
            return False, "herói já está a caminho de uma aventura"
        n = self.num_aventuras()
        if n <= 0:
            return False, "sem aventuras disponíveis"
        vida = self.vida_heroi()
        if vida is None:
            return False, "não consegui ler a vida do herói"
        if vida <= vida_minima:
            return False, "vida baixa (%d%% <= %d%%)" % (vida, vida_minima)
        self.ir(self.base + "/hero/adventures", 5)
        self.enviar([
            {"type": "click", "xpath": '(//button[contains(.,"Explorar")])[1]'},
            {"type": "sleep", "value": 4},
        ])
        return True, "herói enviado (vida %d%%, %d aventura(s))" % (vida, n)

    # ---- herói: pontos de atributo ------------------------------------
    # 'Pontos de atributos disponíveis' aparecem quando o herói sobe de nível.
    # Inputs: power (força), offBonus (ataque), defBonus (defesa),
    # productionPoints (produção). Estratégia vem do .env (HEROI_ATRIBUTO).
    # ordem dos atributos na página = ordem dos botões "+": power, offBonus,
    # defBonus, productionPoints. Clicar no "+" N vezes habilita o "Salvar".
    ATRIBUTO_PLUS = {"forca": 1, "ataque": 2, "defesa": 3, "producao": 4}

    def pontos_heroi(self, html=None):
        """Quantos pontos de atributo o herói tem para distribuir."""
        if html is None:
            _, html = self.ir(self.base + "/hero/attributes", 6)
        txt = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S)
        txt = re.sub(r"<[^>]+>", " ", txt)
        m = re.search(r"[Pp]ontos dispon\w+[^0-9]{0,12}([0-9]+)", txt)
        return int(m.group(1)) if m else 0

    def evoluir_heroi(self, estrategia="producao"):
        """Maximiza o atributo do foco: clica no '+' do atributo N vezes (N =
        pontos disponíveis) e salva. O '+' registra a mudança que habilita o
        botão 'Salvar' (id=savePoints), que vem disabled no load."""
        idx = self.ATRIBUTO_PLUS.get(estrategia, 4)
        _, html = self.ir(self.base + "/hero/attributes", 6)
        n = self.pontos_heroi(html)
        if n <= 0:
            return False, "sem pontos de atributo para distribuir"
        xp_plus = ('(//button[contains(@class,"buttonFramed") and '
                   'contains(@class,"plus")])[%d]' % idx)
        acts = []
        for _ in range(n):
            acts.append({"type": "click", "xpath": xp_plus})
            acts.append({"type": "sleep", "value": SLEEP_TOQUE})
        acts += [
            {"type": "click", "xpath": '//button[@id="savePoints"]'},
            {"type": "sleep", "value": 3},
        ]
        self.enviar(acts)
        return True, "%d ponto(s) -> %s" % (n, estrategia)

    # ---- construir / evoluir ------------------------------------------
    def construir(self, slot, gid, categoria=1):
        """Constrói/sobe o edifício 'gid' no 'slot'. Detecta se a obra entrou
        na fila (respeita a regra de 1 obra por dorf — se a fila estiver cheia,
        o jogo recusa e isto retorna False)."""
        self.ir(self.base + "/build.php?id=%d&category=%d" % (slot, categoria), 4)
        r = self.enviar([
            {"type": "click",
             "xpath": '//button[contains(@onclick,"gid=%d") and '
                      'contains(@onclick,"action=build")]' % gid},
            {"type": "sleep", "value": 3},
            {"type": "html"},
        ])
        html = next((x["html"] for x in r if x["type"] == "html"), "")
        return "buildingList" in html

    def _subir_verde(self, slot, gid):
        """Abre a página do campo/edifício e, SE o botão verde 'Melhorar'
        estiver ativo (o jogo só o mostra quando dá para subir agora — fila com
        vaga E recursos suficientes), clica nele. True se subiu.

        Isto substitui o palpite de fila: vale para dorf1/dorf2 e para conta
        com ou sem Plus, porque reflete o estado real do jogo."""
        _, html = self.ir(self.base + "/build.php?id=%d&gid=%d" % (slot, gid), 4)
        botao = re.search(r'<button[^>]*class="([^"]*\bgreen\b[^"]*\bbuild\b[^"]*)"',
                          html)
        if not botao or "disabled" in botao.group(1):
            return False
        self.enviar([
            {"type": "click",
             "xpath": "//button[contains(@class,'green') and contains(@class,'build')]"},
            {"type": "sleep", "value": 3},
        ])
        return True

    def upgrade_campo(self, slot, gid):
        """Sobe um campo de recurso (dorf1)."""
        return self._subir_verde(slot, gid), None

    def campos_recurso(self, html=None):
        """Lista dos campos de dorf1: [{'slot','gid','nivel'}, ...]."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 4)
        campos = []
        for m in re.finditer(r"resourceField gid(\d) buildingSlot(\d+)\s+level(\d+)",
                             html):
            campos.append({"slot": int(m.group(2)), "gid": int(m.group(1)),
                           "nivel": int(m.group(3))})
        return campos

    def evoluir_dorf1(self):
        """Sobe o campo de MENOR nível (desempate aleatório). 'randômico'."""
        campos = self.campos_recurso()
        if not campos:
            return False, "não consegui ler os campos"
        menor = min(c["nivel"] for c in campos)
        alvo = random.choice([c for c in campos if c["nivel"] == menor])
        ok, _ = self.upgrade_campo(alvo["slot"], alvo["gid"])
        return ok, "campo slot %d (gid %d) nível %d->%d %s" % (
            alvo["slot"], alvo["gid"], menor, menor + 1,
            "construindo" if ok else "fila cheia / sem recursos")

    def edificios_dorf2(self, html=None):
        """Edifícios construídos no dorf2: [{'slot','gid','nivel','nome'}]."""
        if html is None:
            _, html = self.ir(self.base + "/dorf2.php", 4)
        edis = []
        for m in re.finditer(
                r'data-aid="(\d+)"[^>]*data-gid="(\d+)"[^>]*data-name="([^"]*)"'
                r'[^>]*>\s*<a[^>]*data-level="(\d+)"', html, re.S):
            gid = int(m.group(2))
            if gid != 0 and m.group(3):
                edis.append({"slot": int(m.group(1)), "gid": gid,
                             "nome": m.group(3), "nivel": int(m.group(4))})
        return edis

    def evoluir_dorf2(self):
        """Sobe o EDIFÍCIO de menor nível do dorf2 (desempate aleatório)."""
        edis = self.edificios_dorf2()
        if not edis:
            return False, "não consegui ler os edifícios"
        menor = min(e["nivel"] for e in edis)
        alvo = random.choice([e for e in edis if e["nivel"] == menor])
        ok = self._subir_verde(alvo["slot"], alvo["gid"])
        return ok, "%s slot %d nível %d->%d %s" % (
            alvo["nome"], alvo["slot"], menor, menor + 1,
            "construindo" if ok else "fila cheia / sem recursos")

    def criar_novo_dorf2(self, gids_desejados):
        """Constrói o 1º edifício DESEJADO (por gid, em ordem de prioridade) que
        ainda NÃO existe no dorf2, no primeiro slot vazio. É aqui que o
        esconderijo (gid 23) entra como edifício novo."""
        _, html = self.ir(self.base + "/dorf2.php", 4)
        existentes = {e["gid"] for e in self.edificios_dorf2(html)}
        slot = self._primeiro_slot_vazio(html)
        if slot is None:
            return False, "sem slot vazio"
        for gid in gids_desejados:
            if gid in existentes:
                continue
            ok = self.construir(slot, gid)
            return ok, "novo gid %d no slot %d (%s)" % (
                gid, slot, "construindo" if ok else "recusado")
        return False, "todos os desejados já existem"

    def construir_ou_evoluir_dorf2(self, cfg):
        """Decisão do dorf2: EVOLUIR um edifício existente OU CRIAR um novo.
        Com chance DORF2_PCT_NOVO (%) tenta criar um novo da lista DORF2_NOVOS
        (gids, prioridade); senão evolui o de menor nível. Se 'criar' não rolar
        (slot/recusa), cai para evoluir. (A rampa % do esconderijo pluga aqui.)"""
        cfg = cfg or {}
        pct = float(cfg.get("DORF2_PCT_NOVO", "0"))   # 0 = só evoluir (base inerte)
        gids = [int(x) for x in re.split(r"[,\s]+",
                cfg.get("DORF2_NOVOS", "18,23,17").strip()) if x]
        if random.random() * 100 < pct:
            ok, msg = self.criar_novo_dorf2(gids)
            if ok:
                return ok, "criar -> " + msg
            evok, evmsg = self.evoluir_dorf2()
            return evok, "criar n/d (%s) -> evoluir: %s" % (msg, evmsg)
        evok, evmsg = self.evoluir_dorf2()
        return evok, "evoluir -> " + evmsg

    def subir_ou_criar_esconderijo(self, nivel_alvo=10):
        """Esconderijo (gid 23): sobe o existente (o de menor nível) ou cria um
        em slot vazio. Para no nível-alvo (capacidade ~2000; Romano ~200/nível
        -> nível 10). Devolve (ok, msg)."""
        _, html = self.ir(self.base + "/dorf2.php", 4)
        esc = [e for e in self.edificios_dorf2(html) if e["gid"] == 23]
        if esc:
            if max(e["nivel"] for e in esc) >= nivel_alvo:
                return False, "no alvo (nível>=%d)" % nivel_alvo
            alvo = min(esc, key=lambda e: e["nivel"])
            ok = self._subir_verde(alvo["slot"], 23)
            return ok, "subir slot %d nível %d->%d (%s)" % (
                alvo["slot"], alvo["nivel"], alvo["nivel"] + 1,
                "construindo" if ok else "recusado")
        slot = self._primeiro_slot_vazio(html)
        if slot is None:
            return False, "sem slot vazio"
        ok = self.construir(slot, 23)
        return ok, "criar slot %d (%s)" % (slot, "construindo" if ok else "recusado")

    def evoluir(self, onde=None):
        """Evolui: 'dorf1' (campo), 'dorf2' (edifício) ou aleatório (None)."""
        onde = onde or random.choice(["dorf1", "dorf2"])
        return (self.evoluir_dorf1() if onde == "dorf1"
                else self.evoluir_dorf2())

    # ---- mapa / oásis (via API interna, com a action 'eval') ----------
    def eval_js(self, js):
        """Roda JS na página e devolve o retorno (action 'eval')."""
        r = self.enviar([{"type": "eval", "value": js}])
        return next((x["result"] for x in r if x["type"] == "eval"), None)

    def _xhr_post(self, url, corpo):
        """Monta um XHR síncrono (mesma origem/cookies) que devolve o texto."""
        return ('(function(){try{var r=new XMLHttpRequest();r.open("POST",%s,'
                'false);r.setRequestHeader("Content-Type","application/json; '
                'charset=UTF-8");r.send(%s);return r.responseText;}catch(e){'
                'return "";}})()' % (json.dumps(url), json.dumps(corpo)))

    def coords_aldeia(self, html=None):
        """(x, y) da aldeia atual (lido do dorf1)."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 3)
        m = re.search(r'data-x="(-?\d+)"\s+data-y="(-?\d+)"', html)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def nome_aldeia(self, html=None):
        """Nome da aldeia atual (input villageName)."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 3)
        m = re.search(r'value="([^"]+)"\s+name="villageName"', html)
        return m.group(1).strip() if m else "?"

    def fim_construcao(self, dorf, html=None):
        """ISO de quando a obra do DORF pedido termina (campos=1, edifícios=2),
        ou None se aquele dorf não tem obra na fila.

        A buildingList é GLOBAL (lista campos E edifícios juntos, igual nas duas
        páginas) e cada item só traz o NOME — sem slot/gid. Então classifico
        pelo nome: se bate com um edifício do dorf2 (edificios_dorf2) é obra de
        edifício; senão é campo. Assim o 'fim' do dorf1 não herda mais o horário
        de uma obra do dorf2 (bug do agendamento por horário)."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 3)
        m = re.search(r'class="buildingList".*?</div>\s*</div>\s*</div>',
                      html, re.S)
        if not m:
            return None
        itens = re.findall(
            r'class="name">\s*(.*?)\s*<span class="lvl".*?value="(\d+)"',
            m.group(0), re.S)
        if not itens:
            return None
        nomes_d2 = {e["nome"].strip() for e in self.edificios_dorf2()}
        segs = []
        for nome, val in itens:
            nome = re.sub(r"<[^>]+>", "", nome).strip()
            eh_edificio = nome in nomes_d2
            if (dorf == 2) == eh_edificio:   # dorf2&edifício ou dorf1&campo
                segs.append(int(val))
        if not segs:
            return None
        fim = datetime.now(timezone.utc).astimezone() + timedelta(seconds=max(segs))
        return fim.isoformat(timespec="seconds")

    def mapa_posicao(self, x, y, zoom=3):
        """Tiles do campo de visão ao redor de (x,y) via /api/v1/map/position."""
        corpo = json.dumps({"data": {"x": x, "y": y, "zoomLevel": zoom,
                                     "ignorePositions": []}})
        raw = self.eval_js(self._xhr_post("/api/v1/map/position", corpo))
        try:
            return json.loads(raw).get("tiles", []) if raw else []
        except Exception:
            return []

    def oasis_detalhe(self, x, y):
        """Detalhe de um oásis via /api/v1/map/tile-details: ocupado, bônus,
        tropas de natureza (sem_tropas=1 quando 'Tropas nenhum(a)')."""
        raw = self.eval_js(self._xhr_post("/api/v1/map/tile-details",
                                          json.dumps({"x": x, "y": y})))
        if not raw:
            return None
        try:
            html = json.loads(raw).get("html", "")
        except Exception:
            html = raw
        low = re.sub(r"<[^>]+>", " ", html).lower()
        ocupado = 0 if "desocupado" in low else (1 if "ocupad" in low else 0)
        sem_tropas = 1 if re.search(r"tropas\s+nenhum", low) else 0
        tropas = {}
        for u, q in re.findall(r"unit u(\d+)\"[^>]*>.*?(\d+)", html, re.S):
            tropas[u] = int(q)
        bonus = " ".join("%s%% %s" % (a, b) for a, b in re.findall(
            r"(\d+)\s*%?\s*(Madeira|Barro|Ferro|Cereal)", html))
        return {"ocupado": ocupado, "bonus": bonus,
                "tropas": json.dumps(tropas), "sem_tropas": sem_tropas}

    def ir_para_coordenada(self, x, y):
        """Vai até (x,y) pelo mapa (UI): karte.php, preenche X/Y e clica OK
        (o mapa centraliza na coordenada). Navegação VISÍVEL."""
        self.ir(self.base + "/karte.php", 4)
        self.enviar([
            {"type": "key", "xpath": '//input[@id="xCoordInputMap"]',
             "value": str(x)},
            {"type": "sleep", "value": SLEEP_TOQUE},
            {"type": "key", "xpath": '//input[@id="yCoordInputMap"]',
             "value": str(y)},
            {"type": "sleep", "value": SLEEP_TOQUE},
            {"type": "click", "xpath": '//*[@id="mapCoordEnter"]'},  # OK
            {"type": "sleep", "value": 2},
        ])

    def escanear_mapa(self, db, max_oasis=5):
        """Atualiza o mapa: salva todos os tiles (1 chamada à API de posição,
        feita já no karte.php) e consulta o detalhe de NO MÁXIMO 'max_oasis'
        oásis — os de 'data_ultima_consulta' mais antiga (rodízio), navegando
        a cada um pelo mapa (visível). Devolve (n_tiles, n_consultados)."""
        x0, y0 = self.coords_aldeia()
        self.ir(self.base + "/karte.php", 4)            # mapa (visível)
        tiles = self.mapa_posicao(x0, y0)
        agora = _agora()
        for t in tiles:
            x, y = t["position"]["x"], t["position"]["y"]
            title, text = t.get("title", ""), t.get("text", "")
            tipo = ("aldeia" if "{k.dt}" in title
                    else "oasis" if "{k.fo}" in title else "terreno")
            dist = round(((x - x0) ** 2 + (y - y0) ** 2) ** 0.5, 2)
            db.execute("INSERT OR REPLACE INTO mapa_tiles VALUES (?,?,?,?,?,?,?)",
                       (x, y, tipo, title, text, dist, agora))
            if tipo == "oasis":  # garante a linha sem apagar a última consulta
                db.execute("INSERT OR IGNORE INTO oasis(x,y,distancia) "
                           "VALUES (?,?,?)", (x, y, dist))
        db.commit()
        # os menos recentemente consultados primeiro (NULL = nunca = primeiros)
        alvos = db.execute("SELECT x,y FROM oasis ORDER BY data_ultima_consulta "
                           "ASC, distancia ASC LIMIT ?", (max_oasis,)).fetchall()
        for x, y in alvos:
            self.ir_para_coordenada(x, y)               # navega no mapa (visível)
            det = self.oasis_detalhe(x, y)
            if det:
                db.execute("UPDATE oasis SET ocupado=?, bonus=?, tropas=?, "
                           "sem_tropas=?, ts=?, data_ultima_consulta=? "
                           "WHERE x=? AND y=?",
                           (det["ocupado"], det["bonus"], det["tropas"],
                            det["sem_tropas"], agora, agora, x, y))
                db.commit()
        return len(tiles), len(alvos)

    # ---- movimentos de tropas (ataques saindo) ------------------------
    def ler_movimentos(self, meu_xy=None):
        """Lê os movimentos no ponto de encontro (tt=1): tipo, alvo, chegada
        (ISO = agora + timer). Devolve lista de dicts."""
        if meu_xy is None:
            meu_xy = self.coords_aldeia()
        mx, my = meu_xy
        _, html = self.ir(self.base + "/build.php?id=39&gid=16&tt=1", 4)
        movs = []
        # cada movimento é uma <table class="troop_details outRaid|outAttack|
        # inAttack|...">; a classe dá direção (out/in) e tipo (raid/attack/...)
        for m in re.finditer(r'<table[^>]*class="([^"]*troop_details[^"]*)"'
                             r'[^>]*>(.*?)</table>', html, re.S):
            cls, blk = m.group(1).lower(), m.group(2)
            txt = re.sub(r"<[^>]+>", " ", blk).replace("‭", "").replace("‬", "")
            txt = re.sub(r"\s+", " ", txt).strip()
            coords = re.findall(r"\((-?\d+)\s*\|\s*(-?\d+)\)", txt)
            alvo = next(("%s|%s" % (x, y) for x, y in coords
                         if (int(x), int(y)) != (mx, my)), None)
            tmr = re.search(r'class="timer"[^>]*value="(\d+)"', blk)
            seg_s = int(tmr.group(1)) if tmr else None
            if seg_s is None:
                continue  # sem timer = não é movimento (ex.: 'Próprias tropas')
            chegada = ((datetime.now(timezone.utc).astimezone()
                        + timedelta(seconds=seg_s)).isoformat(timespec="seconds")
                       if seg_s else None)
            direcao = "saindo" if "out" in cls else "entrando" if "in" in cls else "?"
            tipo = ("assalto" if "raid" in cls else "ataque" if "attack" in cls
                    else "reforço" if "support" in cls or "reinf" in cls
                    else "retorno" if "return" in cls else cls)
            movs.append({"tipo": "%s %s" % (direcao, tipo), "alvo": alvo,
                         "chegada": chegada, "segundos": seg_s,
                         "detalhe": txt[:150]})
        return movs

    # ---- assalto a oásis (raid) ---------------------------------------
    # Página de envio: build.php?id=39&gid=16&tt=2. Inputs troop[t1..t11]
    # (t11=herói, ativo só com herói em casa); eventType value=4 = Assalto;
    # #ok = Enviar -> #confirmSendTroops = Confirmar. Regras no doc oasis-mapa.
    def tropas_disponiveis_ataque(self, html=None):
        """Tropas que dá para enviar AGORA (inputs troop[tN] ATIVOS, não
        disabled) e quanto há de cada (lê o número logo após o input).
        Devolve (dict {tN: max|None}, html). t11 = herói."""
        if html is None:
            _, html = self.ir(self.base + "/build.php?id=39&gid=16&tt=2", 5)
        disp = {}
        for mm in re.finditer(r'<input[^>]*name="troop\[(t\d+)\]"[^>]*>', html):
            if "disabled" in mm.group(0):
                continue
            cauda = re.sub(r"<[^>]+>", " ", html[mm.end():mm.end() + 280])
            m2 = re.search(r"(\d[\d.‭‬]*)", cauda)
            disp[mm.group(1)] = _num(m2.group(1)) if m2 else None
        return disp, html

    def _enviar_assalto(self, x, y, tropas, mandar_heroi):
        """Preenche destino + tropas (força máxima), marca Assalto (eventType=4),
        Enviar e Confirmar. 'tropas' = {tN: qtd}. True se mandou algo."""
        acts = [
            {"type": "navigate",
             "value": self.base + "/build.php?id=39&gid=16&tt=2"},
            {"type": "sleep", "value": 4},
            {"type": "key", "xpath": '//input[@id="xCoordInput"]', "value": str(x)},
            {"type": "sleep", "value": SLEEP_TOQUE},
            {"type": "key", "xpath": '//input[@id="yCoordInput"]', "value": str(y)},
            {"type": "sleep", "value": SLEEP_TOQUE},
        ]
        enviou = False
        for tn, q in tropas.items():
            if tn == "t11" or not q or q <= 0:
                continue
            acts.append({"type": "key",
                         "xpath": '//input[@name="troop[%s]"]' % tn,
                         "value": str(q)})
            acts.append({"type": "sleep", "value": SLEEP_TOQUE})
            enviou = True
        if mandar_heroi and "t11" in tropas:
            acts.append({"type": "key",
                         "xpath": '//input[@name="troop[t11]"]', "value": "1"})
            acts.append({"type": "sleep", "value": SLEEP_TOQUE})
            enviou = True
        if not enviou:
            return False
        acts += [
            {"type": "click",
             "xpath": '//input[@name="eventType" and @value="4"]'},  # Assalto
            {"type": "sleep", "value": 2},
            {"type": "click", "xpath": '//*[@id="ok"]'},             # Enviar
            {"type": "sleep", "value": 3},
            {"type": "click", "xpath": '//*[@id="confirmSendTroops"]'},  # Confirmar
            {"type": "sleep", "value": 3},
        ]
        self.enviar(acts)
        return True

    def atacar_oasis(self, db, cfg):
        """Assalto a um oásis (AGENDADO; aventura roda ANTES no ciclo).
        Conservador: só DESOCUPADO e SEM DEFESA (sem_tropas=1), re-conferindo a
        defesa na hora (animais nascem). Manda força máxima das tropas em casa;
        herói entra se OASIS_HEROI_OBRIGATORIO=false e estiver em casa."""
        cfg = cfg or {}
        heroi_obrig = str(cfg.get("OASIS_HEROI_OBRIGATORIO", "true")).strip(
            ).lower() in ("1", "true", "sim", "yes")
        disp, _ = self.tropas_disponiveis_ataque()
        tem_heroi = "t11" in disp
        exercito = {tn: q for tn, q in disp.items() if tn != "t11"}
        mandar_heroi = tem_heroi and not heroi_obrig
        if not exercito and not mandar_heroi:
            return False, ("sem tropa p/ assalto"
                           + ("" if tem_heroi else " (herói fora)"))
        alvos = db.execute(
            "SELECT x,y,distancia FROM oasis WHERE ocupado=0 AND sem_tropas=1 "
            "ORDER BY distancia ASC LIMIT 5").fetchall()
        if not alvos:
            return False, "sem oásis livre/sem-defesa no DB (rode 'scan')"
        for x, y, dist in alvos:
            det = self.oasis_detalhe(x, y)          # re-confere defesa AGORA (XHR)
            if det:
                db.execute("UPDATE oasis SET ocupado=?, sem_tropas=? "
                           "WHERE x=? AND y=?",
                           (det["ocupado"], det["sem_tropas"], x, y))
                db.commit()
            if det and det["ocupado"] == 0 and det["sem_tropas"] == 1:
                tropas = dict(exercito)
                if mandar_heroi:
                    tropas["t11"] = 1
                ok = self._enviar_assalto(x, y, tropas, mandar_heroi)
                return ok, ("assalto -> (%d|%d) dist %.1f" % (x, y, dist)
                            if ok else "falha ao enviar p/ (%d|%d)" % (x, y))
        return False, "oásis candidatos ganharam defesa; nada enviado"

    # ---- tarefas diárias (daily quests) -------------------------------
    def tem_tarefas_diarias(self, html=None):
        """True se o botão dailyQuests está com indicador (o '!')."""
        if html is None:
            _, html = self.ir(self.base + "/dorf1.php", 3)
        m = re.search(r'class="dailyQuests"[^>]*>\s*'
                      r'<div class="indicator">([^<]*)</div>', html)
        return bool(m and m.group(1).strip())

    def ler_tarefas_diarias(self):
        """Abre o diálogo de tarefas diárias e lê: tarefas+progresso e se há
        recompensa para coletar. Devolve um dict."""
        self.ir(self.base + "/dorf1.php", 3)
        r = self.enviar([
            {"type": "click", "xpath": '//a[contains(@class,"dailyQuests")]'},
            {"type": "sleep", "value": 3},
            {"type": "html",
             "xpath": '//*[contains(@class,"dailyQuestsDialog")]'},
        ])
        html = next((x["html"] for x in r if x["type"] == "html"), "")
        reward = ("collectRewards" in html) or ("rewardAvailable" in html)
        t = re.sub(r"<(style|script|svg)[^>]*>.*?</\1>", " ", html, flags=re.S)
        t = re.sub(r"<[^>]+>", " ", t).replace("‭", "").replace("‬", "")
        t = re.sub(r"\s+", " ", t).strip()
        tarefas = re.findall(
            r"(\d+)/(\d+)\s+([A-Za-zÀ-ú][^0-9]{4,45}?)"
            r"(?=\s+\d+/\d+|\s+Coletar|$)", t)
        return {"recompensa_disponivel": reward,
                "tarefas": [(n, m, d.strip()) for n, m, d in tarefas],
                "texto": t[:800]}

    # ---- relatórios (batalha / aventura) ------------------------------
    def listar_relatorios(self, html=None):
        """IDs dos relatórios na caixa (com o 's' para abrir cada um)."""
        if html is None:
            _, html = self.ir(self.base + "/report", 5)
        reps = []
        for m in re.finditer(r'name="ids\[\]"\s+value="(\d+)"', html):
            rid = int(m.group(1))
            h = re.search(r"\?id=%d&(?:amp;)?s=(\d+)" % rid, html)
            reps.append({"rid": rid, "s": int(h.group(1)) if h else 1})
        return reps

    def ler_relatorio(self, rid, s=1):
        """Abre e parseia um relatório."""
        _, html = self.ir(self.base + "/report?id=%d&s=%d" % (rid, s), 5)
        txt = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S)
        txt = re.sub(r"<[^>]+>", " ", txt).replace("‭", "").replace("‬", "")
        txt = re.sub(r"\s+", " ", txt).strip()
        rep = {"rid": rid, "ts": _agora(), "bruto": txt[:4000]}
        m = re.search(r"(\d{2}\.\d{2}\.\d{2},?\s*\d{2}:\d{2}:\d{2})", txt)
        rep["data_jogo"] = m.group(1) if m else None
        rep["assunto"] = txt[:80]
        if "Aventura" in txt or "explora" in txt.lower():
            rep["tipo"] = "aventura"
            mi = re.search(r"Informa\w+\s+(-?\d+)\s*[−-]?\s*(\d+)\s*%", txt)
            if mi:
                rep["xp"] = int(mi.group(1))
                rep["vida_delta"] = -int(mi.group(2))
            mp = re.search(r"Pr[êe]mio\s+([A-Za-zÀ-ú ]{3,40}?)\s+(?:naoimporta|"
                           r"População|$)", txt)
            rep["premio"] = mp.group(1).strip() if mp else None
        elif re.search(r"\batac|ofensiv", txt, re.I):
            rep["tipo"] = "ofensivo"   # parser detalhado com amostra real
        elif re.search(r"defend|defensiv", txt, re.I):
            rep["tipo"] = "defensivo"
        elif re.search(r"explor|espion|scout", txt, re.I):
            rep["tipo"] = "exploracao"
        return rep

    # ---- armazenamento -------------------------------------------------
    def garantir_armazenamento(self):
        """Constrói Celeiro e Armazém em slots vazios se ainda não existem."""
        feitos = []
        for nome, gid in [("Celeiro", GID_CELEIRO), ("Armazém", GID_ARMAZEM)]:
            _, html = self.ir(self.base + "/dorf2.php", 4)
            if "g%d " % gid in html or 'class="building %d' % gid in html:
                continue  # já existe
            # acha primeiro slot vazio (gid 0) entre 19 e 40
            slot = self._primeiro_slot_vazio(html)
            if slot is None:
                feitos.append((nome, "sem slot vazio"))
                continue
            ok = self.construir(slot, gid)
            feitos.append((nome, "construindo" if ok else "fila ocupada/recusado"))
        return feitos

    def _primeiro_slot_vazio(self, html_dorf2):
        """1º slot livre (data-gid='0') do dorf2 para edifício NORMAL (19..38;
        exclui 39=ponto de reunião e 40=muralha). Os slots têm
        data-aid="<slot>" data-gid="<gid|0>"."""
        livres = []
        for m in re.finditer(r'data-aid="(\d+)"[^>]*?data-gid="(\d+)"',
                             html_dorf2):
            aid, gid = int(m.group(1)), int(m.group(2))
            if gid == 0 and 19 <= aid <= 38:
                livres.append(aid)
        return min(livres) if livres else None

    # ---- missões -------------------------------------------------------
    def _conta_collect(self, html):
        return len(re.findall(r'<button[^>]*class="[^"]*\bcollect\b[^"]*"', html))

    def recolher_missoes(self, maximo=30):
        """Recolhe TODAS as recompensas disponíveis, sem validar nada.

        No Travian atual não há limite de armazenamento para recompensa de
        missão (vão para o herói). Re-navega a /tasks a cada coleta (a UI
        remove o botão de forma assíncrona, então só uma releitura limpa dá a
        contagem certa); para quando não sobra botão ou se a contagem não cai.
        """
        recolhidas = 0
        anterior = None
        for _ in range(maximo):
            _, html = self.ir(self.base + "/tasks?t=village", 3)
            n = self._conta_collect(html)
            if n == 0:
                break
            if anterior is not None and n >= anterior:
                break  # não diminuiu desde a última coleta -> evita laço
            anterior = n
            self.enviar([
                {"type": "click",
                 "xpath": '(//button[contains(@class,"collect")])[1]'},
                {"type": "sleep", "value": 3},
            ])
            recolhidas += 1
        return recolhidas

    def missoes_prontas(self, html=None):
        """Quantas missões estão prontas para recolher (botões 'collect')."""
        if html is None:
            _, html = self.ir(self.base + "/tasks?t=village", 4)
        return len(re.findall(r'<button[^>]*class="[^"]*\bcollect\b[^"]*"', html))

    # ---- inventário do herói -> armazém/celeiro -----------------------
    # As recompensas ficam no herói (item145=madeira, 146=barro, 147=ferro,
    # 148=cereal). Transferimos para o armazém/celeiro mantendo cada recurso
    # em no máximo LIMITE (80%) da capacidade, deixando folga para a produção.
    ITEM_RECURSO = {"145": "madeira", "146": "barro", "147": "ferro", "148": "cereal"}
    INPUT_RECURSO = {"madeira": "lumber", "barro": "clay", "ferro": "iron",
                     "cereal": "crop"}

    def inventario_heroi(self, html):
        """Quantidade de cada recurso nos slots do herói."""
        inv = {nm: 0 for nm in RECURSOS}
        for m in re.finditer(r'data-placeid="\d+"(.*?)(?=<div class="heroItem|$)',
                             html, re.S):
            blk = m.group(1)
            it = re.search(r'\bitem(\d+)\b', blk)
            cnt = re.search(r'class="count"[^>]*>\s*([0-9.,‭‬]+)', blk)
            if it and it.group(1) in self.ITEM_RECURSO and cnt:
                inv[self.ITEM_RECURSO[it.group(1)]] = _num(cnt.group(1))
        return inv

    def plano_transferencia(self, est, inv, limite=0.80):
        """Quanto transferir de cada recurso para não passar de LIMITE×capac."""
        plano = {}
        for nm in RECURSOS:
            alvo = int(est["capacidade"][nm] * limite)
            espaco = max(0, alvo - est["estoque"][nm])
            plano[nm] = min(inv.get(nm, 0), espaco)
        return plano

    def transferir_recursos(self, limite=0.80):
        """Lê herói + topo, calcula (≤80% cap) e transfere. Devolve o plano."""
        _, html = self.ir(self.base + "/hero/inventory", 5)
        est = self.parse_estado(html)
        inv = self.inventario_heroi(html)
        plano = self.plano_transferencia(est, inv, limite)
        if sum(plano.values()) <= 0:
            return plano, est, inv, False
        # abre o diálogo (clicar um slot de recurso), seta os 4 inputs, confirma
        # — 1s entre cada toque na mesma tela
        actions = [
            {"type": "click",
             "xpath": '//div[contains(@class,"heroItem consumable") and '
                      '@data-placeid="1"]'},
            {"type": "sleep", "value": 2},
        ]
        for nm in RECURSOS:
            actions.append({"type": "key",
                            "xpath": '//input[@name="%s"]' % self.INPUT_RECURSO[nm],
                            "value": str(plano[nm])})
            actions.append({"type": "sleep", "value": SLEEP_TOQUE})
        actions += [
            # confirmar é SEMPRE o SEGUNDO botão "Transferência" (o 1º é
            # "Transferência máxima", que ignora os valores e enche até 100%)
            {"type": "click",
             "xpath": '(//button[contains(.,"Transferência")])[2]'},
            {"type": "sleep", "value": 3},
        ]
        self.enviar(actions)
        return plano, est, inv, True


# ---- CLI ---------------------------------------------------------------
# ---- contas (multi-server / multi-user) + histórico SQLite -------------
# Estrutura: account/<servidor>/<usuario>/  -> .env (credenciais) e
# travian.sqlite (histórico). A conta é escolhida por TRAVIAN_ACCOUNT
# ("<servidor>/<usuario>") ou, se houver só uma, automaticamente.
DIR_ESTE = os.path.dirname(os.path.abspath(__file__))
DIR_CONTAS = os.path.join(DIR_ESTE, "account")


def carregar_env(caminho):
    cfg = {}
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    k, v = linha.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def listar_contas():
    contas = []
    for srv in sorted(glob(os.path.join(DIR_CONTAS, "*"))):
        for usr in sorted(glob(os.path.join(srv, "*"))):
            if os.path.isdir(usr):
                contas.append(os.path.relpath(usr, DIR_CONTAS))
    return contas


def resolver_conta():
    """(conta_dir, base, email, senha) da conta escolhida."""
    alvo = os.environ.get("TRAVIAN_ACCOUNT")
    if not alvo:
        contas = listar_contas()
        if len(contas) == 1:
            alvo = contas[0]
        elif not contas:
            raise SystemExit("nenhuma conta em %s" % DIR_CONTAS)
        else:
            raise SystemExit("defina TRAVIAN_ACCOUNT=<servidor>/<usuario>; "
                             "contas: %s" % ", ".join(contas))
    conta_dir = os.path.join(DIR_CONTAS, alvo)
    env = carregar_env(os.path.join(conta_dir, ".env"))
    base = env.get("TRAVIAN_BASE") or ("https://" + alvo.split(os.sep)[0])
    return (conta_dir, base, env.get("TRAVIAN_EMAIL", EMAIL),
            env.get("TRAVIAN_PASSWORD", SENHA), env)


def abrir_db(conta_dir):
    db = sqlite3.connect(os.path.join(conta_dir, "travian.sqlite"))
    db.execute("""CREATE TABLE IF NOT EXISTS acoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        comando TEXT, ok INTEGER, detalhe TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS estado (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        madeira INT, barro INT, ferro INT, cereal INT,
        cap_madeira INT, cap_barro INT, cap_ferro INT, cap_cereal INT,
        missoes_prontas INT)""")
    # relatórios (batalha/aventura) — base para o modelo de ataque/defesa
    db.execute("""CREATE TABLE IF NOT EXISTS relatorios (
        rid INTEGER PRIMARY KEY, ts TEXT NOT NULL, data_jogo TEXT,
        tipo TEXT, assunto TEXT,
        inimigo TEXT, inimigo_coord TEXT, distancia REAL,
        minha_forca INTEGER, forca_inimigo INTEGER, defesa_inimigo INTEGER,
        minhas_tropas TEXT, tropas_inimigo TEXT,
        minhas_perdas TEXT, perdas_inimigo TEXT, saque TEXT,
        xp INTEGER, vida_delta INTEGER, premio TEXT, bruto TEXT)""")
    # mapa: todos os tiles do campo de visão (aldeia != oásis != terreno)
    db.execute("""CREATE TABLE IF NOT EXISTS mapa_tiles (
        x INT, y INT, tipo TEXT, title TEXT, text TEXT, distancia REAL,
        ts TEXT, PRIMARY KEY (x, y))""")
    # oásis com detalhe (bônus, ocupado, tropas de natureza) p/ decidir raid.
    # data_ultima_consulta: rodízio — consultamos os menos recentes primeiro.
    db.execute("""CREATE TABLE IF NOT EXISTS oasis (
        x INT, y INT, distancia REAL, ocupado INT, bonus TEXT,
        tropas TEXT, sem_tropas INT, ts TEXT, data_ultima_consulta TEXT,
        PRIMARY KEY (x, y))""")
    try:  # bancos antigos: adiciona a coluna se faltar
        db.execute("ALTER TABLE oasis ADD COLUMN data_ultima_consulta TEXT")
    except sqlite3.OperationalError:
        pass
    # meta (chave/valor) — ex.: data do último scan diário do mapa
    db.execute("""CREATE TABLE IF NOT EXISTS meta (
        chave TEXT PRIMARY KEY, valor TEXT)""")
    # construções iniciadas: gate para só reconstruir quando a última terminar
    db.execute("""CREATE TABLE IF NOT EXISTS construcoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        aldeia TEXT, dorf INTEGER, fim TEXT, item TEXT)""")
    # movimentos de tropas (ataques/assaltos saindo): alvo + chegada
    db.execute("""CREATE TABLE IF NOT EXISTS movimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        tipo TEXT, alvo TEXT, chegada TEXT, segundos INTEGER, detalhe TEXT)""")
    db.commit()
    return db


def pode_construir(db, aldeia, dorf):
    """True se NÃO há construção pendente naquela aldeia+dorf (o fim da última
    já passou ou nunca houve)."""
    row = db.execute("SELECT MAX(fim) FROM construcoes WHERE aldeia=? AND dorf=?",
                     (aldeia, dorf)).fetchone()
    if not row or not row[0]:
        return True, None
    fim = datetime.fromisoformat(row[0])
    agora = datetime.now(fim.tzinfo)
    return (agora >= fim), row[0]


def _transfer_seria_inutil(db, janela=1800):
    """True se a última transferência herói->depósito foi INÚTIL (herói vazio)
    há menos de 'janela' s. Serve para NÃO reagendar transferir_recursos à toa
    (evita o ping-pong de reload a cada 60s quando não há o que transferir)."""
    v = meta_get(db, "transfer_vazio")
    if not v:
        return False
    try:
        dt = datetime.fromisoformat(v)
        return (datetime.now(dt.tzinfo) - dt).total_seconds() < janela
    except Exception:
        return False


def evoluir_controlado(t, db, onde=None, html_dorf1=None, cfg=None):
    """Constrói/evolui um dorf (script AGENDADO). Regra do usuário: NEM navega
    para a tela de construção se o SQLite (tabela construcoes) mostra que, por
    horário, a obra anterior daquele dorf ainda não terminou — evita reload à
    toa. Quando a fila está livre, tenta subir; se a obra NÃO entra (fila livre
    porém sem recurso), agenda transferir_recursos no PROXIMO_SCRIPT_IMEDIATO.
    No dorf2 a escolha é evoluir existente OU criar novo (esconderijo etc.)."""
    onde = onde or random.choice(["dorf1", "dorf2"])
    dorf = 1 if onde == "dorf1" else 2
    aldeia = t.nome_aldeia(html_dorf1)          # usa o html do ciclo (sem reload)
    livre, fim = pode_construir(db, aldeia, dorf)
    if not livre:
        return False, "%s: ainda construindo até %s (não navega)" % (onde, fim)
    ok, msg = (t.evoluir_dorf1() if dorf == 1
               else decidir_dorf2(t, db, cfg, html_dorf1))
    if ok:
        fimc = t.fim_construcao(dorf)
        db.execute("INSERT INTO construcoes(ts,aldeia,dorf,fim,item) "
                   "VALUES (?,?,?,?,?)", (_agora(), aldeia, dorf, fimc, msg))
        db.commit()
        msg += " | fim=%s" % fimc
    elif _transfer_seria_inutil(db):
        # fila livre mas sem recurso, e o herói está vazio (transfer recente foi
        # inútil) -> NÃO reagenda transferir (deixa o loop dormir normal).
        msg += " | sem recurso (herói vazio há pouco; não reagenda)"
    else:
        # fila livre (gate ok) mas a obra não entrou -> falta de recurso:
        agendar_imediato(db, "transferir_recursos")
        msg += " | sem recurso -> transferir_recursos IMEDIATO"
    return ok, msg


def detectar_tribo(t):
    """Lê o povo da conta na página de perfil (ex.: 'Tribo Romanos')."""
    _, ph = t.ir(t.base + "/profile", 5)
    txt = re.sub(r"<[^>]+>", " ", ph)
    m = re.search(r"Tribo\s+([A-Za-zÀ-ú]+)", txt)
    return m.group(1) if m else None


def tribo_conta(t, db):
    """Povo da conta, com cache no 'meta' (só consulta a 1ª vez)."""
    v = meta_get(db, "tribo")
    if not v:
        v = detectar_tribo(t)
        if v:
            meta_set(db, "tribo", v)
    return v


def prob_esconderijo(db, html):
    """Probabilidade (0..1) de mandar no esconderijo neste ciclo. Sobe conforme
    a proteção de iniciante acaba ('na sorte'): p = 1 - restante/máximo, onde o
    'máximo' é a maior proteção já vista (gravada no meta), então não precisa
    saber o total exato do servidor. ~0 no começo, ~1 quando a proteção zera.
    A proteção vem do texto 'ainda tem HH:MM:SS horas de proteção' (dorf1)."""
    txt = re.sub(r"<[^>]+>", " ", html).replace("‭", "").replace("‬", "")
    m = re.search(r"(\d+):(\d+):(\d+)\s*horas? de prote", txt)
    if not m:
        return 0.0
    rem = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    mx = meta_get(db, "protecao_max_seg")
    mx = max(int(mx) if mx else 0, rem)
    meta_set(db, "protecao_max_seg", mx)
    return max(0.0, min(1.0, 1.0 - rem / mx)) if mx > 0 else 0.0


def decidir_dorf2(t, db, cfg, html_dorf1):
    """Decisão do dorf2: primeiro a RAMPA DO ESCONDERIJO ('na sorte', sobe com o
    fim da proteção); se não sortear (ou já no alvo), escolhe evoluir × criar
    novo. Para de mirar o esconderijo ao atingir CRANNY_NIVEL_ALVO (~2000)."""
    cfg = cfg or {}
    p = prob_esconderijo(db, html_dorf1)
    nivel_alvo = int(cfg.get("CRANNY_NIVEL_ALVO", "10"))
    if random.random() < p:
        ok, msg = t.subir_ou_criar_esconderijo(nivel_alvo)
        if ok:
            return ok, "ESCONDERIJO(p=%.0f%%): %s" % (p * 100, msg)
        ok2, msg2 = t.construir_ou_evoluir_dorf2(cfg)   # já no alvo/recusa -> normal
        return ok2, "ESCONDERIJO(p=%.0f%%) n/d (%s) -> %s" % (p * 100, msg, msg2)
    return t.construir_ou_evoluir_dorf2(cfg)


def proximo_evento_seg(db, minimo=300, maximo=1800):
    """Segundos até o próximo horário relevante (fim de obra / chegada de
    tropa) no SQLite, limitado a [minimo, maximo] — para o loop dormir até o
    próximo evento em vez de navegar à toa."""
    agora = datetime.now(timezone.utc).astimezone()
    futuros = []
    for sql in ("SELECT fim FROM construcoes WHERE fim IS NOT NULL",
                "SELECT chegada FROM movimentos WHERE chegada IS NOT NULL"):
        for (v,) in db.execute(sql):
            try:
                dt = datetime.fromisoformat(v)
                if dt > agora:
                    futuros.append((dt - agora).total_seconds())
            except Exception:
                pass
    if not futuros:
        return maximo
    return int(max(minimo, min(maximo, min(futuros) + 5)))


# ---- PROXIMO_SCRIPT_IMEDIATO: slot de PRIORIDADE MÁXIMA (one-shot) ----
# O executor tem 3 níveis de prioridade:
#   1) imediato  -> roda JÁ no próximo ciclo, na frente de tudo (este slot)
#   2) agendados -> quando o horário/evento chega (gates de tempo)
#   3) loop      -> a cada ciclo
# Qualquer script pode enfileirar o próximo com agendar_imediato(db, "nome").
# O slot vive em meta['proximo_imediato'] e é consumido (limpo) ao rodar.
def agendar_imediato(db, nome):
    """Coloca um script no slot imediato (roda no início do próximo ciclo)."""
    meta_set(db, "proximo_imediato", nome)


def _exec_script(nome, t, db, cfg):
    """Executa um script pelo nome (usado pelo slot imediato)."""
    if nome == "transferir_recursos":
        _, _, _, fez = t.transferir_recursos()
        # marca se foi inútil (herói vazio) p/ evoluir_controlado não reagendar
        meta_set(db, "transfer_vazio", "" if fez else _agora())
        return "transfer ok" if fez else "nada a transferir (herói vazio)"
    if nome in ("construir_dorf1", "dorf1"):
        return evoluir_controlado(t, db, "dorf1", None, cfg)[1]
    if nome in ("construir_dorf2", "dorf2"):
        return evoluir_controlado(t, db, "dorf2", None, cfg)[1]
    return "script desconhecido: %s" % nome


def ciclo(t, db, cfg):
    """Uma passada do executor. Roda primeiro o script IMEDIATO (se houver),
    depois lê o dorf1 UMA vez e só age no que está pendente (indicadores) ou na
    hora certa (gates de horário no SQLite)."""
    log = []
    # --- PRIORIDADE 1: próximo script imediato (one-shot, na frente de tudo) ---
    prox = meta_get(db, "proximo_imediato")
    if prox:
        meta_set(db, "proximo_imediato", "")          # consome o slot
        log.append("IMEDIATO[%s]: %s" % (prox, _exec_script(prox, t, db, cfg)))
    _, html = t.ir(t.base + "/dorf1.php", 4)

    # --- OBRIGATÓRIOS (só agem se o indicador/condição manda) ---
    if re.search(r'id="questmasterButton"[^>]*\bclaimable\b', html):
        n = t.recolher_missoes()
        if n:
            log.append("collect=%d" % n)
    rind = re.search(r'class="reports"[^>]*>\s*<div class="indicator">(\d+)', html)
    if rind and int(rind.group(1)) > 0:
        reps = t.listar_relatorios()
        for r in reps:
            salvar_relatorio(db, t.ler_relatorio(r["rid"], r["s"]))
        log.append("reports=%d" % len(reps))
    if t.tem_tarefas_diarias(html):
        dq = t.ler_tarefas_diarias()
        log.append("daily(reward=%s)" % dq["recompensa_disponivel"])
    if not t.heroi_em_aventura(html):
        if t.num_aventuras(html) > 0:
            log.append("aventura: %s" % t.fazer_aventura()[1])
        okh, msgh = t.evoluir_heroi(cfg.get("HEROI_ATRIBUTO", "producao"))
        if okh:
            log.append("hero: %s" % msgh)

    # --- CONSTRUÇÃO (agendado). transferir_recursos NÃO roda aqui: só entra
    # via PROXIMO_SCRIPT_IMEDIATO quando um build falha por falta de recurso.
    # Romano tem 2 filas (1 campo dorf1 + 1 edifício dorf2): tenta os DOIS.
    tribo = tribo_conta(t, db)
    if tribo and tribo.lower().startswith("romano"):
        for onde in ("dorf1", "dorf2"):
            oke, msge = evoluir_controlado(t, db, onde, html, cfg)
            log.append("evolve %s: %s" % (onde, msge))
    else:
        oke, msge = evoluir_controlado(t, db, None, html, cfg)
        log.append("evolve: %s" % msge)

    # --- DIÁRIO: scan do mapa 1x/dia (gate no meta) ---
    ult = meta_get(db, "ultimo_scan_mapa")
    horas = ((datetime.now(datetime.fromisoformat(ult).tzinfo)
              - datetime.fromisoformat(ult)).total_seconds() / 3600
             if ult else None)
    if horas is None or horas >= 23:
        nt, _no = t.escanear_mapa(db)
        meta_set(db, "ultimo_scan_mapa", _agora())
        log.append("scan(%d tiles)" % nt)

    # --- movimentos de tropas (salva horários p/ o próximo ciclo) ---
    for mv in t.ler_movimentos():
        db.execute("INSERT INTO movimentos(ts,tipo,alvo,chegada,segundos,"
                   "detalhe) VALUES (?,?,?,?,?,?)",
                   (_agora(), mv["tipo"], mv["alvo"], mv["chegada"],
                    mv["segundos"], mv["detalhe"]))
    db.commit()

    # --- assalto a oásis (agendado; aventura já rodou acima). Só roda se
    # OASIS_ATIVO no .env -> evita navegar à página de envio sem tropa. ---
    if str(cfg.get("OASIS_ATIVO", "false")).strip().lower() in (
            "1", "true", "sim", "yes"):
        oko, msgo = t.atacar_oasis(db, cfg)
        log.append("oasis: %s" % msgo)

    resumo = "; ".join(log) if log else "nada pendente"
    log_acao(db, "ciclo", True, resumo)
    return resumo


def meta_get(db, chave):
    row = db.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
    return row[0] if row else None


def meta_set(db, chave, valor):
    db.execute("INSERT OR REPLACE INTO meta(chave,valor) VALUES (?,?)",
               (chave, str(valor)))
    db.commit()


def salvar_relatorio(db, rep):
    """Insere/atualiza um relatório (dict) na tabela 'relatorios'."""
    cols = ["rid", "ts", "data_jogo", "tipo", "assunto", "inimigo",
            "inimigo_coord", "distancia", "minha_forca", "forca_inimigo",
            "defesa_inimigo", "minhas_tropas", "tropas_inimigo",
            "minhas_perdas", "perdas_inimigo", "saque", "xp", "vida_delta",
            "premio", "bruto"]
    db.execute("INSERT OR REPLACE INTO relatorios (%s) VALUES (%s)" % (
        ",".join(cols), ",".join("?" * len(cols))),
        [rep.get(c) for c in cols])
    db.commit()


def _agora():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_acao(db, comando, ok, detalhe):
    db.execute("INSERT INTO acoes(ts,comando,ok,detalhe) VALUES (?,?,?,?)",
               (_agora(), comando, 1 if ok else 0, str(detalhe)[:500]))
    db.commit()


def snapshot_estado(db, est, missoes=None):
    e, c = est["estoque"], est["capacidade"]
    db.execute("INSERT INTO estado(ts,madeira,barro,ferro,cereal,cap_madeira,"
               "cap_barro,cap_ferro,cap_cereal,missoes_prontas) VALUES "
               "(?,?,?,?,?,?,?,?,?,?)",
               (_agora(), e["madeira"], e["barro"], e["ferro"], e["cereal"],
                c["madeira"], c["barro"], c["ferro"], c["cereal"], missoes))
    db.commit()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    conta_dir, base, email, senha, cfg = resolver_conta()
    t = Travian(base=base, email=email, senha=senha)
    db = abrir_db(conta_dir)
    ok, detalhe = True, ""

    if cmd == "status":
        est = t.estado()
        prontas = t.missoes_prontas()
        print("== RECURSOS ==")
        print("  %-8s %8s %8s %8s" % ("recurso", "estoque", "capac.", "livre"))
        for nm in RECURSOS:
            print("  %-8s %8d %8d %8d" % (nm, est["estoque"][nm],
                  est["capacidade"][nm], est["livre"][nm]))
        print("== MISSÕES ==")
        print("  prontas para recolher:", prontas)
        snapshot_estado(db, est, prontas)
        detalhe = "missoes=%d estoque=%s" % (
            prontas, {nm: est["estoque"][nm] for nm in RECURSOS})
    elif cmd == "login":
        url = t.login()
        detalhe = "url=%s" % url
        print("URL após login:", url)
    elif cmd == "collect":
        n = t.recolher_missoes()
        ok, detalhe = (n > 0), "recolhidas=%d" % n
        print("missões recolhidas:", n)
    elif cmd == "storage":
        res = t.garantir_armazenamento()
        detalhe = "; ".join("%s: %s" % (nm, r) for nm, r in res)
        for nm, r in res:
            print("  %s: %s" % (nm, r))
    elif cmd == "adventure":
        ok, detalhe = t.fazer_aventura()
        print("aventura:", "ENVIADO" if ok else "não enviou", "->", detalhe)
    elif cmd == "transfer":
        plano, est, inv, ok = t.transferir_recursos()
        detalhe = "transferido %s" % plano if ok else "nada a transferir"
        print("== TRANSFERÊNCIA herói -> armazém/celeiro (máx 80%) ==")
        print("  %-8s %6s %7s %7s %9s" % ("recurso", "herói", "estoq.", "cap", "transf."))
        for nm in RECURSOS:
            print("  %-8s %6d %7d %7d %9d" % (nm, inv.get(nm, 0),
                  est["estoque"][nm], est["capacidade"][nm], plano[nm]))
        print("  ->", detalhe)
    elif cmd == "upgrade" and len(sys.argv) >= 4:
        ok, _ = t.upgrade_campo(int(sys.argv[2]), int(sys.argv[3]))
        detalhe = "slot %s gid %s" % (sys.argv[2], sys.argv[3])
        print("upgrade:", "ok (construindo)" if ok else "falhou")
    elif cmd in ("evolve", "evoluir"):
        onde = sys.argv[2] if len(sys.argv) >= 3 else None  # dorf1|dorf2|aleat.
        ok, detalhe = evoluir_controlado(t, db, onde)
        print("evoluir:", "OK" if ok else "não evoluiu", "->", detalhe)
    elif cmd == "hero":
        estrategia = (sys.argv[2] if len(sys.argv) >= 3
                      else cfg.get("HEROI_ATRIBUTO", "producao"))
        ok, detalhe = t.evoluir_heroi(estrategia)
        print("evoluir herói:", "OK" if ok else "nada", "->", detalhe)
    elif cmd == "ciclo":
        resumo = ciclo(t, db, cfg)
        print("ciclo:", resumo)
        ok, detalhe = True, resumo
    elif cmd == "loop":
        print("== loop executor (Ctrl+C para parar) ==")
        try:
            while True:
                resumo = ciclo(t, db, cfg)
                print("[%s] %s" % (_agora(), resumo))
                if meta_get(db, "proximo_imediato"):
                    seg = 60   # há script imediato pendente -> acorda logo
                    print("  script imediato na fila -> dormindo ~1 min...")
                else:
                    seg = proximo_evento_seg(db)
                    print("  dormindo ~%d min até o próximo evento..." % (seg // 60))
                time.sleep(seg)
        except KeyboardInterrupt:
            print("\nloop parado.")
        db.close()
        return
    elif cmd == "movimentos":
        movs = t.ler_movimentos()
        for mv in movs:
            db.execute("INSERT INTO movimentos(ts,tipo,alvo,chegada,segundos,"
                       "detalhe) VALUES (?,?,?,?,?,?)",
                       (_agora(), mv["tipo"], mv["alvo"], mv["chegada"],
                        mv["segundos"], mv["detalhe"]))
            print("  %s -> alvo %s | chega %s" % (mv["tipo"], mv["alvo"],
                                                  mv["chegada"]))
        db.commit()
        ok, detalhe = (len(movs) > 0), "movimentos=%d" % len(movs)
    elif cmd == "oasis":
        ok, detalhe = t.atacar_oasis(db, cfg)
        print("oásis:", "ENVIADO" if ok else "não enviou", "->", detalhe)
    elif cmd == "scan":
        forcar = len(sys.argv) >= 3 and sys.argv[2] == "force"
        ultimo = meta_get(db, "ultimo_scan_mapa")
        horas = None
        if ultimo:
            dt = datetime.fromisoformat(ultimo)
            horas = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
        if horas is not None and horas < 23 and not forcar:
            print("scan já feito há %.1fh (1x/dia; use 'scan force')" % horas)
            ok, detalhe = True, "pulado (%.1fh)" % horas
        else:
            nt, no = t.escanear_mapa(db)
            meta_set(db, "ultimo_scan_mapa", _agora())
            print("scan: %d tiles salvos, %d oásis próximos com detalhe" % (nt, no))
            ok, detalhe = True, "tiles=%d oasis=%d" % (nt, no)
    elif cmd == "daily":
        dq = t.ler_tarefas_diarias()
        print("== TAREFAS DIÁRIAS ==")
        print("  recompensa para coletar:", "SIM" if dq["recompensa_disponivel"]
              else "não")
        for n, m, desc in dq["tarefas"]:
            print("  [%s/%s] %s" % (n, m, desc))
        ok = True
        detalhe = "recompensa=%s tarefas=%d" % (
            dq["recompensa_disponivel"], len(dq["tarefas"]))
    elif cmd == "reports":
        reps = t.listar_relatorios()
        for r in reps:
            rep = t.ler_relatorio(r["rid"], r["s"])
            salvar_relatorio(db, rep)
            print("  salvo rid=%s tipo=%s data=%s premio=%s" % (
                rep["rid"], rep.get("tipo"), rep.get("data_jogo"),
                rep.get("premio")))
        ok, detalhe = (len(reps) > 0), "salvos=%d" % len(reps)
    else:
        print(__doc__)
        db.close()
        return

    log_acao(db, cmd, ok, detalhe)
    db.close()


if __name__ == "__main__":
    main()
