#!/usr/bin/env python3
"""Procura, nos eventos corporativos da B3, a explicação de cada variação
diária acima de 25% que ainda não está declarada em _src/eventos.json.

    python _src/eventos_b3.py          lista o que achou, não grava
    python _src/eventos_b3.py --gravar acrescenta em _src/eventos.json só o
                                       que bateu com um evento da B3

Fonte: as mesmas chamadas que a página de cada empresa/fundo no site da B3 usa
(GetListedSupplementCompany para empresas e BDRs, GetListedSupplementFunds para
fundos imobiliários): desdobramento, grupamento, bonificação, e proventos em
dinheiro, com o "último dia com" (lastDatePrior). O evento vale a partir do
pregão seguinte ao último dia com.

Um evento só é aceito se a variação observada for compatível com o fator
declarado pela B3 (tolerância de 25% sobre a razão esperada). O que não bater
fica de fora e é listado: o build continua parado nele até alguém conferir.
A trava não é desligada em caso nenhum.
"""
import base64
import csv
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "_src"
LIMITE = 25.0
API = "https://sistemaswebb3-listados.b3.com.br/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; mercadonalupa.com.br)"}


def url_b3(ep, payload):
    return API + ep + "/" + base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def b3(ep, payload):
    u = url_b3(ep, payload)
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
        return u, json.loads(r.read().decode("utf-8") or "null")


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def proporcao(x):
    """3.0 -> '3'; 1.3333 -> '1,33'."""
    return (f"{x:.0f}" if abs(x - round(x)) < 0.01 else f"{x:.2f}".replace(".", ","))


def data(s):
    return dt.datetime.strptime(s, "%d/%m/%Y").date().isoformat()


def saltos(eventos):
    ativos = json.loads((SRC / "ativos.json").read_text(encoding="utf-8"))
    for a in ativos:
        arq = RAIZ / "dados" / "cotacoes" / f"{a['codigo']}.csv"
        if not arq.exists():
            continue
        rs = list(csv.DictReader(arq.open(encoding="utf-8")))
        longo = RAIZ / "dados" / "historico" / f"{a['codigo']}.csv"
        if longo.exists():
            antes = [l for l in csv.DictReader(longo.open(encoding="utf-8")) if l["data"] < rs[0]["data"]]
            rs = antes + rs
        for ant, cur in zip(rs, rs[1:]):
            v = (float(cur["fechamento"]) / float(ant["fechamento"]) - 1) * 100
            if abs(v) > LIMITE and cur["data"] not in eventos.get(a["codigo"], {}):
                yield a, ant, cur, v


def explicar(a, ant, cur, v):
    """Devolve (entrada para eventos.json, None) ou (None, motivo)."""
    raiz = a["codigo"][:4]
    if a["tipo"] == "fii":
        u, d = b3("fundsProxy/fundsCall/GetListedSupplementFunds", {"identifierFund": raiz, "typeFund": 7})
        d = d or {}
    else:
        u, d = b3("listedCompaniesProxy/CompanyCall/GetListedSupplementCompany", {"issuingCompany": raiz, "language": "pt-br"})
        d = (d or [{}])[0]
    razao_obs = float(cur["fechamento"]) / float(ant["fechamento"])
    candidatos = []
    # eventos em ações na janela: os fatores se multiplicam (a B3 às vezes lança
    # desdobramento e grupamento no mesmo dia, como no VIVT3 em 2025)
    # só os eventos do próprio papel (a B3 lista um por ISIN: ON e PN aparecem separados)
    isin = json.loads((RAIZ / "dados" / "papeis.json").read_text(encoding="utf-8"))[a["codigo"]]["isin"]
    na_janela = [ev for ev in d.get("stockDividends") or [] if ant["data"] <= data(ev["lastDatePrior"]) < cur["data"]
                 and ev.get("isinCode", isin) in (isin, "")]
    esperado, textos, cisao = 1.0, [], []
    for ev in na_janela:
        f, rot = num(ev["factor"]), ev["label"].upper()
        if "GRUPAMENTO" in rot:
            esperado *= f if f < 1 else 1 / f      # B3 publica 0,1 (10 viram 1)
            esperado_txt = f"grupamento de {proporcao(1 / f if f < 1 else f)} para 1"
        elif "DESDOBRAMENTO" in rot or "BONIFICA" in rot:
            esperado *= 1 + f / 100
            esperado_txt = (f"desdobramento de 1 para {proporcao(1 + f / 100)}" if "DESDOBRA" in rot
                            else f"bonificação de {proporcao(f)}% em novos papéis")
        elif rot.startswith("CIS"):
            cisao.append(ev)
            continue
        else:
            continue
        textos.append(esperado_txt)
    if textos:
        txt = " e ".join(textos)
        if len(textos) > 1:
            txt += (f" (no conjunto, 1 para {proporcao(esperado)})" if esperado >= 1 else f" (no conjunto, {proporcao(1 / esperado)} para 1)")
        candidatos.append((1 / esperado, txt, na_janela[0]))
    if cisao:
        ev = cisao[0]
        u2 = u
        return {"evento": f"Cisão com redução de capital, aprovada em {ev.get('approvedOn', '?')}; último dia com direito em "
                          f"{ev['lastDatePrior']}. O fechamento passou de R$ {ant['fechamento'].replace('.', ',')} para "
                          f"R$ {cur['fechamento'].replace('.', ',')}; o preço depois da cisão não é comparável com o de antes.",
                "fonte": u2, "fonte_nome": "B3, eventos corporativos do emissor"}, None
    for ev in d.get("cashDividends") or []:
        if ev.get("isinCode", isin) not in (isin, ""):
            continue
        ldp = data(ev["lastDatePrior"])
        if not (ant["data"] <= ldp < cur["data"]):
            continue
        r = num(ev["rate"])
        esperado = (float(ant["fechamento"]) - r) / float(ant["fechamento"])
        rot = ev["label"].strip().lower()
        candidatos.append((esperado, f"{rot} de R$ {proporcao(r)} por {'cota' if a['tipo'] == 'fii' else 'papel'}", ev))
    for esperado, texto, ev in candidatos:
        if esperado > 0 and abs(razao_obs / esperado - 1) <= 0.25:
            aprov = "aprovados" if " e " in texto else ("aprovada" if texto.startswith(("bonifica", "cis")) else "aprovado")
            desc = (f"{texto[:1].upper() + texto[1:]}, {aprov} em {ev.get('approvedOn', '?')}; último dia com direito em "
                    f"{ev['lastDatePrior']}. O fechamento passou de R$ {ant['fechamento'].replace('.', ',')} para "
                    f"R$ {cur['fechamento'].replace('.', ',')}, e a diferença vem do evento, não de oscilação de mercado.")
            ent = {"evento": desc, "fonte": u, "fonte_nome": "B3, eventos corporativos do emissor"}
            if ev in na_janela:
                # razão de preço do evento em ações (depois ÷ antes), para corrigir a variação de 12 meses
                ent["fator_preco"] = round(esperado, 8)
            return ent, None
    return None, f"nenhum evento da B3 compatível ({len(candidatos)} candidato(s) na janela)"


def main():
    arq = SRC / "eventos.json"
    eventos = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    achados, sem = 0, []
    for a, ant, cur, v in saltos(eventos):
        ent, motivo = explicar(a, ant, cur, v)
        if ent:
            eventos.setdefault(a["codigo"], {})[cur["data"]] = ent
            achados += 1
            print(f"  {a['codigo']} {cur['data']} {v:+.1f}%: {ent['evento']}")
        else:
            sem.append(f"{a['codigo']} {ant['data']}→{cur['data']} {v:+.1f}%: {motivo}")
    for s in sem:
        print("  SEM EXPLICAÇÃO NA B3:", s)
    print(f"{achados} evento(s) achado(s), {len(sem)} sem explicação")
    if "--gravar" in sys.argv and achados:
        arq.write_text(json.dumps(eventos, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("ok: _src/eventos.json")


if __name__ == "__main__":
    main()
