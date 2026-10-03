"""Leitor da série histórica de cotações da B3 (COTAHIST).

Layout oficial: "Layout do Arquivo de Cotações Históricas — COTAHIST.AAAA.TXT",
B3, revisão 02 de 05/10/2020:
https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf

Arquivos (mesmo layout):
    COTAHIST_DddmmAAAA.ZIP   um pregão
    COTAHIST_AAAAA.ZIP       um ano inteiro
em https://bvmf.bmfbovespa.com.br/InstDados/SerHist/

Registros de 245 bytes: 00 = header, 01 = cotação, 99 = trailer.
Preços vêm como inteiro com 2 casas implícitas, (11)V99.

Este leitor é PORTEIRO: se qualquer coisa do layout não bater (tamanho de
linha, header, trailer, contagem de registros, campo numérico com letra,
preço fora da faixa mínima–máxima, moeda que não é R$, fator de cotação que
não é 1), ele levanta LayoutInvalido e nada é gravado. Número errado
publicado é pior do que página desatualizada.
"""
import datetime as dt
import io
import re
import zipfile
from pathlib import Path

TAM = 245

# (nome, início, fim) — posições 1-based e inclusivas, como no PDF da B3.
CAMPOS_01 = [
    ("tipreg", 1, 2), ("data", 3, 10), ("codbdi", 11, 12), ("codneg", 13, 24),
    ("tpmerc", 25, 27), ("nomres", 28, 39), ("especi", 40, 49), ("prazot", 50, 52),
    ("modref", 53, 56), ("preabe", 57, 69), ("premax", 70, 82), ("premin", 83, 95),
    ("premed", 96, 108), ("preult", 109, 121), ("preofc", 122, 134), ("preofv", 135, 147),
    ("totneg", 148, 152), ("quatot", 153, 170), ("voltot", 171, 188), ("preexe", 189, 201),
    ("indopc", 202, 202), ("datven", 203, 210), ("fatcot", 211, 217), ("ptoexe", 218, 230),
    ("codisi", 231, 242), ("dismes", 243, 245),
]
NUMERICOS = {"data", "tpmerc", "preabe", "premax", "premin", "premed", "preult",
             "totneg", "quatot", "voltot", "fatcot"}
PRECOS = ("preabe", "premax", "premin", "premed", "preult")

# Tabela anexa do layout: CODBDI 02 = lote padrão (ações), 12 = fundos
# imobiliários; TPMERC 010 = mercado à vista.
BDI_ACEITOS = {"02", "12"}
MERCADO_VISTA = "010"


class LayoutInvalido(Exception):
    pass


def _campo(linha, ini, fim):
    return linha[ini - 1:fim]


def _num(s, nome, n_linha):
    s = s.strip()
    if not s or not s.isdigit():
        raise LayoutInvalido(f"linha {n_linha}: campo {nome} não é numérico: {s!r}")
    return int(s)


def ler_bytes(dados_txt, nome="(arquivo)"):
    """Lê o conteúdo de um COTAHIST.TXT. Devolve (meta, registros), onde
    registros é a lista de dicts de TODAS as linhas 01, com preços em reais."""
    txt = dados_txt.decode("latin-1")
    linhas = txt.replace("\r\n", "\n").split("\n")
    while linhas and linhas[-1] == "":
        linhas.pop()
    if len(linhas) < 2:
        raise LayoutInvalido(f"{nome}: arquivo vazio ou sem trailer")
    for i, l in enumerate(linhas, 1):
        if len(l) != TAM:
            raise LayoutInvalido(f"{nome}: linha {i} com {len(l)} caracteres, o layout diz {TAM}")

    h, t = linhas[0], linhas[-1]
    if not re.fullmatch(r"00COTAHIST\.\d{4}BOVESPA \d{8}", h[:31]):
        raise LayoutInvalido(f"{nome}: header fora do layout: {h[:31]!r}")
    if not re.fullmatch(r"99COTAHIST\.\d{4}BOVESPA \d{8}\d{11}", t[:42]):
        raise LayoutInvalido(f"{nome}: trailer fora do layout: {t[:42]!r}")
    total = int(t[31:42])
    # O PDF manda contar header e trailer no total. Os arquivos reais (diários
    # e anuais, conferidos em 03/10/2026) contam só os registros 01. Aceita
    # as duas leituras; qualquer outro número é arquivo truncado.
    if total not in (len(linhas), len(linhas) - 2):
        raise LayoutInvalido(f"{nome}: trailer diz {total} registros, o arquivo tem {len(linhas)} linhas")
    meta = {"ano": int(h[11:15]), "gerado": dt.datetime.strptime(h[23:31], "%Y%m%d").date()}

    regs = []
    for i, l in enumerate(linhas[1:-1], 2):
        if l[:2] != "01":
            raise LayoutInvalido(f"{nome}: linha {i} com tipo de registro {l[:2]!r} no meio do arquivo")
        regs.append((i, l))
    return meta, regs


def interpretar(n_linha, l):
    """Converte uma linha 01 em dict, conferindo o que o layout garante."""
    r = {}
    for nome, ini, fim in CAMPOS_01:
        v = _campo(l, ini, fim)
        r[nome] = _num(v, nome, n_linha) if nome in NUMERICOS else v.strip()
    r["data"] = dt.datetime.strptime(str(r["data"]), "%Y%m%d").date()
    for p in PRECOS:
        r[p] = r[p] / 100
    r["voltot"] = r["voltot"] / 100
    if r["modref"] != "R$":
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): moeda {r['modref']!r}, esperado R$")
    if r["fatcot"] != 1:
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): fator de cotação {r['fatcot']}, esperado 1")
    if not re.fullmatch(r"BR[A-Z0-9]{10}", r["codisi"]):
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): ISIN fora do padrão {r['codisi']!r}")
    mn, mx = r["premin"], r["premax"]
    if not (0 < mn <= mx):
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): mínima {mn} / máxima {mx} incoerentes")
    for p in ("preabe", "premed", "preult"):
        if not (mn - 0.005 <= r[p] <= mx + 0.005):
            raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): {p}={r[p]} fora de [{mn}, {mx}]")
    if r["totneg"] <= 0 or r["quatot"] <= 0 or r["voltot"] <= 0:
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): negócios/quantidade/volume zerados")
    # volume ≈ quantidade × preço médio (tolerância larga, 30%: papel ilíquido diverge até ~15%; layout deslocado erra por ordens de grandeza)
    est = r["quatot"] * r["premed"]
    if abs(est - r["voltot"]) > max(0.30 * r["voltot"], 1.0):
        raise LayoutInvalido(f"linha {n_linha} ({r['codneg']}): volume {r['voltot']} não bate com "
                             f"quantidade × preço médio ({est:.2f}) — layout deslocado?")
    return r


def abrir(caminho):
    """Aceita .ZIP (como a B3 publica) ou .TXT."""
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".zip":
        with zipfile.ZipFile(caminho) as z:
            nomes = [n for n in z.namelist() if n.upper().endswith(".TXT")]
            if len(nomes) != 1:
                raise LayoutInvalido(f"{caminho.name}: esperado 1 .TXT dentro do ZIP, há {nomes}")
            return ler_bytes(z.read(nomes[0]), caminho.name)
    return ler_bytes(caminho.read_bytes(), caminho.name)


def cotacoes(caminho, codigos):
    """Linhas do mercado à vista (lote padrão ou FII) dos códigos pedidos.
    Devolve {codigo: [registro, ...]} em ordem de data. Só interpreta as
    linhas que interessam, mas a estrutura do arquivo inteiro é conferida."""
    meta, regs = abrir(caminho)
    alvo = set(codigos)
    saida = {c: [] for c in codigos}
    for n, l in regs:
        cod = l[12:24].strip()
        if cod not in alvo:
            continue
        if l[10:12] not in BDI_ACEITOS or l[24:27] != MERCADO_VISTA:
            continue
        r = interpretar(n, l)
        if r["data"].year != meta["ano"]:
            raise LayoutInvalido(f"{Path(caminho).name}: pregão {r['data']} fora do ano {meta['ano']} do header")
        saida[cod].append(r)
    for c in saida:
        saida[c].sort(key=lambda r: r["data"])
        datas = [r["data"] for r in saida[c]]
        if len(datas) != len(set(datas)):
            raise LayoutInvalido(f"{Path(caminho).name}: {c} com mais de uma linha no mesmo pregão")
    return meta, saida
