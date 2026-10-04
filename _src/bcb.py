#!/usr/bin/env python3
"""Indicadores do Banco Central (dados abertos) -> dados/bcb.json.

    python _src/bcb.py

SGS (Sistema Gerenciador de Séries Temporais), licença ODbL no portal de dados abertos do BC:
  selic_meta  432    Meta Selic definida pelo Copom (% a.a.)
  selic       11     Selic over, taxa diária (% a.d.)
  selic_ano   1178   Selic over anualizada, base 252 (% a.a.)
  cdi         12     CDI (taxa DI), diária (% a.d.)
  cdi_ano     4389   CDI anualizado, base 252 (% a.a.)
  ipca        433    IPCA, variação mensal (%) — IBGE, publicado no SGS
  ipca12      13522  IPCA acumulado em 12 meses (%)
  poupanca    195    Poupança (depósitos a partir de 04/05/2012): rendimento no período (% no mês),
                     por data de aniversário — cada ponto leva [início, valor, fim]
  tr          226    TR (taxa referencial) por período mensal [início, valor, fim]
PTAX (API Olinda do BC, mesma licença):
  dolar, euro  cotação PTAX de venda e compra do boletim de fechamento.

A API JSON do SGS (api.bcb.gov.br) não resolvia no DNS em 03/10/2026: o script tenta ela
e cai para o serviço SOAP oficial do SGS (www3.bcb.gov.br/wssgs). IGP-M fica de fora de
propósito: é índice da FGV, sem publicação no portal de dados abertos do BC (ver README).

Falha ISOLADA: série que não responder fica com a coleta anterior, o erro vai para o
arquivo (a status.html mostra) e o script sai com 0.
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "bcb.json"
INICIO = dt.date(2021, 1, 1)
UA = {"User-Agent": "mercadonalupa.com.br"}

SERIES = {
    "selic_meta": (432, "Meta Selic definida pelo Copom (% ao ano)"),
    "selic": (11, "Selic over — taxa diária (% ao dia)"),
    "selic_ano": (1178, "Selic over anualizada, base 252 (% ao ano)"),
    "cdi": (12, "CDI — taxa DI diária (% ao dia)"),
    "cdi_ano": (4389, "CDI anualizado, base 252 (% ao ano)"),
    "ipca": (433, "IPCA — variação mensal (%)"),
    "ipca12": (13522, "IPCA acumulado em 12 meses (%)"),
    "poupanca": (195, "Poupança (depósitos desde 04/05/2012) — rendimento no período mensal (%)"),
    "tr": (226, "TR — taxa referencial do período mensal (%)"),
}
# a meta Selic e os períodos mensais (poupança, TR) vêm com uma linha por dia corrido
MIN_PONTOS = 12

URL_JSON = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{n}/dados?formato=json&dataInicial={i}&dataFinal={f}"
SOAP = "https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS"
OLINDA = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"


def _data(s):
    p = [int(x) for x in s.split("/")]
    return dt.date(p[-1], p[-2], p[0] if len(p) == 3 else 1).isoformat()


def coleta_json(n):
    hoje = dt.date.today()
    u = URL_JSON.format(n=n, i=INICIO.strftime("%d/%m/%Y"), f=hoje.strftime("%d/%m/%Y"))
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    out = []
    for x in d:
        p = [_data(x["data"]), float(x["valor"])]
        if x.get("datafim"):
            p.append(_data(x["datafim"]))
        out.append(p)
    return out, u


def coleta_soap(n):
    hoje = dt.date.today()
    corpo = ('<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
             'xmlns:pub="http://publico.ws.casosdeuso.sgs.pec.bcb.gov.br"><soapenv:Body><pub:getValoresSeriesXML>'
             f'<in0><long>{n}</long></in0><in1>{INICIO.strftime("%d/%m/%Y")}</in1><in2>{hoje.strftime("%d/%m/%Y")}</in2>'
             '</pub:getValoresSeriesXML></soapenv:Body></soapenv:Envelope>').encode()
    req = urllib.request.Request(SOAP, data=corpo, headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""', **UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = html.unescape(r.read().decode("utf-8"))
    out = []
    for item in re.findall(r"<ITEM>(.*?)</ITEM>", txt, re.S):
        d = re.search(r"<DATA>([^<]+)</DATA>", item)
        v = re.search(r"<VALOR>([^<]*)</VALOR>", item)
        f = re.search(r"<DATAFIM>([^<]+)</DATAFIM>", item)
        if not d or not v or not v.group(1).strip():
            continue
        p = [_data(d.group(1)), float(v.group(1))]
        if f:
            p.append(_data(f.group(1)))
        out.append(p)
    return out, f"{SOAP} (getValoresSeriesXML, série {n})"


def conferir(pts, periodo):
    if len(pts) < MIN_PONTOS:
        raise ValueError(f"só {len(pts)} pontos — resposta estranha")
    if periodo:
        # poupança e TR: mesma data de início pode repetir com outro fim (fim de mês); fica a chave (início, fim)
        chaves = [(p[0], p[2]) for p in pts]
    else:
        chaves = [p[0] for p in pts]
    if chaves != sorted(chaves) or len(set(chaves)) != len(chaves):
        raise ValueError("datas fora de ordem ou repetidas")
    for p in pts:
        if not -50 < p[1] < 100:
            raise ValueError(f"valor fora de faixa: {p}")


def coleta(n):
    try:
        pts, u = coleta_json(n)
    except Exception:  # noqa: BLE001 — cai para o serviço SOAP oficial
        pts, u = coleta_soap(n)
    conferir(pts, any(len(p) == 3 for p in pts))
    return pts, u


def ptax(moeda):
    """Boletim de fechamento da PTAX, desde 2 anos atrás. [data, compra, venda]."""
    hoje = dt.date.today()
    ini = (hoje - dt.timedelta(days=740)).strftime("%m-%d-%Y")
    fim = hoje.strftime("%m-%d-%Y")
    if moeda == "USD":
        u = (OLINDA + "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?"
             + urllib.parse.urlencode({"@dataInicial": f"'{ini}'", "@dataFinalCotacao": f"'{fim}'", "$format": "json",
                                       "$top": "2000"}))
    else:
        u = (OLINDA + "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?"
             + urllib.parse.urlencode({"@moeda": f"'{moeda}'", "@dataInicial": f"'{ini}'", "@dataFinalCotacao": f"'{fim}'",
                                       "$format": "json", "$top": "5000", "$filter": "tipoBoletim eq 'Fechamento'"},
                                      quote_via=urllib.parse.quote))
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90) as r:
        d = json.loads(r.read().decode("utf-8"))["value"]
    out = {}
    for x in d:
        if x.get("tipoBoletim", "Fechamento") != "Fechamento":
            continue
        data = x["dataHoraCotacao"][:10]
        out[data] = [data, round(float(x["cotacaoCompra"]), 4), round(float(x["cotacaoVenda"]), 4)]
    pts = [out[k] for k in sorted(out)]
    if len(pts) < 200:
        raise ValueError(f"só {len(pts)} boletins — resposta estranha")
    for p in pts:
        if not 1 < p[2] < 20 or p[1] > p[2]:
            raise ValueError(f"cotação fora de faixa: {p}")
    return pts, u.split("?")[0]


def main():
    velho = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {"series": {}}
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    saida = {"_leia": "Gerado por _src/bcb.py. Banco Central do Brasil: SGS e PTAX (dados abertos, ODbL).",
             "coletado_em": agora, "series": {}}
    tarefas = [(k, n, nome, (lambda n=n: coleta(n))) for k, (n, nome) in SERIES.items()]
    tarefas += [("dolar", "PTAX", "Dólar dos EUA — PTAX, boletim de fechamento (R$)", lambda: ptax("USD")),
                ("euro", "PTAX", "Euro — PTAX, boletim de fechamento (R$)", lambda: ptax("EUR"))]
    for k, n, nome, f in tarefas:
        ant = velho["series"].get(k, {})
        try:
            pts, u = f()
            saida["series"][k] = {"nome": nome, "sgs": n, "url": u, "ok": True, "coletado_em": agora, "pontos": pts}
            print(f"  {k}: {len(pts)} pontos, último {pts[-1][0]} = {pts[-1][1:]}")
        except Exception as ex:  # noqa: BLE001 — falha isolada de propósito
            saida["series"][k] = {**ant, "nome": nome, "sgs": n, "ok": False, "erro": f"{type(ex).__name__}: {ex}"[:300],
                                  "falhou_em": agora}
            print(f"  {k}: FALHOU ({ex}); mantida a coleta anterior")
    SAIDA.parent.mkdir(exist_ok=True)
    corpo = json.dumps(saida, ensure_ascii=False, separators=(",", ":"))
    SAIDA.write_text(corpo.replace("],[", "],\n[") + "\n", encoding="utf-8")
    print("ok: dados/bcb.json")


if __name__ == "__main__":
    main()
