#!/usr/bin/env python3
"""CDI e IPCA do Banco Central (SGS, dados abertos), para a comparação com índices.

    python _src/bcb.py

  CDI   SGS 12  — taxa DI diária, % ao dia
  IPCA  SGS 433 — variação mensal, %
Primeiro tenta a API JSON (api.bcb.gov.br/dados/serie/bcdata.sgs.N/dados); em 03/10/2026
esse endereço não existia mais no DNS (o portal de dados abertos ainda aponta para ele).
Então usa o serviço oficial do SGS em SOAP (www3.bcb.gov.br/wssgs/services/FachadaWSSGS,
operação getValoresSeriesXML), o mesmo listado no portal. Desde 01/01/2021.

Grava dados/bcb.json. Falha ISOLADA: se o BC não responder, fica a coleta anterior,
o erro vai para o arquivo (a status.html mostra) e o script sai com 0.
"""
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "bcb.json"
INICIO = dt.date(2021, 1, 1)
SERIES = {"cdi": (12, "CDI — taxa DI diária (% ao dia)"), "ipca": (433, "IPCA — variação mensal (%)")}
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{n}/dados?formato=json&dataInicial={i}&dataFinal={f}"


SOAP = "https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS"


def coleta_soap(n):
    import html
    import re
    hoje = dt.date.today()
    corpo = ('<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
             'xmlns:pub="http://publico.ws.casosdeuso.sgs.pec.bcb.gov.br"><soapenv:Body><pub:getValoresSeriesXML>'
             f'<in0><long>{n}</long></in0><in1>{INICIO.strftime("%d/%m/%Y")}</in1><in2>{hoje.strftime("%d/%m/%Y")}</in2>'
             '</pub:getValoresSeriesXML></soapenv:Body></soapenv:Envelope>').encode()
    req = urllib.request.Request(SOAP, data=corpo, headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""',
                                                            "User-Agent": "mercadonalupa.com.br"})
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = html.unescape(r.read().decode("utf-8"))
    out = []
    for d, v in re.findall(r"<DATA>([^<]+)</DATA>\s*<VALOR>([^<]*)</VALOR>", txt):
        p = [int(x) for x in d.split("/")]
        data = dt.date(p[-1], p[-2], p[0] if len(p) == 3 else 1).isoformat()
        if v.strip():
            out.append([data, float(v)])
    return out, f"{SOAP} (getValoresSeriesXML, série {n})"


def coleta(n):
    try:
        return coleta_json(n)
    except Exception:  # noqa: BLE001 — cai para o serviço SOAP oficial
        pts, u = coleta_soap(n)
    if len(pts) < 12:
        raise ValueError(f"só {len(pts)} pontos — resposta estranha")
    datas = [p[0] for p in pts]
    if datas != sorted(datas) or len(set(datas)) != len(datas):
        raise ValueError("datas fora de ordem ou repetidas")
    return pts, u


def coleta_json(n):
    hoje = dt.date.today()
    u = URL.format(n=n, i=INICIO.strftime("%d/%m/%Y"), f=hoje.strftime("%d/%m/%Y"))
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "mercadonalupa.com.br"}), timeout=90) as r:
        d = json.loads(r.read().decode("utf-8"))
    out = []
    for x in d:
        data = dt.datetime.strptime(x["data"], "%d/%m/%Y").date().isoformat()
        out.append([data, float(x["valor"])])
    if len(out) < 12:
        raise ValueError(f"só {len(out)} pontos — resposta estranha")
    datas = [p[0] for p in out]
    if datas != sorted(datas) or len(set(datas)) != len(datas):
        raise ValueError("datas fora de ordem ou repetidas")
    return out, u


def main():
    velho = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {"series": {}}
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    saida = {"_leia": "Gerado por _src/bcb.py. Banco Central, SGS (dados abertos).", "coletado_em": agora, "series": {}}
    for k, (n, nome) in SERIES.items():
        ant = velho["series"].get(k, {})
        try:
            pts, u = coleta(n)
            saida["series"][k] = {"nome": nome, "sgs": n, "url": u, "ok": True, "coletado_em": agora, "pontos": pts}
            print(f"  {k}: {len(pts)} pontos, último {pts[-1][0]}")
        except Exception as ex:  # noqa: BLE001 — falha isolada de propósito
            saida["series"][k] = {**ant, "nome": nome, "sgs": n, "ok": False, "erro": f"{type(ex).__name__}: {ex}"[:300],
                                  "falhou_em": agora}
            print(f"  {k}: FALHOU ({ex}); mantida a coleta anterior")
    corpo = json.dumps(saida, ensure_ascii=False, separators=(",", ":"))
    SAIDA.write_text(corpo.replace("],[", "],\n[") + "\n", encoding="utf-8")
    print("ok: dados/bcb.json")


if __name__ == "__main__":
    main()
