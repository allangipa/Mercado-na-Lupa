#!/usr/bin/env python3
"""Comunicados oficiais das empresas e fundos acompanhados, dos dados abertos da CVM.

    python _src/comunicados.py

Companhias abertas — documentos IPE (dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/):
    fato relevante, comunicado ao mercado, aviso aos acionistas. O link é o do
    próprio documento no sistema da CVM (rad.cvm.gov.br). Casa pelo CNPJ das
    ações de _src/ativos.json e pelo código CVM dos BDRs patrocinados.
Fundos imobiliários — documentos eventuais de fundos (dados.cvm.gov.br/dados/FI/DOC/EVENTUAL/):
    fato relevante, aviso ao mercado, relatório gerencial. O link é o do
    documento no Fundos.NET (B3), como a CVM publica. Não há campo de assunto
    nesse conjunto: a página mostra o tipo do documento e a data.

Grava dados/comunicados.json: os 10 mais recentes de cada empresa/fundo, e os 30
mais recentes de empresas e os 30 de fundos para a página geral. Falha ISOLADA: se uma fonte não responder, o que já
estava gravado dela fica, o erro é anotado no arquivo (a status.html mostra) e
o script sai com código 0 — as cotações não podem parar por causa disto.
"""
import csv
import datetime as dt
import email.utils
import io
import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
csv.field_size_limit(10_000_000)
RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
SAIDA = RAIZ / "dados" / "comunicados.json"
UA = {"User-Agent": "mercadonalupa.com.br (dados abertos)"}

IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
EVENTUAL = "https://dados.cvm.gov.br/dados/FI/DOC/EVENTUAL/DADOS/eventual_fi_{ano}.csv"
CATEGORIAS_IPE = {"Fato Relevante": "Fato relevante", "Comunicado ao Mercado": "Comunicado ao mercado",
                  "Aviso aos Acionistas": "Aviso aos acionistas"}
TIPOS_FII = {"FATO RELEV": "Fato relevante", "AVISO MERCADO": "Aviso ao mercado", "RELAT GERENCIAL": "Relatório gerencial"}
POR_ATIVO = 10
POR_ATIVO_PROV = 12
PROVENTO = re.compile(r"dividend|juros\s+sobre\s+(o\s+)?capital|\bjcp\b|provento|remunera[çc][ãa]o\s+aos\s+acionistas|rendimento", re.I)
GERAL = 60
LINK_OK = re.compile(r"^https://(www\.rad\.cvm\.gov\.br/ENET/|fnet\.bmfbovespa\.com\.br/fnet/publico/)")


def baixar(url, nome):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        corpo = r.read()
        mod = r.headers.get("Last-Modified")
    TMP.mkdir(exist_ok=True)
    (TMP / nome).write_bytes(corpo)
    quando = email.utils.parsedate_to_datetime(mod).astimezone(dt.timezone.utc).isoformat(timespec="minutes") if mod else None
    return corpo, quando


def limpa(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").strip())


def coleta_ipe(alvos_cnpj, alvos_cvm, ano):
    docs, atualizado = {}, None
    for a in (ano - 1, ano):
        corpo, mod = baixar(IPE.format(ano=a), f"ipe{a}.zip")
        atualizado = mod or atualizado
        z = zipfile.ZipFile(io.BytesIO(corpo))
        linhas = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode("latin-1")), delimiter=";")
        for l in linhas:
            if l["Categoria"] not in CATEGORIAS_IPE:
                continue
            chave = l["CNPJ_Companhia"].strip()
            if chave not in alvos_cnpj:
                chave = "cvm:" + l["Codigo_CVM"].strip().lstrip("0")
                if chave not in alvos_cvm:
                    continue
            link = l["Link_Download"].strip()
            if not LINK_OK.match(link):
                continue
            prot = l["Protocolo_Entrega"].strip()
            ver = int(l["Versao"] or 1)
            if prot in docs and docs[prot][0] >= ver:
                continue
            assunto = limpa(l["Assunto"]) or limpa(l["Especie"]) or limpa(l["Tipo"]) or CATEGORIAS_IPE[l["Categoria"]]
            doc = {"k": chave, "d": l["Data_Entrega"].strip(), "c": CATEGORIAS_IPE[l["Categoria"]], "a": assunto[:220], "u": link}
            if PROVENTO.search(assunto + " " + l["Tipo"] + " " + l["Especie"]):
                doc["p"] = 1
            docs[prot] = (ver, doc)
    return [d for _, d in docs.values()], atualizado


def coleta_fii(alvos, ano):
    corpo, mod = baixar(EVENTUAL.format(ano=ano), f"eventual{ano}.csv")
    docs = {}
    for l in csv.DictReader(io.StringIO(corpo.decode("latin-1")), delimiter=";"):
        if l["TP_DOC"].strip() not in TIPOS_FII or l["CNPJ_FUNDO_CLASSE"].strip() not in alvos:
            continue
        link = l["LINK_ARQ"].strip()
        if not LINK_OK.match(link):
            continue
        rotulo = TIPOS_FII[l["TP_DOC"].strip()]
        comp = l["DT_COMPTC"].strip()
        a = rotulo + (f" (referência {comp[8:10]}/{comp[5:7]}/{comp[:4]})" if comp and rotulo == "Relatório gerencial" else "")
        docs[link] = {"k": l["CNPJ_FUNDO_CLASSE"].strip(), "d": l["DT_RECEB"].strip(), "c": rotulo, "a": a, "u": link}
    return list(docs.values()), mod


def main():
    ativos = json.loads((RAIZ / "_src" / "ativos.json").read_text(encoding="utf-8"))
    acoes = {a["cnpj"] for a in ativos if a["tipo"] == "acao" and a.get("cnpj")}
    bdrs = {"cvm:" + a["codigo_cvm"].lstrip("0") for a in ativos if a["tipo"] == "bdr" and a.get("codigo_cvm")}
    fiis = {a["cnpj"] for a in ativos if a["tipo"] == "fii" and a.get("cnpj")}
    velho = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {"fontes": {}, "docs": []}
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    ano = dt.date.today().year
    fontes, docs = {}, []
    for nome, rot, url, func in (("ipe", "CVM — documentos IPE de companhias abertas", IPE.format(ano=ano),
                                  lambda: coleta_ipe(acoes, bdrs, ano)),
                                 ("fii", "CVM — documentos eventuais de fundos (FIIs)", EVENTUAL.format(ano=ano),
                                  lambda: coleta_fii(fiis, ano))):
        ant = velho.get("fontes", {}).get(nome, {})
        try:
            novos, mod = func()
            if not novos:
                raise ValueError("nenhum documento dos ativos acompanhados — formato mudou?")
            docs += novos
            fontes[nome] = {"nome": rot, "url": url, "ok": True, "coletado_em": agora, "arquivo_cvm_em": mod,
                            "ultimo_documento": max(d["d"] for d in novos), "documentos": len(novos)}
            print(f"  {nome}: {len(novos)} documentos, último de {fontes[nome]['ultimo_documento']}")
        except Exception as ex:  # noqa: BLE001 — falha isolada de propósito
            docs += [d for d in velho.get("docs", []) if d.get("f") == nome]
            fontes[nome] = {**ant, "nome": rot, "url": url, "ok": False, "erro": f"{type(ex).__name__}: {ex}"[:300],
                            "falhou_em": agora}
            print(f"  {nome}: FALHOU ({ex}); mantido o que havia")
    for d in docs:
        d.setdefault("f", "fii" if d["u"].startswith("https://fnet.") else "ipe")
    docs.sort(key=lambda d: (d["d"], d["u"]), reverse=True)
    por, mantidos = {}, []
    for d in docs:
        n = por.setdefault(d["k"], 0)
        if n < POR_ATIVO:
            por[d["k"]] = n + 1
            mantidos.append(d)
    # avisos sobre proventos (seção Dividendos da página do ativo), além dos 10 gerais
    por_p = {}
    for d in docs:
        if d.get("p") and d not in mantidos:
            n = por_p.setdefault(d["k"], 0)
            if n < POR_ATIVO_PROV:
                por_p[d["k"]] = n + 1
                mantidos.append(d)
    recentes = [d for f in ("ipe", "fii") for d in [x for x in docs if x["f"] == f][:GERAL // 2]]
    geral = {d["u"] for d in recentes}
    mantidos += [d for d in recentes if d not in mantidos]
    saida = {"_leia": "Gerado por _src/comunicados.py. 10 mais recentes por empresa/fundo + 30 mais recentes de empresas e 30 de fundos.",
             "coletado_em": agora, "fontes": fontes, "geral": sorted(geral), "docs": mantidos}
    # uma linha por documento: o diff do dia fica pequeno
    corpo = json.dumps({k: v for k, v in saida.items() if k != "docs"}, ensure_ascii=False, indent=1)[:-2]
    corpo += ',\n "docs": [\n' + ",\n".join("  " + json.dumps(d, ensure_ascii=False) for d in mantidos) + "\n ]\n}\n"
    SAIDA.write_text(corpo, encoding="utf-8")
    print(f"ok: {len(mantidos)} comunicados de {len(por)} empresas/fundos")


if __name__ == "__main__":
    main()
