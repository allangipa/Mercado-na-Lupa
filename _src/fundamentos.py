#!/usr/bin/env python3
"""Números de balanço e de proventos, só de dados abertos da CVM.

    python _src/fundamentos.py              baixa o que faltar e grava dados/fundamentos.json
    python _src/fundamentos.py --se-velho   só se o arquivo tiver mais de 7 dias (rotina diária)

Fontes (dados.cvm.gov.br, uso livre):
  DFP  CIA_ABERTA/DOC/DFP  demonstrações anuais (DRE, BPP, DMPL, composição do capital)
  ITR  CIA_ABERTA/DOC/ITR  demonstrações trimestrais
  FII  FII/DOC/INF_MENSAL  informe mensal dos fundos imobiliários
  FCA  CIA_ABERTA/DOC/FCA  quantas ações compõem cada unit

Por companhia (casada pelo CNPJ de _src/ativos.json):
  lucro   lucro líquido atribuído aos controladores (DRE consolidada, conta "Atribuído a
          Sócios da Empresa Controladora"); sem consolidada, o lucro da DRE individual
  receita conta 3.01 da DRE quando ela é "Receita de Venda de Bens e/ou Serviços"
          (bancos e seguradoras têm outro formato: fica sem receita)
  prov    proventos declarados no período: soma das linhas de dividendos e juros sobre
          capital próprio da DMPL, coluna do patrimônio dos controladores ("Patrimônio
          Líquido"), que reduziram o patrimônio (valor negativo). Exclui dividendos
          prescritos; dividendos "propostos" que só mudam de reserva somam zero ali.
  pl      patrimônio líquido atribuído aos controladores (BPP)
  acoes   ações da composição do capital, menos as em tesouraria
12 meses = último exercício (DFP) + acumulado do ano no último ITR − mesmo acumulado do ano
anterior (que o próprio ITR traz). Valores em reais (a escala MIL da CVM é convertida).

A composição do capital da CVM não tem campo de escala: algumas companhias informam em
milhares. O número é conferido contra o total de ações que a B3 publica para a empresa
(só como verificação; não é exibido): se bater × 1 ou × 1000, usa; se não bater (por
exemplo, desdobramento depois do balanço), fica sem número e a página mostra "—".

Fundos imobiliários: para cada mês do informe, rendimento por cota = Percentual de
dividend yield do mês × valor patrimonial da cota, como a CVM publica (o informe não traz
o valor por cota pago nem a data com).
"""
import csv
import datetime as dt
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
csv.field_size_limit(10_000_000)
RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
SAIDA = RAIZ / "dados" / "fundamentos.json"
UA = {"User-Agent": "mercadonalupa.com.br (dados abertos)"}
DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{a}.zip"
ITR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{a}.zip"
FII = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{a}.zip"
FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{a}.zip"
B3_SUP = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetListedSupplementCompany/"
ANOS_DFP = 10


def baixar(url, nome, dias=7):
    """Usa o arquivo de _tmp/ se tiver menos de `dias` dias; senão baixa."""
    TMP.mkdir(exist_ok=True)
    arq = TMP / nome
    if arq.exists() and time.time() - arq.stat().st_mtime < dias * 86400:
        return arq
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r:
        arq.write_bytes(r.read())
    return arq


def linhas(z, nome, cnpjs, col="CNPJ_CIA"):
    if nome not in z.namelist():
        return []
    with z.open(nome) as fh:
        txt = io.TextIOWrapper(fh, encoding="latin-1", newline="")
        r = csv.DictReader(txt, delimiter=";")
        if col not in (r.fieldnames or []):
            col = next((f for f in r.fieldnames if f.startswith("CNPJ_Fundo")), col)
        out = []
        for l in r:
            if l.get(col) in cnpjs:
                l["CNPJ_Fundo_Classe"] = l[col]
                out.append(l)
        return out


def ultima_versao(rows):
    v = {}
    for l in rows:
        k = (l["CNPJ_CIA"], l["DT_REFER"])
        v[k] = max(v.get(k, 0), int(l["VERSAO"] or 1))
    return [l for l in rows if int(l["VERSAO"] or 1) == v[(l["CNPJ_CIA"], l["DT_REFER"])]]


def agrupa(rows):
    g = {}
    for l in ultima_versao(rows):
        g.setdefault((l["CNPJ_CIA"], l["DT_REFER"]), []).append(l)
    return g


def valor(l):
    v = float(l["VL_CONTA"])
    return v * 1000 if l.get("ESCALA_MOEDA", "").upper() == "MIL" else v


def periodos(rows, ordem):
    """Linhas do exercício pedido no período mais longo (acumulado do ano)."""
    rs = [l for l in rows if l["ORDEM_EXERC"] == ordem]
    if not rs:
        return [], None
    ini = min(l.get("DT_INI_EXERC") or l["DT_FIM_EXERC"] for l in rs)
    return [l for l in rs if (l.get("DT_INI_EXERC") or ini) == ini], (ini, rs[0]["DT_FIM_EXERC"])


CONTROLADORA = re.compile(r"atribu[íi]d[oa]s?\s+(a|ao|aos)\s+(s[óo]cios|acionistas)\s+(da\s+)?(empresa\s+)?controladora|atribu[íi]do\s+ao\s+controlador", re.I)
LUCRO_IND = re.compile(r"^lucro.{0,4}(/|ou)\s*preju[íi]zo.*per[íi]odo", re.I)


def lucro(con, ind):
    for l in con:
        if CONTROLADORA.search(l["DS_CONTA"]) and l["CD_CONTA"].startswith("3."):
            return valor(l), "DRE consolidada, atribuído aos controladores"
    cands = [l for l in ind if LUCRO_IND.search(l["DS_CONTA"].strip()) and l["CD_CONTA"].count(".") == 1]
    if cands:
        l = max(cands, key=lambda l: [int(x) for x in l["CD_CONTA"].split(".")])
        return valor(l), "DRE individual (controladora)"
    return None, None


def receita(rows):
    for l in rows:
        if l["CD_CONTA"] == "3.01" and re.search(r"receita.*venda", l["DS_CONTA"], re.I):
            return valor(l)
    return None


def patrimonio(con, ind):
    # o BPP do ITR traz a data do trimestre (ÚLTIMO) e o fim do exercício anterior (PENÚLTIMO)
    con = [l for l in con if l["ORDEM_EXERC"] == "ÚLTIMO"]
    ind = [l for l in ind if l["ORDEM_EXERC"] == "ÚLTIMO"]
    for rows, fonte in ((con, "balanço consolidado"), (ind, "balanço individual")):
        topo = [l for l in rows if l["CD_CONTA"].count(".") == 1 and l["CD_CONTA"].startswith("2.")
                and re.match(r"patrim[ôo]nio l[íi]quido", l["DS_CONTA"].strip(), re.I)]
        if not topo:
            continue
        t = topo[0]
        filhos = [l for l in rows if l["CD_CONTA"].startswith(t["CD_CONTA"] + ".") and l["CD_CONTA"].count(".") == 2]
        ctrl = [l for l in filhos if re.search(r"atribu[íi]do ao controlador", l["DS_CONTA"], re.I)]
        if ctrl:
            return valor(ctrl[0]), fonte
        nc = [l for l in filhos if re.search(r"n[ãa]o\s+controlador", l["DS_CONTA"], re.I)]
        return valor(t) - sum(valor(l) for l in nc), fonte
    return None, None


PROVENTO = re.compile(r"dividend|juros\s+sobre\s+(o\s+)?capital|\bjcp\b", re.I)


def proventos(rows):
    """DMPL: soma (em módulo) das linhas de dividendos/JCP que reduziram o PL dos controladores.
    Só as contas de nível mais alto que casam (a CVM repete o total na conta-mãe e nas filhas).
    Se a coluna dos controladores vier zerada e a consolidada não (layout de alguns bancos,
    com valores deslocados de coluna), devolve None: dado inconsistente não vira número."""
    sel = [l for l in rows if PROVENTO.search(l["DS_CONTA"]) and not re.search(r"prescrit|revers", l["DS_CONTA"], re.I)]
    if not sel:
        return None
    codigos = {l["CD_CONTA"] for l in sel}
    topo = [l for l in sel if not any(l["CD_CONTA"].startswith(c + ".") for c in codigos)]
    col = lambda nome: [l for l in topo if l.get("COLUNA_DF", "").strip().lower() == nome]
    ctrl = col("patrimônio líquido")
    tot = sum(-valor(l) for l in ctrl if valor(l) < 0)
    cons = sum(-valor(l) for l in col("patrimônio líquido consolidado") if valor(l) < 0)
    nci = sum(-valor(l) for l in col("participação dos não controladores") if valor(l) < 0)
    outras = any(valor(l) < 0 for l in topo if l.get("COLUNA_DF", "").strip().lower() not in
                 ("patrimônio líquido", "participação dos não controladores", "patrimônio líquido consolidado"))
    if tot == 0 and (cons - nci > 0.5 or outras):
        return None
    return tot


def composicao(rows):
    if not rows:
        return None, None
    l = rows[0]
    tot = int(float(l["QT_ACAO_TOTAL_CAP_INTEGR"] or 0))
    tes = int(float(l["QT_ACAO_TOTAL_TESOURO"] or 0))
    return (tot - tes if tot else None), tes


class Doc:
    """Uma demonstração (DFP ou ITR) de um ano: tudo agrupado por (CNPJ, data)."""
    def __init__(self, arq, pref, ano, cnpjs):
        z = zipfile.ZipFile(arq)
        g = lambda s: agrupa(linhas(z, f"{pref}_cia_aberta_{s}_{ano}.csv", cnpjs))
        self.dre_con, self.dre_ind = g("DRE_con"), g("DRE_ind")
        self.bpp_con, self.bpp_ind = g("BPP_con"), g("BPP_ind")
        self.dmpl_con, self.dmpl_ind = g("DMPL_con"), g("DMPL_ind")
        self.cap = agrupa(linhas(z, f"{pref}_cia_aberta_composicao_capital_{ano}.csv", cnpjs))
        self.datas = {}
        for (c, d) in list(self.dre_con) + list(self.dre_ind):
            self.datas.setdefault(c, set()).add(d)

    def medidas(self, c, d, ordem):
        k = (c, d)
        con, per = periodos(self.dre_con.get(k, []), ordem)
        ind, per2 = periodos(self.dre_ind.get(k, []), ordem)
        lu, fonte = lucro(con, ind)
        rec = receita(con or ind)
        dm, _ = periodos(self.dmpl_con.get(k, []) or self.dmpl_ind.get(k, []), ordem)
        return {"lucro": lu, "lucro_fonte": fonte, "receita": rec, "prov": proventos(dm), "periodo": per or per2}


def b3_total_acoes(raiz):
    import base64
    p = base64.b64encode(json.dumps({"issuingCompany": raiz, "language": "pt-br"}, separators=(",", ":")).encode()).decode()
    with urllib.request.urlopen(urllib.request.Request(B3_SUP + p, headers=UA), timeout=60) as r:
        d = json.loads(r.read().decode("utf-8") or "null")
    if not d:
        return None
    return int(d[0]["totalNumberShares"].replace(".", "") or 0) or None


def unidades(ano, codigos):
    arq = baixar(FCA.format(a=ano), f"fca{ano}.zip")
    z = zipfile.ZipFile(arq)
    with z.open(f"fca_cia_aberta_valor_mobiliario_{ano}.csv") as fh:
        rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";"))
    out = {}
    for l in rows:
        c = l["Codigo_Negociacao"].strip()
        if c in codigos and l["Valor_Mobiliario"].strip() == "Units":
            nums = [int(x) for x in re.findall(r"(\d+)\s*(?:a[çc](?:[ãa]o|[õo]es)|ON|PN|[A-Z]{4}\d)", l["Composicao_BDR_Unit"], re.I)]
            if nums:
                out[c] = {"acoes": sum(nums), "composicao": l["Composicao_BDR_Unit"].strip()}
    return out


def main():
    if "--se-velho" in sys.argv and SAIDA.exists():
        idade = time.time() - SAIDA.stat().st_mtime
        velho = json.loads(SAIDA.read_text(encoding="utf-8"))
        if (dt.date.today() - dt.date.fromisoformat(velho["gerado_em"][:10])).days < 7:
            print(f"fundamentos de {velho['gerado_em'][:10]}: mantidos")
            return
    hoje = dt.date.today()
    ano = hoje.year
    ativos = json.loads((RAIZ / "_src" / "ativos.json").read_text(encoding="utf-8"))
    acoes = [a for a in ativos if a["tipo"] == "acao" and a.get("cnpj")]
    cnpjs = {a["cnpj"] for a in acoes}
    saida = {"_leia": "Gerado por _src/fundamentos.py. Valores em reais; datas no formato ISO.",
             "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
             "fontes": {}, "empresas": {}, "units": {}, "fiis": {}}

    print("CVM: DFP e ITR…")
    dfps = {}
    for a in range(ano - ANOS_DFP, ano):
        try:
            dfps[a] = Doc(baixar(DFP.format(a=a), f"dfp{a}.zip", dias=30 if a < ano - 1 else 7), "dfp", a, cnpjs)
        except Exception as ex:  # noqa: BLE001
            print(f"  DFP {a}: {ex}")
    itrs = {}
    for a in (ano - 1, ano):
        try:
            itrs[a] = Doc(baixar(ITR.format(a=a), f"itr{a}.zip"), "itr", a, cnpjs)
        except Exception as ex:  # noqa: BLE001
            print(f"  ITR {a}: {ex}")
    saida["fontes"]["cvm_balancos"] = {"nome": "CVM — DFP e ITR de companhias abertas",
                                       "url": "https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp",
                                       "anos_dfp": sorted(dfps), "anos_itr": sorted(itrs)}

    totais_b3 = {}
    for a in acoes:
        raiz = a["codigo"][:4]
        if raiz not in totais_b3:
            try:
                totais_b3[raiz] = b3_total_acoes(raiz)
            except Exception:  # noqa: BLE001
                totais_b3[raiz] = None

    datas_base = {}
    for c in sorted(cnpjs):
        e = {"anos": {}}
        # exercícios anuais
        for a, doc in sorted(dfps.items()):
            for d in sorted(doc.datas.get(c, [])):
                m = doc.medidas(c, d, "ÚLTIMO")
                pl, _ = patrimonio(doc.bpp_con.get((c, d), []), doc.bpp_ind.get((c, d), []))
                qt, _ = composicao(doc.cap.get((c, d), []))
                e["anos"][d[:4]] = {"fim": d, "lucro": m["lucro"], "receita": m["receita"], "prov": m["prov"], "pl": pl, "acoes_cvm": qt}
        # último documento: ITR mais recente depois do último DFP, ou o próprio DFP
        ult_dfp = max((v["fim"] for v in e["anos"].values()), default=None)
        cand = sorted({(d, a) for a, doc in itrs.items() for d in doc.datas.get(c, []) if not ult_dfp or d > ult_dfp})
        ttm = None
        if cand:
            d, a = cand[-1]
            doc = itrs[a]
            cur = doc.medidas(c, d, "ÚLTIMO")
            ant = doc.medidas(c, d, "PENÚLTIMO")
            anual = e["anos"].get(ult_dfp[:4]) if ult_dfp else None
            pl, pl_fonte = patrimonio(doc.bpp_con.get((c, d), []), doc.bpp_ind.get((c, d), []))
            qt, tes = composicao(doc.cap.get((c, d), []))
            tri = {"03": "1T", "06": "2T", "09": "3T"}.get(d[5:7], "")
            if anual and cur["periodo"] and ant["periodo"]:
                def soma(k):
                    vs = (anual[k], cur[k], ant[k])
                    return None if any(v is None for v in vs) else anual[k] + cur[k] - ant[k]
                ttm = {"fim": d, "doc": f"ITR {tri}{d[2:4]} + DFP {ult_dfp[:4]} − ITR {tri}{str(int(d[:4]) - 1)[2:]}",
                       "lucro": soma("lucro"), "receita": soma("receita"), "prov": soma("prov"),
                       "lucro_fonte": cur["lucro_fonte"]}
            e.update(pl=pl, pl_fonte=pl_fonte, pl_data=d, acoes_cvm=qt, tesouraria=tes, acoes_data=d)
        elif ult_dfp:
            an = e["anos"][ult_dfp[:4]]
            doc = dfps[int(ult_dfp[:4])]
            m = doc.medidas(c, ult_dfp, "ÚLTIMO")
            ttm = {"fim": ult_dfp, "doc": f"DFP {ult_dfp[:4]}", "lucro": an["lucro"], "receita": an["receita"],
                   "prov": an["prov"], "lucro_fonte": m["lucro_fonte"]}
            pl, pl_fonte = patrimonio(doc.bpp_con.get((c, ult_dfp), []), doc.bpp_ind.get((c, ult_dfp), []))
            qt, tes = composicao(doc.cap.get((c, ult_dfp), []))
            e.update(pl=pl, pl_fonte=pl_fonte, pl_data=ult_dfp, acoes_cvm=qt, tesouraria=tes, acoes_data=ult_dfp)
        e["ttm"] = ttm
        # escala da composição do capital, conferida contra o total da B3
        raizes = {a["codigo"][:4] for a in acoes if a["cnpj"] == c}
        b3tot = next((totais_b3.get(r) for r in raizes if totais_b3.get(r)), None)
        esc = None
        if e.get("acoes_cvm") and b3tot:
            bruto = e["acoes_cvm"] + (e.get("tesouraria") or 0)
            for f in (1, 1000):
                if abs(bruto * f / b3tot - 1) <= 0.02:
                    esc = f
        e["escala_acoes"] = esc
        if esc:
            e["acoes"] = e["acoes_cvm"] * esc
            for v in e["anos"].values():
                # anos anteriores na mesma escala, se forem coerentes com o atual (sem desdobramento no meio)
                v["acoes"] = v["acoes_cvm"] * esc if v.get("acoes_cvm") and 0.98 <= v["acoes_cvm"] * esc / e["acoes"] <= 1.02 else None
        else:
            e["acoes"] = None
            e["acoes_motivo"] = ("número de ações da CVM não confere com o total publicado pela B3 hoje "
                                 "(mudança no capital depois do último balanço, ou escala diferente)") if e.get("acoes_cvm") else "sem composição do capital na CVM"
            for v in e["anos"].values():
                v["acoes"] = None
        if e.get("pl_data"):
            datas_base[e["pl_data"]] = datas_base.get(e["pl_data"], 0) + 1
        saida["empresas"][c] = e
    saida["fontes"]["cvm_balancos"]["datas_base"] = dict(sorted(datas_base.items(), reverse=True))
    print(f"  {len(saida['empresas'])} companhias; datas-base: {saida['fontes']['cvm_balancos']['datas_base']}")

    try:
        saida["units"] = unidades(ano, {a["codigo"] for a in acoes})
        print(f"  units: {saida['units']}")
    except Exception as ex:  # noqa: BLE001
        print(f"  FCA: {ex}")

    print("CVM: informes mensais dos FIIs…")
    fiis = {a["cnpj"] for a in ativos if a["tipo"] == "fii" and a.get("cnpj")}
    meses = {}
    for a in range(ano - ANOS_DFP, ano + 1):
        try:
            arq = baixar(FII.format(a=a), f"inf_fii_{a}.zip", dias=30 if a < ano - 1 else 7)
        except Exception as ex:  # noqa: BLE001
            print(f"  informe {a}: {ex}")
            continue
        z = zipfile.ZipFile(arq)
        rows = linhas(z, f"inf_mensal_fii_complemento_{a}.csv", fiis, col="CNPJ_Fundo_Classe")
        for l in rows:
            k = (l["CNPJ_Fundo_Classe"], l["Data_Referencia"][:7])
            v = int(l["Versao"] or 1)
            if k in meses and meses[k][0] >= v:
                continue
            try:
                dy, vp = float(l["Percentual_Dividend_Yield_Mes"] or "nan"), float(l["Valor_Patrimonial_Cotas"] or "nan")
            except ValueError:
                continue
            if dy != dy or vp != vp:
                continue
            meses[k] = (v, round(dy * vp, 6), round(vp, 6), dy)
    for (c, m), (_, rend, vp, dy) in sorted(meses.items()):
        saida["fiis"].setdefault(c, []).append([m, rend, vp, round(dy, 6)])
    saida["fontes"]["cvm_fii"] = {"nome": "CVM — informe mensal de FIIs", "url": "https://dados.cvm.gov.br/dataset/fii-doc-inf_mensal",
                                  "ultimo_mes": max((m for (_, m) in meses), default=None)}
    print(f"  {len(saida['fiis'])} fundos, último mês {saida['fontes']['cvm_fii']['ultimo_mes']}")

    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"ok: dados/fundamentos.json ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
