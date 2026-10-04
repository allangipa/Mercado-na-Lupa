#!/usr/bin/env python3
"""Taxas e preços dos títulos do Tesouro Direto -> dados/tesouro.json.

    python _src/tesouro.py

Fonte: Tesouro Transparente (Tesouro Nacional), conjunto "Taxas dos Títulos Ofertados pelo
Tesouro Direto", licença ODbL (conferida na API CKAN em 03/10/2026):
  https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto
O CSV traz, por título e por dia (desde 2002): taxa e preço unitário de compra e de venda
da manhã, e o preço base. ~15 MB; baixado em _tmp/ (fora do git).

Grava:
  - o último dia do arquivo, título a título;
  - histórico SEMANAL (último dia útil de cada semana) da taxa de compra e de venda,
    nos últimos 3 anos, só dos títulos que aparecem no último dia.

Falha ISOLADA: se o Tesouro não responder ou o arquivo vier estranho, fica a coleta
anterior, o erro vai para o JSON (a status.html mostra) e o script sai com 0.
"""
import csv
import datetime as dt
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
SAIDA = RAIZ / "dados" / "tesouro.json"
PACOTE = "df56aa42-484a-4a59-8184-7676580c81e3"
API = f"https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id={PACOTE}"
PAGINA = "https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto"
CABECALHO = ["Tipo Titulo", "Data Vencimento", "Data Base", "Taxa Compra Manha", "Taxa Venda Manha",
             "PU Compra Manha", "PU Venda Manha", "PU Base Manha"]
ANOS_HIST = 3
UA = {"User-Agent": "mercadonalupa.com.br"}


def num(s):
    return float(s.replace(".", "").replace(",", ".")) if s.strip() else None


def data(s):
    return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date()


def baixar():
    with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=60) as r:
        pac = json.loads(r.read().decode("utf-8"))["result"]
    rec = [x for x in pac["resources"] if x["url"].lower().endswith(".csv")]
    if not rec:
        raise ValueError("pacote sem recurso CSV")
    rec = rec[0]
    TMP.mkdir(exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(rec["url"], headers=UA), timeout=300) as r:
        corpo = r.read()
    (TMP / "tesouro.csv").write_bytes(corpo)
    return corpo, rec["url"], rec.get("last_modified") or rec.get("created"), pac.get("license_title")


def ler(corpo):
    txt = corpo.decode("latin-1")
    linhas = list(csv.reader(io.StringIO(txt), delimiter=";"))
    if [c.strip() for c in linhas[0]] != CABECALHO:
        raise ValueError(f"cabeçalho mudou: {linhas[0]}")
    out = []
    for i, l in enumerate(linhas[1:], start=2):
        if not l:
            continue
        if len(l) != 8:
            raise ValueError(f"linha {i} com {len(l)} campos")
        r = {"tipo": l[0].strip(), "venc": data(l[1]), "data": data(l[2]),
             "tx_c": num(l[3]), "tx_v": num(l[4]), "pu_c": num(l[5]), "pu_v": num(l[6]), "pu_b": num(l[7])}
        for k in ("tx_c", "tx_v"):
            if r[k] is not None and not -5 < r[k] < 40:
                raise ValueError(f"linha {i}: taxa fora de faixa {r[k]}")
        for k in ("pu_c", "pu_v", "pu_b"):
            if r[k] == 0:  # o arquivo usa 0,00 para "sem preço naquele dia" (título fora de oferta)
                r[k] = None
        if r["pu_v"] is not None and not 0 < r["pu_v"] < 1e6:
            raise ValueError(f"linha {i}: PU fora de faixa {r['pu_v']}")
        out.append(r)
    if len(out) < 10000:
        raise ValueError(f"só {len(out)} linhas")
    return out


def chave(r):
    return f"{r['tipo']}|{r['venc'].isoformat()}"


def montar(linhas):
    ult = max(r["data"] for r in linhas)
    hoje = [r for r in linhas if r["data"] == ult]
    if len(hoje) < 10:
        raise ValueError(f"último dia ({ult}) com só {len(hoje)} títulos")
    vivos = {chave(r) for r in hoje}
    corte = ult - dt.timedelta(days=365 * ANOS_HIST + 3)
    # último dia de cada semana ISO, por título
    semana = {}
    for r in linhas:
        if r["data"] < corte:
            continue
        k = chave(r)
        if k not in vivos:
            continue
        s = r["data"].isocalendar()[:2]
        if (k, s) not in semana or r["data"] > semana[(k, s)]["data"]:
            semana[(k, s)] = r
    hist = {}
    for (k, _), r in sorted(semana.items(), key=lambda x: x[1]["data"]):
        hist.setdefault(k, []).append([r["data"].isoformat(), r["tx_c"], r["tx_v"]])
    # o último dia sempre entra (a semana corrente pode não ter fechado)
    titulos = []
    for r in sorted(hoje, key=lambda r: (r["tipo"], r["venc"])):
        titulos.append({"tipo": r["tipo"], "vencimento": r["venc"].isoformat(), "taxa_compra": r["tx_c"],
                        "taxa_venda": r["tx_v"], "pu_compra": r["pu_c"], "pu_venda": r["pu_v"], "pu_base": r["pu_b"]})
    return ult.isoformat(), titulos, hist


def main():
    velho = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    try:
        corpo, url, modificado, licenca = baixar()
        ult, titulos, hist = montar(ler(corpo))
        saida = {"_leia": "Gerado por _src/tesouro.py. Tesouro Transparente, Taxas dos Títulos Ofertados pelo Tesouro Direto (ODbL).",
                 "ok": True, "coletado_em": agora, "fonte": PAGINA, "csv": url, "arquivo_modificado_em": modificado,
                 "licenca": licenca, "data_base": ult, "titulos": titulos, "historico": hist}
        print(f"  tesouro: {len(titulos)} títulos em {ult}; histórico de {len(hist)} títulos")
    except Exception as ex:  # noqa: BLE001 — falha isolada de propósito
        saida = {**velho, "ok": False, "erro": f"{type(ex).__name__}: {ex}"[:300], "falhou_em": agora}
        print(f"  tesouro: FALHOU ({ex}); mantida a coleta anterior")
    SAIDA.parent.mkdir(exist_ok=True)
    corpo = json.dumps(saida, ensure_ascii=False, separators=(",", ":"))
    SAIDA.write_text(corpo.replace("],[", "],\n[") + "\n", encoding="utf-8")
    print("ok: dados/tesouro.json")


if __name__ == "__main__":
    main()
