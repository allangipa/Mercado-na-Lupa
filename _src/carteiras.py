#!/usr/bin/env python3
"""Monta a LISTA de ativos (_src/ativos.json) a partir de fontes oficiais.

    python _src/carteiras.py            mostra o que mudaria, não grava
    python _src/carteiras.py --gravar   grava _src/ativos.json e _src/carteiras.json

Rode à mão quando a carteira dos índices mudar (o Ibovespa e o IFIX são
rebalanceados em janeiro, maio e setembro) e depois:
    python _src/atualiza.py historico 2025 2026
    python _src/cvm.py
    python _src/build.py

De onde vem cada grupo:
  - Ações: carteira do dia do Ibovespa (B3, GetPortfolioDay, índice IBOV),
    mais as ações e units fora do índice entre as 100 de maior volume
    financeiro no ano corrente (COTAHIST anual), especificação ON/PN/UNT,
    negociadas em todos os pregões do ano.
  - Fundos imobiliários: carteira do dia do IFIX (B3, índice IFIX).
  - BDRs: os 50 de maior volume financeiro no ano corrente no COTAHIST,
    códigos BDI 34 (BDR não patrocinado, especificação DRN) e 35 (BDR
    patrocinado, DR1/DR2/DR3). BDR de ETF (BDI 36, DRE) fica de fora: é cota
    de fundo, e a página de BDR explica empresa.

CNPJ e nome:
  - ações: CNPJ pelo código de negociação no FCA da CVM (valor mobiliário);
    nome curto pelo nome comercial do cadastro da CVM (com ajustes à mão em
    NOMES); os 10 ativos do começo mantêm o nome que já tinham;
  - FIIs: CNPJ pelo ISIN da B3 casado com o ISIN do informe mensal da CVM;
  - BDRs: nome da empresa estrangeira e tipo do programa pela B3
    (GetCompaniesBDR). A bolsa de origem não é informada pela B3 nem pela
    CVM nesses dados, e por isso o site não a cita.
Nada é escolhido por juízo sobre o ativo: são critérios mecânicos, gravados
em _src/carteiras.json com a data e a fonte.
"""
import base64
import collections
import csv
import datetime as dt
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "_src"
TMP = RAIZ / "_tmp"
UA = {"User-Agent": "Mozilla/5.0 (compatible; mercadonalupa.com.br)"}

B3_INDICE = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/"
B3_EMPRESA = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/"
B3_BDR = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetCompaniesBDR/"
PAGINA_INDICE = {
    "IBOV": "https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/indice-ibovespa-ibovespa-composicao-da-carteira.htm",
    "IFIX": "https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-de-segmentos-e-setoriais/indice-de-fundos-de-investimentos-imobiliarios-ifix-composicao-da-carteira.htm",
}
FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip"
CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
FII = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"

N_EXTRAS_TOPO = 100
N_BDR = 50
ESPECIE_ACAO = re.compile(r"^(ON|PN[A-H]?|UNT)\b")

# Nome curto escrito à mão quando o nome comercial da CVM não serve
# (sigla, grafia, nome antigo). Só nome, nunca adjetivo.
NOMES = {
    "PETR3": "Petrobras", "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú Unibanco", "ITUB3": "Itaú Unibanco",
    "BBAS3": "Banco do Brasil", "WEGE3": "WEG", "ABEV3": "Ambev", "B3SA3": "B3", "BBDC3": "Bradesco", "BBDC4": "Bradesco",
    "BBSE3": "BB Seguridade", "BPAC11": "BTG Pactual", "BRAP4": "Bradespar", "BRAV3": "Brava Energia",
    "CMIG4": "Cemig", "CPLE3": "Copel", "CSMG3": "Copasa", "CSAN3": "Cosan", "CPFE3": "CPFL Energia", "CMIN3": "CSN Mineração",
    "CSNA3": "CSN", "CXSE3": "Caixa Seguridade", "CEAB3": "C&A", "COGN3": "Cogna", "CURY3": "Cury", "CYRE3": "Cyrela",
    "DIRR3": "Direcional", "EMBJ3": "Embraer", "ENGI11": "Energisa", "ENEV3": "Eneva", "EGIE3": "Engie Brasil",
    "EQTL3": "Equatorial", "FLRY3": "Fleury", "GGBR4": "Gerdau", "GOAU4": "Metalúrgica Gerdau", "HAPV3": "Hapvida",
    "HYPE3": "Hypera", "IGTI11": "Iguatemi", "ISAE4": "ISA Energia", "ITSA4": "Itaúsa", "KLBN11": "Klabin",
    "RENT3": "Localiza", "LREN3": "Lojas Renner", "MGLU3": "Magazine Luiza", "POMO4": "Marcopolo", "MBRF3": "MBRF",
    "BEEF3": "Minerva", "MOTV3": "Motiva", "MRVE3": "MRV", "MULT3": "Multiplan", "NATU3": "Natura", "PSSA3": "Porto Seguro",
    "PRIO3": "PRIO", "RADL3": "Raia Drogasil", "RDOR3": "Rede D'Or", "RAIL3": "Rumo", "SBSP3": "Sabesp",
    "SANB11": "Santander Brasil", "SMFT3": "Smart Fit", "SUZB3": "Suzano", "TAEE11": "Taesa", "VIVT3": "Telefônica Brasil",
    "TEND3": "Tenda", "TIMS3": "TIM", "TOTS3": "Totvs", "UGPA3": "Ultrapar", "USIM5": "Usiminas", "VAMO3": "Vamos",
    "VBBR3": "Vibra Energia", "VIVA3": "Vivara", "YDUQ3": "Yduqs", "ALOS3": "Allos", "ASAI3": "Assaí", "AURE3": "Auren",
    "AXIA3": "Axia Energia", "AXIA7": "Axia Energia", "AZZA3": "Azzas 2154", "SAPR11": "Sanepar", "MOVI3": "Movida",
    "ECOR3": "EcoRodovias", "ORVR3": "Orizon", "JHSF3": "JHSF", "SLCE3": "SLC Agrícola", "GGPS3": "GPS",
    "SMTO3": "São Martinho", "CBAV3": "CBA", "IRBR3": "IRB(Re)", "MDNE3": "Moura Dubeux", "RECV3": "PetroReconcavo",
    "GMAT3": "Grupo Mateus", "CVCB3": "CVC", "SIMH3": "Simpar", "PLPL3": "Plano & Plano", "ALUP11": "Alupar",
    "BRSR6": "Banrisul",
    # BDRs: o nome comum da empresa; a razão social completa (B3) vai na página
    "AURA33": "Aura Minerals", "NVDC34": "Nvidia", "ROXO34": "Nu Holdings", "JBSS32": "JBS N.V.", "INBR32": "Inter&Co",
    "XPBR31": "XP Inc.", "TSLA34": "Tesla", "MELI34": "MercadoLibre", "MUTC34": "Micron Technology", "AMZO34": "Amazon",
    "M2ST34": "Strategy", "MSFT34": "Microsoft", "GOGL34": "Alphabet", "SPCX34": "SpaceX", "M1TA34": "Meta Platforms",
    "ITLC34": "Intel", "TSMC34": "TSMC", "AAPL34": "Apple", "A1MD34": "AMD", "ORCL34": "Oracle", "STOC34": "StoneCo",
    "NFLX34": "Netflix", "BABA34": "Alibaba", "P2LT34": "Palantir", "JPMC34": "JPMorgan Chase", "AVGO34": "Broadcom",
    "BERK34": "Berkshire Hathaway", "C2OI34": "Coinbase", "LILY34": "Eli Lilly", "M2RV34": "Marvell Technology",
    "W1DC34": "Western Digital", "GSGI34": "Goldman Sachs", "ASML34": "ASML", "D1EL34": "Dell Technologies",
    "COCA34": "Coca-Cola", "S1TX34": "Seagate", "EXXO34": "ExxonMobil", "FCXO34": "Freeport-McMoRan", "CHVX34": "Chevron",
    "QCOM34": "Qualcomm", "VISA34": "Visa", "S2GM34": "Sigma Lithium", "M1RN34": "Moderna", "MSCD34": "Mastercard",
    "PAGS34": "PagSeguro", "A1MT34": "Applied Materials", "DISB34": "Disney", "C2RW34": "CrowdStrike", "D1DG34": "Datadog",
    "BOAC34": "Bank of America",
    # FIIs cujo nome na CVM não diz a marca pela qual o fundo é conhecido
    "KFOF11": "Kinea Fundo de Fundos FII", "RCRB11": "Rio Bravo Renda Corporativa FII", "HFOF11": "Hedge Top FOFII 3 FII",
}


def baixar(url, nome=None, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        corpo = r.read()
    if nome:
        TMP.mkdir(exist_ok=True)
        (TMP / nome).write_bytes(corpo)
    return corpo


def b3_api(base, payload):
    p = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return json.loads(baixar(base + p, timeout=60).decode("utf-8"))


def carteira(indice):
    d = b3_api(B3_INDICE, {"language": "pt-br", "pageNumber": 1, "pageSize": 300, "index": indice, "segment": "1"})
    if d["page"]["totalPages"] != 1:
        raise SystemExit(f"PARADO: carteira do {indice} em mais de uma página")
    data = dt.datetime.strptime(d["header"]["date"], "%d/%m/%y").date().isoformat()
    cods = [r["cod"].strip() for r in d["results"]]
    if len(cods) < 50:
        raise SystemExit(f"PARADO: carteira do {indice} com só {len(cods)} ativos — resposta estranha da B3")
    return {"data": data, "fonte": PAGINA_INDICE[indice], "fonte_dados": "B3, GetPortfolioDay (carteira do dia)",
            "codigos": cods, "nomes_b3": {r["cod"].strip(): r["asset"].strip() for r in d["results"]}}


def volumes(ano):
    """Volume financeiro, dias com negócio, último ISIN e especificação por código,
    no mercado à vista, a partir do COTAHIST anual (já baixado em _tmp/)."""
    arqs = [TMP / f"COTAHIST_A{ano}.ZIP"] + sorted(TMP.glob(f"COTAHIST_D*{ano}.ZIP"))
    vol, dias, info, datas = collections.Counter(), collections.Counter(), {}, set()
    vistos = set()
    for arq in arqs:
        if not arq.exists():
            raise SystemExit(f"PARADO: falta {arq.name} em _tmp/ (rode atualiza.py historico {ano})")
        z = zipfile.ZipFile(arq)
        with z.open(z.namelist()[0]) as fh:
            for raw in fh:
                l = raw.decode("latin-1")
                if l[:2] != "01" or l[24:27] != "010":
                    continue
                cod, d = l[12:24].strip(), l[2:10]
                if (cod, d) in vistos:   # o diário repete o que o anual já tem
                    continue
                vistos.add((cod, d))
                datas.add(d)
                bdi = l[10:12]
                vol[(bdi, cod)] += int(l[170:188]) / 100
                dias[(bdi, cod)] += 1
                if cod not in info or info[cod]["data"] <= d:
                    info[cod] = {"data": d, "bdi": bdi, "especi": l[39:49].strip(), "isin": l[230:242], "nomres": l[27:39].strip()}
    return vol, dias, info, len(datas), max(datas)


def csv_cvm(txt):
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))


def titulo(s):
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    ps = s.strip().lower().split()
    return " ".join(p if (i and p in pequenas) else p[:1].upper() + p[1:] for i, p in enumerate(ps))


SIGLAS = {"af", "btg", "cri", "cdi", "ipca", "bb", "bc", "btgp", "hsi", "js", "xp", "vbi", "spx", "tg", "rbr", "rec", "whg", "gd",
          "fof", "ii", "iii", "brc", "ce", "re", "jpp", "sec"}
ACENTOS = {"logistica": "logística", "logistico": "logístico", "recebiveis": "recebíveis", "imobiliarios": "imobiliários",
           "imobiliaria": "imobiliária", "imobiliario": "imobiliário", "credito": "crédito", "indices": "índices",
           "precos": "preços", "patria": "pátria", "maua": "mauá", "multiestrategia": "multiestratégia"}


def nome_fii(razao, reserva):
    """Nome curto a partir da denominação da CVM: tira a forma jurídica, que é
    igual em todos (fundo de investimento imobiliário, responsabilidade limitada)."""
    n = " " + razao.upper() + " "
    for lixo in (r"FUNDO DE INVESTIMENTO IMOBILI[ÁA]RIO", r"FUNDO DE INV\.? IMOBILI[ÁA]RIO", r"FUNDO INVESTIMENTO IMOBILI[ÁA]RIO",
                 r"\bFI IMOBILI[ÁA]RIO\b", r"DE RESPONSABILIDADE LIMITADA", r"\bDE RESP\.? LTDA\b", r"RESPONSABILIDADE LIMITADA",
                 r"\bRESPONSABIL\b", r"\bRESP\.? LIMITADA\b", r"\bRL\b", r"\bFII\b", r"\bCETIPADO\b", r"CLASSE [ÚU]NICA"):
        n = re.sub(lixo, " ", n)
    n = re.sub(r"\s*[-–]\s*", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if not n:
        return titulo(reserva)
    ps = []
    for i, p in enumerate(n.lower().split()):
        p = ACENTOS.get(p, p)
        ps.append(p.upper() if p in SIGLAS else (p if (i and p in {"de", "da", "do", "das", "dos", "e"}) else p[:1].upper() + p[1:]))
    return " ".join(ps) + " FII"


def main():
    gravar = "--gravar" in sys.argv
    hoje = dt.date.today()
    ano = hoje.year
    antigo = {a["codigo"]: a for a in json.loads((SRC / "ativos.json").read_text(encoding="utf-8"))}

    print("carteiras da B3…")
    ibov, ifix = carteira("IBOV"), carteira("IFIX")
    print(f"  IBOV {ibov['data']}: {len(ibov['codigos'])} · IFIX {ifix['data']}: {len(ifix['codigos'])}")

    print(f"volumes de {ano} no COTAHIST…")
    vol, dias, info, n_pregoes, ult = volumes(ano)
    acoes_topo = [c for (b, c), v in vol.most_common() if b == "02"][:N_EXTRAS_TOPO]
    extras = [c for c in acoes_topo if c not in ibov["codigos"] and ESPECIE_ACAO.match(info[c]["especi"])
              and dias[("02", c)] == n_pregoes]
    bdrs = [c for (b, c), v in vol.most_common() if b in ("34", "35")][:N_BDR]

    print("CVM: FCA, cadastro, informe dos FIIs…")
    z = zipfile.ZipFile(io.BytesIO(baixar(FCA.format(ano=ano), f"fca{ano}.zip")))
    vm = csv_cvm(z.read(f"fca_cia_aberta_valor_mobiliario_{ano}.csv").decode("latin-1"))
    por_cod = {}
    for l in sorted(vm, key=lambda l: (l["Data_Referencia"], int(l["Versao"] or 0))):
        if l["Codigo_Negociacao"].strip() and not l["Data_Fim_Negociacao"].strip():
            por_cod[l["Codigo_Negociacao"].strip()] = l["CNPJ_Companhia"].strip()
    cad = {l["CNPJ_CIA"]: l for l in csv_cvm(baixar(CAD, "cad_cia_aberta.csv").decode("latin-1")) if l["SIT"].startswith("ATIVO")}
    zf = zipfile.ZipFile(io.BytesIO(baixar(FII.format(ano=ano), f"inf_fii_{ano}.zip")))
    geral = csv_cvm(zf.read(f"inf_mensal_fii_geral_{ano}.csv").decode("latin-1"))
    por_isin = {}
    for l in sorted(geral, key=lambda l: (l["Data_Referencia"], int(l["Versao"] or 0))):
        por_isin[l["Codigo_ISIN"].strip()] = l

    lista, problemas, sem_cadastro = [], [], []
    for c in ibov["codigos"] + extras:
        if c not in info or info[c]["bdi"] != "02":
            problemas.append(f"{c}: sem negócio em lote padrão no COTAHIST de {ano}")
            continue
        cnpj = por_cod.get(c)
        if not cnpj:
            # reserva: o cadastro de empresas listadas da B3 (mesmo CNPJ que a CVM usa)
            d = b3_api(B3_EMPRESA, {"language": "pt-br", "pageNumber": 1, "pageSize": 20, "company": c[:4]})
            hit = [r for r in d.get("results", []) if r["issuingCompany"].strip() == c[:4] and r.get("cnpj", "0") not in ("", "0")]
            if len(hit) == 1:
                x = hit[0]["cnpj"].zfill(14)
                cnpj = f"{x[:2]}.{x[2:5]}.{x[5:8]}/{x[8:12]}-{x[12:]}"
                print(f"  {c}: fora do FCA da CVM; CNPJ {cnpj} pelo cadastro da B3")
        if not cnpj or cnpj not in cad:
            problemas.append(f"{c}: código não achado no FCA da CVM nem com CNPJ ativo no cadastro da CVM")
            continue
        nome = antigo.get(c, {}).get("nome") or NOMES.get(c) or titulo(cad.get(cnpj, {}).get("DENOM_COMERC", info[c]["nomres"]))
        lista.append({"codigo": c, "tipo": "acao", "nome": nome, "cnpj": cnpj,
                      "indices": ["IBOV"] if c in ibov["codigos"] else []})
    for c in ifix["codigos"]:
        if c not in info or info[c]["bdi"] != "12":
            problemas.append(f"{c}: sem negócio como FII no COTAHIST de {ano}")
            continue
        g = por_isin.get(info[c]["isin"])
        if not g:
            # Sem ISIN igual no informe da CVM (campo vazio ou truncado lá): não se
            # adivinha o CNPJ pelo nome. A página sai com o texto mínimo.
            sem_cadastro.append(c)
            nome = antigo.get(c, {}).get("nome") or nome_fii(ifix["nomes_b3"].get(c, ""), info[c]["nomres"])
            lista.append({"codigo": c, "tipo": "fii", "nome": nome, "cnpj": None, "indices": ["IFIX"]})
            continue
        nome = antigo.get(c, {}).get("nome") or NOMES.get(c) or nome_fii(g["Nome_Fundo_Classe"], info[c]["nomres"])
        lista.append({"codigo": c, "tipo": "fii", "nome": nome, "cnpj": g["CNPJ_Fundo_Classe"].strip(), "indices": ["IFIX"]})
    for c in bdrs:
        emissor = c[:4]
        d = b3_api(B3_BDR, {"language": "pt-br", "pageNumber": 1, "pageSize": 20, "company": emissor})
        hit = [r for r in d.get("results", []) if r["issuingCompany"].strip() == emissor]
        if len(hit) != 1:
            problemas.append(f"{c}: B3 devolveu {len(hit)} empresa(s) BDR para {emissor}")
            continue
        r = hit[0]
        lista.append({"codigo": c, "tipo": "bdr", "nome": NOMES.get(c) or titulo(r["companyName"]),
                      "emissor": r["companyName"].strip(), "programa": r["typeBDR"].strip(),
                      "codigo_cvm": r["codeCVM"].strip(), "indices": []})

    if sem_cadastro:
        print(f"  {len(sem_cadastro)} FII(s) sem ISIN igual no informe da CVM (texto mínimo): {' '.join(sem_cadastro)}")
    for p in problemas:
        print("  ATENÇÃO:", p)
    tipos = collections.Counter(a["tipo"] for a in lista)
    novos = [a["codigo"] for a in lista if a["codigo"] not in antigo]
    saem = [c for c in antigo if c not in {a["codigo"] for a in lista}]
    print(f"  {len(lista)} ativos: {dict(tipos)} · novos {len(novos)} · saem {saem}")
    meta = {
        "_leia": "Gerado por _src/carteiras.py. Critérios mecânicos, sem juízo sobre os ativos.",
        "gerado_em": hoje.isoformat(),
        "IBOV": {k: v for k, v in ibov.items() if k != "nomes_b3"},
        "IFIX": {k: v for k, v in ifix.items() if k != "nomes_b3"},
        "acoes_extras": {"criterio": f"ações e units fora do Ibovespa entre as {N_EXTRAS_TOPO} de maior volume financeiro "
                                     f"em {ano} (COTAHIST, lote padrão, até {ult[:4]}-{ult[4:6]}-{ult[6:]}), "
                                     "especificação ON/PN/UNT, com negócio em todos os pregões do ano",
                         "codigos": extras},
        "BDR": {"criterio": f"os {N_BDR} BDRs (BDI 34 não patrocinado e 35 patrocinado) de maior volume financeiro em "
                            f"{ano} no COTAHIST, até {ult[:4]}-{ult[4:6]}-{ult[6:]}; BDR de ETF (BDI 36) fora",
                "fonte_empresa": "B3, GetCompaniesBDR (nome da empresa e tipo do programa)", "codigos": bdrs},
        "fiis_sem_isin_na_cvm": sem_cadastro,
        "problemas": problemas,
    }
    if problemas and "--aceitar-problemas" not in sys.argv:
        print("Há problemas acima; nada gravado. Confira e rode com --aceitar-problemas para gravar sem esses ativos.")
        if gravar:
            sys.exit(1)
    if gravar:
        (SRC / "ativos.json").write_text("[\n" + ",\n".join(" " + json.dumps(a, ensure_ascii=False) for a in lista) + "\n]\n", encoding="utf-8")
        (SRC / "carteiras.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("ok: _src/ativos.json e _src/carteiras.json gravados")
    else:
        for a in lista:
            print(f"  {a['codigo']:8} {a['tipo']:4} {a['nome']}")


if __name__ == "__main__":
    main()
