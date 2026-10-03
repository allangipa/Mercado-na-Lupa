"""Páginas de dados abertos do Mercado na Lupa: indicadores do Banco Central,
Tesouro Direto e glossário. Usado por _src/build.py (que injeta a si mesmo em B).

Lê dados/bcb.json (_src/bcb.py), dados/tesouro.json (_src/tesouro.py) e
_src/glossario.json. Nenhum número é escrito à mão: tudo sai dos arquivos, com a
data de referência de cada um. O build PARA se faltar um arquivo ou uma série
essencial; uma série que falhou na última coleta aparece com aviso (falha isolada).
"""
import datetime as dt
import json
import math
import re

B = None  # módulo build, injetado em build.main()

SGS_URL = "https://www3.bcb.gov.br/sgspub/localizarseries/localizarSeries.do?method=prepararTelaLocalizarSeries"
PORTAL = "https://dadosabertos.bcb.gov.br/dataset/"
# conjunto no portal de dados abertos do BC (licença ODbL), quando a série está lá
PORTAL_SERIE = {432: "432-taxa-de-juros---meta-selic-definida-pelo-copom", 11: "11-taxa-de-juros---selic",
                1178: "1178-taxa-de-juros---selic-anualizada-base-252",
                195: "195-depositos-de-poupanca-a-partir-de-04052012---rentabilidade-no-periodo"}
PTAX_PORTAL = {"dolar": "dolar-americano-usd-todos-os-boletins-diarios", "euro": "taxas-de-cambio-todos-os-boletins-diarios"}
ESSENCIAIS = ("selic_meta", "selic", "selic_ano", "cdi", "cdi_ano", "ipca", "ipca12", "poupanca", "tr", "dolar", "euro")  # avisos do hub

# Regras com data — aparecem nas páginas e nos simuladores. Conferidas em fonte oficial.
CONFERIDO = "2026-10-03"
LEI_POUPANCA = "https://www.planalto.gov.br/ccivil_03/leis/l8177.htm"
LEI_11033 = "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2004/lei/l11033.htm"
DEC_IOF = "https://www.planalto.gov.br/ccivil_03/_ato2007-2010/2007/decreto/d6306.htm"
B3_TARIFAS_TD = "https://www.b3.com.br/pt_br/produtos-e-servicos/tarifas/tarifas-de-tesouro-direto/"
RES_CMN_5215 = "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20CMN&numero=5215"
ADC_MP1303 = "https://www.planalto.gov.br/ccivil_03/_Ato2023-2026/2025/Congresso/adc-67-mpv1.303.htm"
CIRC_PTAX = "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Circular&numero=3506"
COPOM_URL = "https://www.bcb.gov.br/controleinflacao/copom"
IBGE_IPCA = "https://www.ibge.gov.br/estatisticas/economicas/precos-e-custos/9256-indice-nacional-de-precos-ao-consumidor-amplo.html"
TD_ABERTO = "https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto"
ODBL = "https://opendatacommons.org/licenses/odbl/1-0/"


def e(s):
    return B.e(s)


def pct(v, casas=2):
    return B.br(v, casas) + "%"


def dlong(d):
    return B.data_longa(d)


def dbr(d):
    return B.data_br(d)


# --- carga ---------------------------------------------------------------------------

class Inconsistente(Exception):
    """Dado de uma série que não passou na conferência. Não para o build: a série volta
    para o último dado bom (dados/*-bom.json) e aparece como "com problema" no status.
    O build só para se não houver dado bom anterior."""


# grupo -> (séries que ele usa, séries que ele publica e que voltam juntas ao dado bom)
GRUPOS = {
    "meta": (("selic_meta",), ("selic_meta",)),
    "selic": (("selic", "selic_ano"), ("selic", "selic_ano")),
    "cdi": (("cdi", "cdi_ano"), ("cdi", "cdi_ano")),
    "ipca": (("ipca", "ipca12"), ("ipca", "ipca12")),
    "poup": (("poupanca", "tr", "selic_meta"), ("poupanca", "tr")),
    "dolar": (("dolar",), ("dolar",)),
    "euro": (("euro",), ("euro",)),
}
BOM_BCB = "bcb-bom.json"
BOM_TD = "tesouro-bom.json"


def _calc_grupo(g, S):
    try:
        for k in GRUPOS[g][0]:
            if not S.get(k, {}).get("pontos"):
                raise Inconsistente(f"série {k} vazia ou ausente")
        return CALC[g](S)
    except Inconsistente:
        raise
    except Exception as ex:  # noqa: BLE001 — dado estranho vira inconsistência da série, não erro do build
        raise Inconsistente(f"{type(ex).__name__}: {ex}") from ex


def _grava_json(arq, obj):
    corpo = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    arq.write_text(corpo.replace("],[", "],\n[") + "\n", encoding="utf-8")


def carregar():
    arq = B.DADOS / "bcb.json"
    bcb = B.ler_json(arq) if arq.exists() else {"coletado_em": dt.datetime.now(dt.timezone.utc).isoformat(), "series": {}}
    S = bcb.setdefault("series", {})
    arq_bom = B.DADOS / BOM_BCB
    Sb = B.ler_json(arq_bom)["series"] if arq_bom.exists() else {}
    I, problemas, novo_bom = {}, {}, dict(Sb)
    for g, (usa, publica) in GRUPOS.items():
        try:
            I[g] = _calc_grupo(g, S)
            for k in publica:
                novo_bom[k] = S[k]
        except Inconsistente as ex:
            msg = str(ex)[:300]
            try:
                I[g] = _calc_grupo(g, {**S, **{k: Sb[k] for k in usa if k in Sb}})
            except Inconsistente as ex2:
                B.falha(f"indicadores, grupo {g}: {msg} — e não há dado bom anterior em dados/{BOM_BCB} ({ex2})")
            for k in publica:
                S[k] = {**Sb[k], "problema": msg}
            problemas[g] = msg
            print(f"ATENÇÃO (dados do BC): {g} inconsistente — {msg}. Publicado o último dado bom.")
    if novo_bom != Sb:
        _grava_json(arq_bom, {"_leia": "Último dado do BC que passou nas conferências do build (_src/paginas_dados.py). "
                                       "Usado quando a coleta nova vem inconsistente.", "series": novo_bom})
    td = carregar_tesouro()
    glo = B.ler_json(B.SRC / "glossario.json") if (B.SRC / "glossario.json").exists() else None
    return {"bcb": bcb, "S": S, "td": td, "glo": glo, "I": I, "problemas": problemas}


def conferir_tesouro(td):
    try:
        tit = td.get("titulos") or []
        if len(tit) < 10:
            raise Inconsistente(f"só {len(tit)} títulos")
        dt.date.fromisoformat(td["data_base"])
        for t in tit:
            dt.date.fromisoformat(t["vencimento"])
            for k in ("taxa_compra", "taxa_venda"):
                if t[k] is not None and not -5 < t[k] < 40:
                    raise Inconsistente(f"{t['tipo']} {t['vencimento']}: {k} fora de faixa ({t[k]})")
            for k in ("pu_compra", "pu_venda"):
                if t[k] is not None and not 0 < t[k] < 1e6:
                    raise Inconsistente(f"{t['tipo']} {t['vencimento']}: {k} fora de faixa ({t[k]})")
        if not isinstance(td.get("historico"), dict):
            raise Inconsistente("sem histórico")
    except Inconsistente:
        raise
    except Exception as ex:  # noqa: BLE001
        raise Inconsistente(f"{type(ex).__name__}: {ex}") from ex


def carregar_tesouro():
    arq, arq_bom = B.DADOS / "tesouro.json", B.DADOS / BOM_TD
    td = B.ler_json(arq) if arq.exists() else {}
    try:
        conferir_tesouro(td)
        if not arq_bom.exists() or B.ler_json(arq_bom) != td:
            _grava_json(arq_bom, td)
        return td
    except Inconsistente as ex:
        msg = str(ex)[:300]
        if not arq_bom.exists():
            B.falha(f"Tesouro: {msg} — e não há dado bom anterior em dados/{BOM_TD}")
        bom = B.ler_json(arq_bom)
        conferir_tesouro(bom)
        print(f"ATENÇÃO (Tesouro): {msg}. Publicado o último dado bom (data-base {bom['data_base']}).")
        return {**bom, "problema": msg}


def ult(S, k):
    p = S[k]["pontos"][-1]
    return p[0], p[1]


def acumula(pts, ini, fim):
    """Fator acumulado de taxas diárias (% ao dia) com ini <= data <= fim."""
    f, n = 1.0, 0
    for d, v, *_ in pts:
        if ini <= d <= fim:
            f *= 1 + v / 100
            n += 1
    return f, n


def menos_um_ano(d):
    d = dt.date.fromisoformat(d)
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:
        return d.replace(year=d.year - 1, day=28).isoformat()


def diaria(S, k, kano):
    pts = S[k]["pontos"]
    d, v = pts[-1][0], pts[-1][1]
    ini12 = (dt.date.fromisoformat(menos_um_ano(d)) + dt.timedelta(days=1)).isoformat()
    f12, n12 = acumula(pts, ini12, d)
    fano, nano = acumula(pts, d[:4] + "-01-01", d)
    fmes, nmes = acumula(pts, d[:7] + "-01", d)
    da, va = S[kano]["pontos"][-1][0], S[kano]["pontos"][-1][1]
    if da != d:
        raise Inconsistente(f"bcb.json: {k} e {kano} com datas diferentes ({d} × {da})")
    # mesmo valor anualizado: (1 + diária)^252
    if abs(((1 + v / 100) ** 252 - 1) * 100 - va) > 0.02:
        raise Inconsistente(f"bcb.json: {k} diária {v} não bate com a anualizada {va}")
    primeiro12 = next(p[0] for p in pts if p[0] >= ini12)
    return {"data": d, "dia": v, "ano": va, "acum12": (f12 - 1) * 100, "dias12": n12, "ini12": primeiro12,
            "acum_ano": (fano - 1) * 100, "dias_ano": nano, "acum_mes": (fmes - 1) * 100, "dias_mes": nmes,
            "serie_ano": [(p[0], p[1]) for p in S[kano]["pontos"]]}


def c_meta(S):
    pts = S["selic_meta"]["pontos"]
    d, v = pts[-1][0], pts[-1][1]
    desde = d
    for p in reversed(pts):
        if p[1] != v:
            break
        desde = p[0]
    mudancas = []
    ant = None
    for p in pts:
        if p[1] != ant:
            mudancas.append((p[0], p[1]))
            ant = p[1]
    if not 0 < v < 50:
        raise Inconsistente(f"meta Selic fora de faixa ({v})")
    return {"data": d, "valor": v, "desde": desde, "mudancas": mudancas}


def c_ipca(S):
    ip = S["ipca"]["pontos"]
    ip12 = S["ipca12"]["pontos"]
    if ip[-1][0] != ip12[-1][0]:
        raise Inconsistente(f"bcb.json: IPCA mensal ({ip[-1][0]}) e acumulado 12M ({ip12[-1][0]}) com meses diferentes")
    ref = ip[-1][0]
    fa = 1.0
    for dd, vv in ip:
        if dd[:4] == ref[:4] and dd <= ref:
            fa *= 1 + vv / 100
    # confere o 12M do SGS com o produto dos 12 meses
    f12 = 1.0
    ult12 = [p for p in ip if p[0] <= ref][-12:]
    for _, vv in ult12:
        f12 *= 1 + vv / 100
    if abs((f12 - 1) * 100 - ip12[-1][1]) > 0.02:
        raise Inconsistente(f"bcb.json: IPCA 12M do SGS ({ip12[-1][1]}) não bate com o produto dos 12 meses ({(f12 - 1) * 100:.4f})")
    return {"ref": ref, "mes": ip[-1][1], "doze": ip12[-1][1], "ano": (fa - 1) * 100, "mensal": ip, "serie12": ip12}


def c_poup(S):
    pts = S["selic_meta"]["pontos"]
    pp = S["poupanca"]["pontos"]
    ult_p = pp[-1]
    dia1 = [p for p in pp if p[0].endswith("-01")]
    dia1 = sorted({p[0]: p for p in dia1}.values())
    ult12 = dia1[-12:]
    f = 1.0
    for p in ult12:
        f *= 1 + p[1] / 100
    tr = S["tr"]["pontos"]
    tr1 = sorted({p[0]: p for p in tr if p[0].endswith("-01")}.values())
    meta_no_inicio = valor_em(pts, ult_p[0])
    regra_05 = meta_no_inicio > 8.5
    tr_ult = [p for p in tr if p[0] == ult_p[0]]
    tr_v = tr_ult[-1][1] if tr_ult else tr1[-1][1]
    if regra_05:
        esperado = ((1.005) * (1 + tr_v / 100) - 1) * 100
    else:
        esperado = ((1 + 0.7 * ((1 + meta_no_inicio / 100) ** (1 / 12) - 1)) * (1 + tr_v / 100) - 1) * 100
    if abs(esperado - ult_p[1]) > 0.0002 * 100:
        raise Inconsistente(f"poupança de {ult_p[0]}: SGS diz {ult_p[1]}%, a regra legal com TR {tr_v}% e meta {meta_no_inicio}% dá {esperado:.4f}%")
    return {"ini": ult_p[0], "fim": ult_p[2], "valor": ult_p[1], "acum12": (f - 1) * 100, "ini12": ult12[0][0],
                 "fim12": ult12[-1][2], "regra_05": regra_05, "meta": meta_no_inicio, "tr": tr_v, "tr_ini": ult_p[0],
                 "dia1": dia1, "tr1": tr1}


def c_moeda(S, k):
    if True:
        pt = S[k]["pontos"]
        d, c, vd = pt[-1]
        ant = pt[-2]
        d12 = menos_um_ano(d)
        base12 = [p for p in pt if p[0] <= d12]
        base12 = base12[-1] if base12 else pt[0]
        janela = [p for p in pt if p[0] > d12]
        mx = max(janela, key=lambda p: p[2])
        mn = min(janela, key=lambda p: p[2])
        ini_ano = [p for p in pt if p[0] < d[:4] + "-01-01"]
        if not 1 < vd < 20 or c > vd or abs(vd / ant[2] - 1) > 0.15:
            raise Inconsistente(f"{k}: PTAX estranha (compra {c}, venda {vd}, anterior {ant[2]})")
        return {"data": d, "compra": c, "venda": vd, "ant": ant, "var_dia": (vd / ant[2] - 1) * 100,
                "var12": (vd / base12[2] - 1) * 100, "base12": base12, "max": mx, "min": mn,
                "var_ano": (vd / ini_ano[-1][2] - 1) * 100 if ini_ano else None,
                "base_ano": ini_ano[-1] if ini_ano else None, "pontos": pt}


CALC = {"meta": c_meta, "selic": lambda S: diaria(S, "selic", "selic_ano"), "cdi": lambda S: diaria(S, "cdi", "cdi_ano"),
        "ipca": c_ipca, "poup": c_poup, "dolar": lambda S: c_moeda(S, "dolar"), "euro": lambda S: c_moeda(S, "euro")}


def valor_em(pts, data):
    v = None
    for p in pts:
        if p[0] <= data:
            v = p[1]
        else:
            break
    return v


# --- gráfico SVG (estático, gerado no build) ----------------------------------------

def svg_serie(pontos, tid, titulo, casas=2, sufixo="", degrau=False, rotulo_x="ano"):
    """pontos: [(data_iso, valor)]. Linha com área, grade e rótulos; degrau=True para taxas que mudam por decisão."""
    W, H, x0, x1, y0, y1 = 720, 330, 86, 708, 16, 282
    vals = [v for _, v in pontos]
    lo, hi = min(vals), max(vals)
    p = B.passo_bonito(hi - lo if hi > lo else abs(hi) or 1)
    ymin = math.floor(lo / p) * p
    ymax = math.ceil(hi / p) * p
    if ymax == ymin:
        ymax = ymin + p
    t0 = dt.date.fromisoformat(pontos[0][0]).toordinal()
    t1 = dt.date.fromisoformat(pontos[-1][0]).toordinal()
    X = lambda d: x0 + (x1 - x0) * ((dt.date.fromisoformat(d).toordinal() - t0) / ((t1 - t0) or 1))
    Y = lambda v: y1 - (y1 - y0) * (v - ymin) / (ymax - ymin)
    coords = []
    for i, (d, v) in enumerate(pontos):
        if degrau and i:
            coords.append((X(d), Y(pontos[i - 1][1])))
        coords.append((X(d), Y(v)))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"M{coords[0][0]:.1f},{y1} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords) + f" L{coords[-1][0]:.1f},{y1} Z"
    grade = []
    v = ymin
    cg = 2 if p < 0.1 or abs(p * 10 - round(p * 10)) > 1e-9 else (1 if p < 1 or p != int(p) else 0)
    while v <= ymax + 1e-9:
        y = Y(v)
        grade.append(f'<line class="grade-y" x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text x="{x0 - 10}" y="{y + 7:.1f}" text-anchor="end">{B.br(v, cg)}{sufixo}</text>')
        v += p
    xs = []
    a0, a1 = int(pontos[0][0][:4]), int(pontos[-1][0][:4])
    if rotulo_x == "ano" and a1 - a0 >= 2:
        for a in range(a0 + 1, a1 + 1):
            d = f"{a}-01-01"
            xs.append((X(d), str(a)))
    else:
        d0 = dt.date.fromisoformat(pontos[0][0])
        meses = (a1 - a0) * 12 + int(pontos[-1][0][5:7]) - d0.month
        passo = 3 if meses > 15 else (2 if meses > 8 else 1)
        m = d0.replace(day=1)
        k = 0
        while m.isoformat() <= pontos[-1][0]:
            if m.isoformat() > pontos[0][0] and k % passo == 0:
                xs.append((X(m.isoformat()), B.MESES[m.month - 1] + "/" + str(m.year)[2:]))
            m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            k += 1
    eixo = "".join(f'<text x="{x:.1f}" y="{H - 14}" text-anchor="middle">{e(t)}</text>' for x, t in xs if x0 + 20 < x < x1 - 10)
    marca = f'<circle class="ponto" cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="6"/>'
    return (f'<svg class="unico" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{tid}">'
            f'<title id="{tid}">{e(titulo)}</title>{"".join(grade)}<path class="area" d="{area}"/>'
            f'<polyline class="linha" points="{pts}"/>{marca}{eixo}</svg>')


def grafico(svg, legenda):
    return f'<figure class="grafico">{svg}<figcaption class="legenda">{legenda}</figcaption></figure>'


# --- peças -------------------------------------------------------------------------

def selo_ref(texto):
    return f'<p class="selo-dados" data-estado="neutro"><span class="selo-ponto" aria-hidden="true">i</span><span class="selo-txt">{texto}</span></p>'


def fonte_sgs(S, k):
    s = S[k]
    n = s["sgs"]
    if n == "PTAX":
        return (f'<a href="{PORTAL}{PTAX_PORTAL[k]}" rel="noopener">Banco Central do Brasil — PTAX, boletins diários '
                f'(API Olinda, dados abertos, licença ODbL)</a>')
    if n in PORTAL_SERIE:
        return (f'<a href="{PORTAL}{PORTAL_SERIE[n]}" rel="noopener">Banco Central do Brasil — SGS, série {n}: '
                f'{e(s["nome"])} (portal de dados abertos, licença ODbL)</a>')
    return (f'<a href="{SGS_URL}" rel="noopener">Banco Central do Brasil — SGS, série {n}: {e(s["nome"])}</a>')


def aviso_falha(S, ks):
    prob = [k for k in ks if S[k].get("problema")]
    ruins = [k for k in ks if not S[k].get("ok", True) and k not in prob]
    txt = ""
    if prob:
        txt = ('<div class="aviso"><strong>Dado novo com problema</strong> em '
               + ", ".join(e(S[k]["nome"]) for k in prob)
               + ': a coleta mais recente não passou na conferência do site e não foi publicada. Os números abaixo são o '
                 'último dado conferido, com a data de referência dele. Detalhes na <a href="{base}status.html">página de status</a>.</div>')
    if not ruins:
        return txt
    return ('<div class="aviso"><strong>A última coleta no Banco Central falhou</strong> para '
            + ", ".join(e(S[k]["nome"]) for k in ruins)
            + '. Os números abaixo são da coleta anterior; a data de referência de cada um continua valendo. '
              'Detalhes na <a href="' + "{base}" + 'status.html">página de status</a>.</div>') + txt


def coletado(bcb):
    t = dt.datetime.fromisoformat(bcb["coletado_em"]).astimezone(B.BRASILIA)
    return t.strftime("%d/%m/%Y às %H:%M")


def numeros(itens):
    return '<dl class="numeros">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in itens) + "</dl>"


def pagina(D, rel, titulo, desc, h1, lead, corpo, migalha, og_url, ld_extra=None, foto="paulista-dia", atual="indicadores",
           js=""):
    base = "../" if "/" in rel else ""
    url = f"{B.DOMINIO}/{rel}"
    trilha = [(migalha[0], base + migalha[1])] if migalha else []
    cab = f"""{B.migalhas_html(base, *trilha, (h1, ""))}
<h1>{e(h1)}</h1>
<p class="lead">{lead}</p>
"""
    html_corpo = f"""<main id="conteudo" class="com-faixa">
{B.faixa(foto, base, cab)}<div class="casca">
{corpo.replace("{base}", base)}
<div class="aviso"><strong>{B.AVISO_FIXO}</strong> Os indicadores são reproduzidos das fontes oficiais citadas, com a data de referência de cada número.</div>
</div></main>
"""
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": titulo, "description": desc, "url": url,
           "inLanguage": "pt-BR", "dateModified": D["modificado"], "publisher": B.ORG}]
    if ld_extra:
        ld += ld_extra
    itens = [(B.NOME, B.DOMINIO + "/")] + ([(migalha[0], f"{B.DOMINIO}/{migalha[1]}")] if migalha else []) + [(h1, url)]
    ld.append(B.migalhas_ld(*itens))
    return (B.cabeca(titulo, desc, url, og_url, base, ld, extra=B.fundo_preload(foto, base))
            + B.topo(base, atual) + html_corpo + B.rodape(base) + B.consentimento(base) + B.fim(js))


def dataset_ld(nome, desc, url, fonte_url, data, licenca=ODBL, publicador="Banco Central do Brasil"):
    return {"@context": "https://schema.org", "@type": "Dataset", "name": nome, "description": desc, "url": url,
            "isBasedOn": fonte_url, "license": licenca, "temporalCoverage": data, "inLanguage": "pt-BR",
            "creator": {"@type": "GovernmentOrganization", "name": publicador}}


def fontes_html(itens):
    return '<h2 id="fontes">Fontes</h2><ul class="fontes">' + "".join(f"<li>{i}</li>" for i in itens) + "</ul>"


def links_rel(itens, base):
    return ('<h2 id="veja-tambem">Veja também</h2><ul class="cartoes grade grade-3">' + "".join(
        f'<li><a class="cartao" href="{base}{h}"><span class="rotulo">{e(r)}</span><h3>{e(t)}</h3>{B.SETA}</a></li>'
        for h, r, t in itens) + "</ul>")


def tabela(cab, linhas, caption):
    th = "".join(f'<th{" class=\"n\"" if i else ""}>{c}</th>' for i, c in enumerate(cab))
    tr = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' for c in l) + "</tr>" for l in linhas)
    return f'<div class="rolagem"><table><caption>{caption}</caption><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


# --- as páginas de indicador -----------------------------------------------------------

def p_selic(D, og):
    S, I = D["S"], D["I"]
    m, s = I["meta"], I["selic"]
    corte = (dt.date.fromisoformat(m["data"]) - dt.timedelta(days=365 * 5)).isoformat()
    serie = [(d, v) for d, v in m["mudancas"] if d >= corte]
    antes = [x for x in m["mudancas"] if x[0] < corte]
    if antes:
        serie = [(corte, antes[-1][1])] + serie
    serie.append((m["data"], m["valor"]))
    svg = svg_serie(serie, "g-selic", f"Meta Selic de {dbr(serie[0][0])} a {dbr(m['data'])}, em % ao ano.", 2, "%", degrau=True)
    mud = list(reversed(m["mudancas"]))[:10]
    linhas = [[dbr(d), pct(v)] for d, v in mud]
    nums = numeros([("Meta Selic", pct(m["valor"])), ("Em vigor desde", dbr(m["desde"])),
                    ("Selic over (a.a.)", pct(s["ano"])), ("Selic over do dia", pct(s["dia"], 6)),
                    ("Acumulada em 12 meses", pct(s["acum12"])), (f"Acumulada em {s['data'][:4]}", pct(s["acum_ano"])),
                    ("Referência da over", dbr(s["data"])), ("Dias úteis em 12 meses", str(s["dias12"]))])
    corpo = f"""{aviso_falha(S, ["selic_meta", "selic", "selic_ano"])}
{selo_ref(f"Meta de {dbr(m['data'])} · Selic over de {dbr(s['data'])} · coletado em {coletado(D['bcb'])}")}
{nums}
<h2 id="grafico">A meta Selic nos últimos cinco anos</h2>
{grafico(svg, "Meta para a taxa Selic definida pelo Copom, em % ao ano, a partir do dia em que passou a valer. Fonte: Banco Central do Brasil, SGS 432.")}
<div class="texto">
<h2 id="o-que-e">O que é a Selic</h2>
<p>A Selic é a taxa básica de juros da economia brasileira. Há duas Selic, e é comum confundir:</p>
<ul>
 <li><strong>Meta Selic</strong> — o número anunciado pelo Comitê de Política Monetária (<a href="{{base}}glossario.html#copom">Copom</a>) do Banco Central, que se reúne oito vezes por ano. É o instrumento da política monetária para levar a inflação à meta. Hoje: <span class="num">{pct(m['valor'])}</span> ao ano, desde {dlong(m['desde'])}.</li>
 <li><strong>Selic over (ou efetiva)</strong> — a taxa média das operações de um dia lastreadas em títulos públicos, registradas no sistema Selic. É calculada todo dia útil e fica muito perto da meta, um pouco abaixo. Em {dbr(s['data'])}: <span class="num">{pct(s['ano'])}</span> ao ano, ou <span class="num">{pct(s['dia'], 6)}</span> naquele dia.</li>
</ul>
<p>É a Selic over que corrige o <a href="{{base}}tesouro-direto.html">Tesouro Selic</a> e que serve de referência para a correção de tributos pagos em atraso. A meta é a que aparece no noticiário e decide a regra da <a href="{{base}}indicadores/rendimento-da-poupanca.html">poupança</a>: com a meta acima de 8,5% ao ano, a poupança rende 0,5% ao mês mais a TR.</p>

<h2 id="acumulada">Selic acumulada</h2>
<p>A Selic over acumulada em 12 meses — de {dbr(s['ini12'])} a {dbr(s['data'])}, {s['dias12']} dias úteis — foi de <span class="num">{pct(s['acum12'])}</span>. No ano de {s['data'][:4]}, até {dbr(s['data'])}, <span class="num">{pct(s['acum_ano'])}</span>. A conta multiplica a taxa de cada dia útil:</p>
<div class="formula">acumulada = (1 + t<sub>1</sub>) × (1 + t<sub>2</sub>) × … × (1 + t<sub>n</sub>) − 1</div>
<p>É a mesma convenção da Calculadora do Cidadão do Banco Central: a taxa de um dia rende daquele dia até o dia útil seguinte. Conferido em {dbr(CONFERIDO)}: de 01/10/2025 a 01/10/2026, a conta deste site e a calculadora do BC dão o mesmo fator, 1,14474060.</p>
<p>A relação entre a taxa do dia e a anualizada usa 252 dias úteis por ano: <span class="num">(1 + {B.br(s['dia'], 6)}%)<sup>252</sup> − 1 = {pct(s['ano'])}</span>.</p>

<h2 id="decisoes">Últimas mudanças da meta</h2>
<p>A tabela mostra o dia em que cada nova meta passou a valer, segundo a série 432 do Banco Central (em geral, o dia seguinte ao anúncio do Copom).</p>
</div>
{tabela(["Em vigor desde", "Meta Selic (a.a.)"], linhas, "Mudanças da meta Selic")}
<div class="texto">
<h2 id="investimentos">O que muda nos investimentos</h2>
<p>Títulos pós-fixados acompanham os juros do dia a dia: o Tesouro Selic pela Selic over, e CDBs, LCIs e LCAs pós-fixados pelo <a href="{{base}}indicadores/cdi-hoje.html">CDI</a>, que anda colado nela. Quando a meta sobe, o rendimento desses títulos sobe junto, aos poucos, dia após dia. Títulos prefixados e atrelados ao IPCA já negociados reagem de outro jeito: o preço deles cai quando os juros de mercado sobem (é a <a href="{{base}}glossario.html#marcacao-a-mercado">marcação a mercado</a>). Para comparar números, use o <a href="{{base}}calculadoras/simulador-renda-fixa.html">simulador de renda fixa</a>.</p>
</div>
{fontes_html([fonte_sgs(S, "selic_meta"), fonte_sgs(S, "selic"), fonte_sgs(S, "selic_ano"),
              f'<a href="{COPOM_URL}" rel="noopener">Banco Central do Brasil — Copom: calendário e comunicados</a>',
              f'<a href="https://www3.bcb.gov.br/CALCIDADAO/publico/exibirFormCorrecaoValores.do?method=exibirFormCorrecaoValores&amp;aba=4" rel="noopener">Banco Central — Calculadora do Cidadão (correção pela Selic), usada na conferência</a>'])}
{links_rel([("indicadores/cdi-hoje.html", "Indicador", "CDI hoje"), ("indicadores/rendimento-da-poupanca.html", "Indicador", "Rendimento da poupança"),
            ("tesouro-direto.html", "Dados abertos", "Tesouro Direto: taxas do dia")], "{base}")}
"""
    t = f"Selic hoje: meta de {pct(m['valor'])} e taxa over · {B.NOME}"
    if len(t) > B.TITULO_MAX:
        t = f"Selic hoje: meta de {pct(m['valor'])} e taxa over"
    desc = (f"Meta Selic de {pct(m['valor'])} ao ano desde {dbr(m['desde'])}, Selic over do dia e acumulada em 12 meses, "
            f"com gráfico e fonte do Banco Central.")
    desc = ajusta_desc(desc, "Educativo.")
    return t, desc, pagina(D, "indicadores/selic-hoje.html", t, desc, "Selic hoje",
                           f"A meta Selic está em <strong>{pct(m['valor'])} ao ano</strong> desde {dlong(m['desde'])}. A Selic over de {dbr(s['data'])} ficou em {pct(s['ano'])} ao ano.",
                           corpo, ("Indicadores", "indicadores.html"), og,
                           [dataset_ld("Meta Selic e Selic over", "Meta Selic (SGS 432) e Selic over (SGS 11 e 1178) do Banco Central",
                                       f"{B.DOMINIO}/indicadores/selic-hoje.html", PORTAL + PORTAL_SERIE[432], f"{m['mudancas'][0][0]}/{m['data']}")])


def ajusta_desc(desc, extra):
    """Mantém a descrição entre os limites do build: completa com 'extra' se curta."""
    if len(desc) < B.DESCRICAO_MIN:
        desc = desc + " " + extra
    return desc


def p_cdi(D, og):
    S, I = D["S"], D["I"]
    c, s, m = I["cdi"], I["selic"], I["meta"]
    corte = (dt.date.fromisoformat(c["data"]) - dt.timedelta(days=365 * 5)).isoformat()
    # uma amostra por semana basta para o desenho (a tabela traz os dias)
    serie = []
    ultima_sem = None
    for d, v in c["serie_ano"]:
        if d < corte:
            continue
        sem = dt.date.fromisoformat(d).isocalendar()[:2]
        if sem != ultima_sem:
            serie.append((d, v))
            ultima_sem = sem
    if serie[-1][0] != c["data"]:
        serie.append((c["data"], c["ano"]))
    svg = svg_serie(serie, "g-cdi", f"CDI anualizado de {dbr(serie[0][0])} a {dbr(c['data'])}, em % ao ano.", 2, "%")
    ult10 = list(reversed(S["cdi"]["pontos"][-10:]))
    anos = {d: v for d, v in c["serie_ano"]}
    linhas = [[dbr(p[0]), pct(p[1], 6), pct(anos.get(p[0], float("nan")))] for p in ult10]
    nums = numeros([("CDI (a.a.)", pct(c["ano"])), ("CDI do dia", pct(c["dia"], 6)),
                    ("Acumulado em 12 meses", pct(c["acum12"])), (f"Acumulado em {c['data'][:4]}", pct(c["acum_ano"])),
                    ("Acumulado no mês", pct(c["acum_mes"])), ("Referência", dbr(c["data"])),
                    ("Meta Selic", pct(m["valor"])), ("Selic over (a.a.)", pct(s["ano"]))])
    ex100 = 1000 * (c["acum12"] / 100)
    ex90 = 1000 * ((1 + 0.9 * ((1 + c["ano"] / 100) ** (1 / 252) - 1)) ** 252 - 1)
    corpo = f"""{aviso_falha(S, ["cdi", "cdi_ano"])}
{selo_ref(f"Taxa de {dbr(c['data'])} · coletado em {coletado(D['bcb'])}")}
{nums}
<h2 id="grafico">O CDI nos últimos cinco anos</h2>
{grafico(svg, "CDI anualizado (base 252 dias úteis), um ponto por semana. Fonte: Banco Central do Brasil, SGS 4389.")}
<div class="texto">
<h2 id="o-que-e">O que é o CDI</h2>
<p>CDI é a sigla de Certificado de Depósito Interbancário, o título que os bancos usam para emprestar dinheiro uns aos outros por um dia. A <strong>taxa DI</strong> — que todo mundo chama de CDI — é a média dessas operações, calculada pela B3 e publicada também pelo Banco Central no SGS, que é a fonte usada aqui. Ela anda colada na <a href="{{base}}indicadores/selic-hoje.html">Selic</a>: em {dbr(c['data'])}, CDI de {pct(c['ano'])} contra Selic over de {pct(s['ano'])}.</p>
<p>O CDI importa para o investidor porque é a régua da renda fixa privada: um <a href="{{base}}glossario.html#cdb">CDB</a> que paga “100% do CDI” rende, a cada dia útil, a taxa DI daquele dia; um que paga 90% rende 90% dela.</p>

<h2 id="acumulado">CDI acumulado</h2>
<p>Nos 12 meses até {dbr(c['data'])} — {c['dias12']} dias úteis, a partir de {dbr(c['ini12'])} —, o CDI acumulou <span class="num">{pct(c['acum12'])}</span>. No ano de {c['data'][:4]}, <span class="num">{pct(c['acum_ano'])}</span>; no mês, <span class="num">{pct(c['acum_mes'])}</span> em {c['dias_mes']} dias úteis.</p>
<div class="formula">acumulado = (1 + DI<sub>1</sub>) × (1 + DI<sub>2</sub>) × … × (1 + DI<sub>n</sub>) − 1</div>
<p>Conferido em {dbr(CONFERIDO)} contra a Calculadora do Cidadão do Banco Central: de 01/10/2025 a 01/10/2026, fator de 1,14474060 nos dois.</p>

<h2 id="percentual">Como calcular um percentual do CDI</h2>
<p>O percentual se aplica à taxa de cada dia, não à taxa anual. Com o CDI anual de {pct(c['ano'])}, a taxa do dia é <span class="num">(1 + {B.br(c['ano'])}%)<sup>1/252</sup> − 1 = {pct(((1 + c['ano'] / 100) ** (1 / 252) - 1) * 100, 6)}</span>. Noventa por cento disso, acumulados em 252 dias úteis, dão <span class="num">{pct(ex90 / 10)}</span> ao ano — um pouco menos que 90% de {pct(c['ano'])} ({pct(0.9 * c['ano'])}).</p>
<div class="exemplo"><p><strong>Exemplo:</strong> R$ 1.000 aplicados a 100% do CDI nos últimos 12 meses teriam rendido cerca de <span class="num">{B.brl(ex100)}</span> antes do imposto. Num CDB, o <a href="{{base}}glossario.html#tabela-regressiva">imposto de renda</a> leva de 22,5% a 15% do rendimento, conforme o prazo; numa LCI ou LCA, nada. O <a href="{{base}}calculadoras/simulador-renda-fixa.html">simulador de renda fixa</a> faz a conta líquida.</p></div>

<h2 id="ultimos">Últimas taxas diárias</h2>
</div>
{tabela(["Data", "CDI do dia", "CDI anualizado"], linhas, "CDI nos últimos 10 dias úteis publicados")}
{fontes_html([fonte_sgs(S, "cdi"), fonte_sgs(S, "cdi_ano"),
              f'<a href="https://www3.bcb.gov.br/CALCIDADAO/publico/exibirFormCorrecaoValores.do?method=exibirFormCorrecaoValores&amp;aba=5" rel="noopener">Banco Central — Calculadora do Cidadão (correção pelo CDI), usada na conferência</a>'])}
{links_rel([("indicadores/selic-hoje.html", "Indicador", "Selic hoje"), ("calculadoras/simulador-renda-fixa.html", "Simulador", "CDB, LCI, LCA, Tesouro e poupança"),
            ("glossario.html#cdi", "Glossário", "CDI e outros termos")], "{base}")}
"""
    t = f"CDI hoje: {pct(c['ano'])} ao ano e acumulado 12 meses · {B.NOME}"
    if len(t) > B.TITULO_MAX:
        t = f"CDI hoje: {pct(c['ano'])} ao ano e acumulado em 12 meses"
    desc = (f"CDI de {pct(c['ano'])} ao ano em {dbr(c['data'])}, acumulado em 12 meses, no ano e no mês, como calcular "
            f"% do CDI e gráfico. Fonte: Banco Central.")
    desc = ajusta_desc(desc, "Educativo.")
    return t, desc, pagina(D, "indicadores/cdi-hoje.html", t, desc, "CDI hoje",
                           f"O CDI de {dbr(c['data'])} foi de <strong>{pct(c['ano'])} ao ano</strong>. Nos últimos 12 meses, acumulou {pct(c['acum12'])}.",
                           corpo, ("Indicadores", "indicadores.html"), og,
                           [dataset_ld("CDI diário e acumulado", "Taxa DI (CDI) diária e anualizada, SGS 12 e 4389 do Banco Central",
                                       f"{B.DOMINIO}/indicadores/cdi-hoje.html", SGS_URL, f"{S['cdi']['pontos'][0][0]}/{c['data']}",
                                       licenca="https://www.bcb.gov.br/")])


def mes_ref(d):
    return B.mes_ano(d)


def p_ipca(D, og):
    S, I = D["S"], D["I"]
    ip = I["ipca"]
    serie = [(d, v) for d, v in ip["serie12"]][-61:]
    svg = svg_serie(serie, "g-ipca", f"IPCA acumulado em 12 meses de {mes_ref(serie[0][0])} a {mes_ref(serie[-1][0])}.", 2, "%")
    doze = {d: v for d, v in ip["serie12"]}
    linhas = [[B.MESES[int(d[5:7]) - 1] + "/" + d[:4], pct(v), pct(doze.get(d, float("nan")))] for d, v in reversed(ip["mensal"][-13:])]
    nums = numeros([("IPCA 12 meses", pct(ip["doze"])), (f"IPCA de {B.MESES_LONGO[int(ip['ref'][5:7]) - 1]}", pct(ip["mes"])),
                    (f"Acumulado em {ip['ref'][:4]}", pct(ip["ano"])), ("Mês de referência", B.MESES[int(ip['ref'][5:7]) - 1] + "/" + ip["ref"][:4])])
    real = ((1 + I["cdi"]["acum12"] / 100) / (1 + ip["doze"] / 100) - 1) * 100
    corpo = f"""{aviso_falha(S, ["ipca", "ipca12"])}
{selo_ref(f"Referência: {mes_ref(ip['ref'])} · coletado em {coletado(D['bcb'])}")}
{nums}
<h2 id="grafico">IPCA em 12 meses, nos últimos cinco anos</h2>
{grafico(svg, "IPCA acumulado em 12 meses, mês a mês. Fonte: IBGE, série publicada no SGS do Banco Central (13522).")}
<div class="texto">
<h2 id="o-que-e">O que é o IPCA</h2>
<p>O Índice Nacional de Preços ao Consumidor Amplo é a inflação oficial do Brasil. Ele é calculado pelo IBGE a partir dos preços de uma cesta de produtos e serviços consumida por famílias com renda de 1 a 40 salários mínimos, em várias regiões metropolitanas. É o índice da meta de inflação perseguida pelo Banco Central — e o que corrige o <a href="{{base}}tesouro-direto.html">Tesouro IPCA+</a>.</p>
<p>O IBGE divulga o IPCA de um mês por volta do dia 10 do mês seguinte. Por isso o número mais recente aqui é de <strong>{mes_ref(ip['ref'])}</strong>.</p>

<h2 id="acumulado">Como se chega ao acumulado em 12 meses</h2>
<p>Os índices mensais se multiplicam, não se somam:</p>
<div class="formula">IPCA 12 meses = (1 + m<sub>1</sub>) × (1 + m<sub>2</sub>) × … × (1 + m<sub>12</sub>) − 1</div>
<p>O site confere, a cada atualização, se o acumulado publicado pelo Banco Central (série 13522) bate com o produto dos doze meses da série mensal (433). Se não bater, a página não é publicada.</p>

<h2 id="juro-real">IPCA e juro real</h2>
<p>Juro real é o que sobra do rendimento depois da inflação. A conta certa divide, em vez de subtrair:</p>
<div class="formula">real = (1 + nominal) ÷ (1 + inflação) − 1</div>
<p>Com o <a href="{{base}}indicadores/cdi-hoje.html">CDI acumulado em 12 meses</a> de {pct(I['cdi']['acum12'])} e IPCA de {pct(ip['doze'])} no período mais próximo, o juro real do CDI ficou perto de <span class="num">{pct(real)}</span> — os períodos não são idênticos (o CDI vai até {dbr(I['cdi']['data'])}, o IPCA até {mes_ref(ip['ref'])}), então o número é aproximado.</p>

<h2 id="tabela">IPCA mês a mês</h2>
</div>
{tabela(["Mês", "IPCA do mês", "Acumulado em 12 meses"], linhas, "IPCA nos últimos 13 meses")}
{fontes_html([fonte_sgs(S, "ipca"), fonte_sgs(S, "ipca12"),
              f'<a href="{IBGE_IPCA}" rel="noopener">IBGE — Índice Nacional de Preços ao Consumidor Amplo (IPCA): metodologia e calendário</a>'])}
{links_rel([("indicadores/cdi-hoje.html", "Indicador", "CDI hoje"), ("tesouro-direto.html", "Dados abertos", "Tesouro IPCA+: taxas do dia"),
            ("glossario.html#ipca", "Glossário", "IPCA, inflação e juro real")], "{base}")}
"""
    t = f"IPCA acumulado em 12 meses: {pct(ip['doze'])} · {B.NOME}"
    desc = (f"IPCA acumulado em 12 meses de {pct(ip['doze'])} até {mes_ref(ip['ref'])}, inflação do mês e do ano, "
            "como o acumulado é calculado e juro real. Fonte: IBGE.")
    desc = ajusta_desc(desc, "Educativo.")
    return t, desc, pagina(D, "indicadores/ipca-acumulado-12-meses.html", t, desc, "IPCA acumulado em 12 meses",
                           f"A inflação oficial acumulada em 12 meses até {mes_ref(ip['ref'])} foi de <strong>{pct(ip['doze'])}</strong>. Só em {B.MESES_LONGO[int(ip['ref'][5:7]) - 1]}, {pct(ip['mes'])}.",
                           corpo, ("Indicadores", "indicadores.html"), og,
                           [dataset_ld("IPCA mensal e acumulado em 12 meses", "IPCA do IBGE, séries 433 e 13522 do SGS do Banco Central",
                                       f"{B.DOMINIO}/indicadores/ipca-acumulado-12-meses.html", IBGE_IPCA,
                                       f"{ip['mensal'][0][0][:7]}/{ip['ref'][:7]}", licenca="https://www.ibge.gov.br/", publicador="IBGE")])


def p_poupanca(D, og):
    S, I = D["S"], D["I"]
    p, m = I["poup"], I["meta"]
    corte = (dt.date.fromisoformat(p["ini"]) - dt.timedelta(days=365 * 5)).isoformat()
    serie = [(x[0], x[1]) for x in p["dia1"] if x[0] >= corte]
    svg = svg_serie(serie, "g-poup", "Rendimento mensal da poupança para aniversário no dia 1, em % ao mês.", 2, "%")
    tr = {x[0]: x[1] for x in p["tr1"]}
    linhas = [[dbr(x[0]) + " a " + dbr(x[2]), pct(x[1], 4), pct(tr.get(x[0], float("nan")), 4)] for x in reversed(p["dia1"][-12:])]
    regra = ("0,5% ao mês + TR" if p["regra_05"] else "70% da meta Selic mensalizada + TR")
    nums = numeros([(f"Período {dbr(p['ini'])} a {dbr(p['fim'])}", pct(p["valor"], 4)), ("Regra em vigor", regra),
                    ("TR do período", pct(p["tr"], 4)), ("12 meses (aniversário dia 1)", pct(p["acum12"]))])
    corpo = f"""{aviso_falha(S, ["poupanca", "tr", "selic_meta"])}
{selo_ref(f"Período iniciado em {dbr(p['ini'])} · coletado em {coletado(D['bcb'])}")}
{nums}
<h2 id="grafico">Rendimento mensal, nos últimos cinco anos</h2>
{grafico(svg, "Rendimento da poupança no período mensal que começa no dia 1 de cada mês (depósitos feitos desde 04/05/2012). Fonte: Banco Central do Brasil, SGS 195.")}
<div class="texto">
<h2 id="regra">A regra, conferida na lei</h2>
<p class="data-regra"><strong>Regra conferida em {dlong(CONFERIDO)}</strong> na Lei nº 8.177/1991, art. 12, com a redação da Lei nº 12.703/2012.</p>
<p>Para depósitos feitos a partir de 4 de maio de 2012, a poupança rende, a cada mês completo desde a data de aniversário:</p>
<ul>
 <li>a <strong>TR</strong> (taxa referencial) do período, como remuneração básica; mais</li>
 <li><strong>0,5% ao mês</strong>, enquanto a meta Selic for <em>superior</em> a 8,5% ao ano; ou</li>
 <li><strong>70% da meta Selic mensalizada</strong>, quando a meta for de 8,5% ou menos.</li>
</ul>
<p>Hoje a meta é de <span class="num">{pct(m['valor'])}</span>, acima de 8,5%: vale a primeira regra. Para o período de {dbr(p['ini'])} a {dbr(p['fim'])}, a TR foi de {pct(p['tr'], 4)}, e a conta dá</p>
<div class="formula">(1 + 0,5%) × (1 + {B.br(p['tr'], 4)}%) − 1 = {pct(p['valor'], 4)}</div>
<p>que é exatamente o número publicado pelo Banco Central. O site faz essa conta a cada atualização e para a publicação se ela não bater.</p>
<p>Depósitos anteriores a 4 de maio de 2012 seguem rendendo sempre 0,5% ao mês + TR. Para pessoa física, o rendimento da poupança é isento de imposto de renda (Lei nº 8.981/1995, art. 68, III).</p>

<h2 id="aniversario">Data de aniversário: o rendimento é mensal</h2>
<p>A poupança só paga no aniversário — o dia do mês em que o dinheiro entrou. Quem tira o dinheiro um dia antes perde o rendimento do mês inteiro. Depósitos feitos nos dias 29, 30 e 31 fazem aniversário no dia 1º do mês seguinte. Como a TR muda a cada dia de início, o rendimento depende do dia de aniversário; os números desta página são do aniversário no dia 1º.</p>

<h2 id="tr">E a TR?</h2>
<p>A TR é calculada pelo Banco Central a partir das taxas de juros dos títulos públicos prefixados, com um redutor. Passou anos em zero e voltou a ser positiva com os juros altos; hoje está em torno de {pct(p['tr'], 2)} ao mês. Nos 12 períodos mensais de {dbr(p['ini12'])} a {dbr(p['fim12'])}, a poupança com aniversário no dia 1º rendeu <span class="num">{pct(p['acum12'])}</span>.</p>

<h2 id="comparar">Comparar com outros investimentos</h2>
<p>O rendimento da poupança cai na conta sem imposto, mas só em meses completos. O <a href="{{base}}calculadoras/simulador-renda-fixa.html">simulador de renda fixa</a> compara a poupança com CDB, LCI, LCA e Tesouro Direto no mesmo prazo, já descontando imposto de renda, IOF e taxa de custódia.</p>
<h2 id="tabela">Últimos 12 períodos</h2>
</div>
{tabela(["Período (aniversário dia 1)", "Rendimento", "TR"], linhas, "Rendimento da poupança e TR por período mensal")}
{fontes_html([fonte_sgs(S, "poupanca"), fonte_sgs(S, "tr"), fonte_sgs(S, "selic_meta"),
              f'<a href="{LEI_POUPANCA}" rel="noopener">Lei nº 8.177/1991, art. 12 (redação da Lei nº 12.703/2012) — regra de remuneração da poupança</a>',
              '<a href="https://www.planalto.gov.br/ccivil_03/leis/l8981.htm" rel="noopener">Lei nº 8.981/1995, art. 68, III — isenção de IR da poupança para pessoa física</a>',
              '<a href="https://www3.bcb.gov.br/CALCIDADAO/publico/exibirFormCorrecaoValores.do?method=exibirFormCorrecaoValores&amp;aba=3" rel="noopener">Banco Central — Calculadora do Cidadão (poupança), usada na conferência</a>'])}
{links_rel([("indicadores/selic-hoje.html", "Indicador", "Selic hoje"), ("calculadoras/simulador-renda-fixa.html", "Simulador", "Poupança × CDB × Tesouro"),
            ("glossario.html#poupanca", "Glossário", "Poupança e TR")], "{base}")}
"""
    t = f"Rendimento da poupança hoje: regra e TR · {B.NOME}"
    desc = (f"Quanto rende a poupança: {pct(p['valor'], 4)} no período iniciado em {dbr(p['ini'])}, regra de 0,5% + TR "
            "conferida na lei, TR do mês e acumulado em 12 meses.")
    desc = ajusta_desc(desc, "Fonte: Banco Central.")
    return t, desc, pagina(D, "indicadores/rendimento-da-poupanca.html", t, desc, "Rendimento da poupança",
                           f"Para aniversário em {dbr(p['ini'])}, a poupança rende <strong>{pct(p['valor'], 4)}</strong> no mês: {regra}, com a meta Selic em {pct(m['valor'])}.",
                           corpo, ("Indicadores", "indicadores.html"), og,
                           [dataset_ld("Rendimento da poupança", "Rentabilidade da poupança no período (SGS 195) e TR (SGS 226)",
                                       f"{B.DOMINIO}/indicadores/rendimento-da-poupanca.html", PORTAL + PORTAL_SERIE[195],
                                       f"{S['poupanca']['pontos'][0][0]}/{p['ini']}")])


def p_moeda(D, og, k):
    S, I = D["S"], D["I"]
    x = I[k]
    nome, slug = ("dólar", "dolar-ptax-hoje") if k == "dolar" else ("euro", "euro-ptax-hoje")
    Nome = nome.capitalize()
    pts = [(p[0], p[2]) for p in x["pontos"]]
    svg = svg_serie(pts, f"g-{k}", f"{Nome} PTAX de venda de {dbr(pts[0][0])} a {dbr(pts[-1][0])}, em reais.", 4, "", rotulo_x="mes")
    linhas = [[dbr(p[0]), B.br(p[1], 4), B.br(p[2], 4)] for p in reversed(x["pontos"][-10:])]
    va = B.var_html(x["var_dia"])
    nums = numeros([("PTAX de venda", "R$ " + B.br(x["venda"], 4)), ("PTAX de compra", "R$ " + B.br(x["compra"], 4)),
                    ("Variação no dia", va), ("Em 12 meses", B.var_html(x["var12"])),
                    (f"No ano de {x['data'][:4]}", B.var_html(x["var_ano"]) if x["var_ano"] is not None else "—"),
                    ("Máxima em 12 meses", f"R$ {B.br(x['max'][2], 4)} ({dbr(x['max'][0])})"),
                    ("Mínima em 12 meses", f"R$ {B.br(x['min'][2], 4)} ({dbr(x['min'][0])})"), ("Boletim de", dbr(x["data"]))])
    outro = ("euro-ptax-hoje.html", "Euro PTAX hoje") if k == "dolar" else ("dolar-ptax-hoje.html", "Dólar PTAX hoje")
    paridade = ""
    if k == "euro" and I["dolar"]["data"] == x["data"]:
        paridade = (f"<p>Dividindo o euro pelo dólar do mesmo boletim, chega-se à paridade aproximada de "
                    f"<span class=\"num\">{B.br(x['venda'] / I['dolar']['venda'], 4)}</span> dólar por euro.</p>")
    corpo = f"""{aviso_falha(S, [k])}
{selo_ref(f"Boletim de fechamento de {dbr(x['data'])} · coletado em {coletado(D['bcb'])}")}
{nums}
<h2 id="grafico">{Nome} PTAX nos últimos dois anos</h2>
{grafico(svg, f"Cotação PTAX de venda do {nome}, boletim de fechamento, em reais. Fonte: Banco Central do Brasil.")}
<div class="texto">
<h2 id="o-que-e">O que é a PTAX</h2>
<p>A PTAX é a taxa de câmbio de referência calculada pelo Banco Central. Não é o preço de uma operação: é a média das cotações que os dealers de câmbio informam ao BC em quatro janelas de consulta ao longo do dia, descartadas as extremas, conforme a Circular BCB nº 3.506/2010. O boletim de <strong>fechamento</strong>, divulgado no começo da tarde, é a PTAX do dia.</p>
<p>Ela é usada em contratos, na conversão de valores para a declaração do imposto de renda, em faturas de cartão em moeda estrangeira (conforme o contrato) e como base de comparação. O {nome} que se paga numa casa de câmbio ou no cartão é outro número: inclui o spread da instituição e, no caso do cartão, o IOF.</p>
<p>A PTAX tem dois lados: a de <strong>compra</strong> (R$ {B.br(x['compra'], 4)}) e a de <strong>venda</strong> (R$ {B.br(x['venda'], 4)}). Quando um contrato fala em “PTAX” sem dizer qual, costuma ser a de venda — confira sempre o texto do contrato.</p>
{paridade}
<h2 id="variacao">Como ler a variação</h2>
<p>A variação de {dbr(x['ant'][0])} para {dbr(x['data'])} compara as PTAX de venda dos dois boletins de fechamento. A de 12 meses compara com o último boletim até {dbr(menos_um_ano_iso(x['data']))} ({dbr(x['base12'][0])}, R$ {B.br(x['base12'][2], 4)}). Câmbio oscila todos os dias, e uma fotografia do dia não diz para onde ele vai.</p>
<h2 id="tabela">Últimos boletins</h2>
</div>
{tabela(["Data", "Compra (R$)", "Venda (R$)"], linhas, f"{Nome} PTAX, boletim de fechamento")}
{fontes_html([fonte_sgs(S, k), f'<a href="{CIRC_PTAX}" rel="noopener">Circular BCB nº 3.506/2010 — metodologia da PTAX</a>'])}
{links_rel([("indicadores/" + outro[0], "Indicador", outro[1]), ("indicadores.html", "Indicadores", "Todos os indicadores de hoje"),
            ("glossario.html#ptax", "Glossário", "PTAX e câmbio")], "{base}")}
"""
    sigla = "US$" if k == "dolar" else "€"
    t = f"{Nome} PTAX hoje: R$ {B.br(x['venda'], 4)} · {B.NOME}"
    desc = (f"{Nome} PTAX de {dbr(x['data'])}: R$ {B.br(x['venda'], 4)} na venda e R$ {B.br(x['compra'], 4)} na compra, "
            f"variação do dia e em 12 meses e gráfico de 2 anos.")
    desc = ajusta_desc(desc, "Fonte: Banco Central.")
    return t, desc, pagina(D, f"indicadores/{slug}.html", t, desc, f"{Nome} PTAX hoje",
                           f"A PTAX de venda do {nome} no boletim de fechamento de {dbr(x['data'])} foi de <strong>R$ {B.br(x['venda'], 4)}</strong> por {sigla} 1.",
                           corpo, ("Indicadores", "indicadores.html"), og,
                           [dataset_ld(f"{Nome} PTAX", f"Cotação PTAX do {nome}, boletim de fechamento, Banco Central do Brasil",
                                       f"{B.DOMINIO}/indicadores/{slug}.html", PORTAL + PTAX_PORTAL[k], f"{pts[0][0]}/{x['data']}")])


def menos_um_ano_iso(d):
    return menos_um_ano(d)


# --- hub dos indicadores -----------------------------------------------------------------

def p_hub(D, og):
    S, I = D["S"], D["I"]
    m, s, c, ip, p, td = I["meta"], I["selic"], I["cdi"], I["ipca"], I["poup"], D["td"]
    cartoes = [
        ("indicadores/selic-hoje.html", "Meta Selic", pct(m["valor"]), f"ao ano · desde {dbr(m['desde'])}", "SGS 432"),
        ("indicadores/selic-hoje.html", "Selic over", pct(s["ano"]), f"ao ano · {dbr(s['data'])} · 12 meses: {pct(s['acum12'])}", "SGS 11 e 1178"),
        ("indicadores/cdi-hoje.html", "CDI", pct(c["ano"]), f"ao ano · {dbr(c['data'])}", "SGS 12 e 4389"),
        ("indicadores/cdi-hoje.html", "CDI em 12 meses", pct(c["acum12"]), f"acumulado até {dbr(c['data'])} · no ano: {pct(c['acum_ano'])}", "SGS 12"),
        ("indicadores/ipca-acumulado-12-meses.html", "IPCA em 12 meses", pct(ip["doze"]), f"até {mes_ref(ip['ref'])} · no mês: {pct(ip['mes'])}", "IBGE, SGS 13522 e 433"),
        ("indicadores/rendimento-da-poupanca.html", "Poupança", pct(p["valor"], 4), f"no mês iniciado em {dbr(p['ini'])} · 0,5% + TR", "SGS 195"),
        ("indicadores/rendimento-da-poupanca.html", "TR", pct(p["tr"], 4), f"período iniciado em {dbr(p['tr_ini'])}", "SGS 226"),
        ("indicadores/dolar-ptax-hoje.html", "Dólar PTAX", "R$ " + B.br(I["dolar"]["venda"], 4), f"venda · fechamento de {dbr(I['dolar']['data'])}", "PTAX"),
        ("indicadores/euro-ptax-hoje.html", "Euro PTAX", "R$ " + B.br(I["euro"]["venda"], 4), f"venda · fechamento de {dbr(I['euro']['data'])}", "PTAX"),
    ]
    html_c = '<ul class="ind-grade">' + "".join(
        f'<li><a class="ind-cartao" href="{{base}}{h}"><span class="rotulo">{e(r)}</span><span class="ind-valor num">{v}</span>'
        f'<span class="ind-ref">{e(sub)}</span><span class="ind-fonte">Fonte: {e(f)}</span></a></li>' for h, r, v, sub, f in cartoes) + "</ul>"
    # mini gráfico: CDI × IPCA em 12 meses (mensal)
    cdi_mes = {}
    for d, v, *_ in S["cdi"]["pontos"]:
        cdi_mes.setdefault(d[:7], []).append(v)
    tabela_resumo = [[e(r), v, e(sub)] for _, r, v, sub, _ in cartoes]
    corpo = f"""{aviso_falha(S, list(ESSENCIAIS))}
{selo_ref(f"Coletado no Banco Central em {coletado(D['bcb'])} · cada número traz a própria data de referência")}
{html_c}
<div class="texto">
<h2 id="como-ler">Como ler estes números</h2>
<p>Cada indicador tem a sua data: o CDI e a Selic over saem a cada dia útil, com um dia de atraso; o IPCA é mensal e sai por volta do dia 10 do mês seguinte; a PTAX é publicada todo dia útil, à tarde; a poupança tem um número para cada dia de aniversário. Por isso as datas dos cartões não são iguais — e o site mostra cada uma em vez de fingir que tudo é “de hoje”.</p>
<p>Todos vêm de dados abertos do <strong>Banco Central do Brasil</strong> (SGS e PTAX); o IPCA é calculado pelo <strong>IBGE</strong> e publicado também no SGS. A coleta roda junto com a atualização diária do site, e uma falha numa fonte não derruba as outras: a página mostra o último dado bom e avisa.</p>
<h2 id="tesouro">Tesouro Direto</h2>
<p>As taxas e os preços dos títulos públicos do dia, com histórico, estão na página do <a href="{{base}}tesouro-direto.html">Tesouro Direto</a> (dados abertos do Tesouro Nacional, base de {dbr(td['data_base'])}).</p>
<h2 id="igpm">E o IGP-M?</h2>
<p>O IGP-M é calculado pela Fundação Getulio Vargas, uma instituição privada, e não está entre os dados abertos do Banco Central com licença aberta. Para não republicar número sem licença clara, o site não o mostra; a fonte é o portal do FGV IBRE.</p>
<h2 id="resumo">Todos os números</h2>
</div>
{tabela(["Indicador", "Valor", "Referência"], tabela_resumo, "Indicadores de hoje, com data de referência")}
{links_rel([("calculadoras/simulador-renda-fixa.html", "Simulador", "Renda fixa: poupança, CDB, LCI, LCA e Tesouro"),
            ("tesouro-direto.html", "Dados abertos", "Tesouro Direto: taxas do dia"), ("glossario.html", "Glossário", "Termos do mercado explicados")], "{base}")}
"""
    t = f"Selic, CDI, IPCA e dólar hoje · {B.NOME}"
    desc = ("Selic, CDI, IPCA, poupança, TR, dólar e euro PTAX com a data de referência de cada número e a fonte oficial. "
            "Dados abertos do Banco Central.")
    desc = ajusta_desc(desc, "Educativo.")
    return t, desc, pagina(D, "indicadores.html", t, desc, "Indicadores de hoje",
                           "Juros, inflação, poupança e câmbio em um só lugar, direto das fontes oficiais e com a data de cada número.",
                           corpo, None, og, [dataset_ld("Indicadores econômicos do Banco Central", "Meta Selic, Selic over, CDI, IPCA, poupança, TR e PTAX",
                                                        f"{B.DOMINIO}/indicadores.html", SGS_URL, f"2021-01-01/{c['data']}")])


# --- Tesouro Direto ---------------------------------------------------------------------

ORDEM_TD = ["Tesouro Selic", "Tesouro Prefixado", "Tesouro Prefixado com Juros Semestrais", "Tesouro IPCA+",
            "Tesouro IPCA+ com Juros Semestrais", "Tesouro Renda+ Aposentadoria Extra", "Tesouro Educa+",
            "Tesouro IGPM+ com Juros Semestrais"]
INDEX_TD = {"Tesouro Selic": "Selic + ", "Tesouro IPCA+": "IPCA + ", "Tesouro IPCA+ com Juros Semestrais": "IPCA + ",
            "Tesouro Renda+ Aposentadoria Extra": "IPCA + ", "Tesouro Educa+": "IPCA + ", "Tesouro IGPM+ com Juros Semestrais": "IGP-M + "}


def slug_td(t):
    return re.sub(r"[^a-z0-9]+", "-", (t["tipo"] + " " + t["vencimento"][:4]).lower()
                  .replace("+", " mais ").replace("ç", "c").replace("ã", "a").replace("é", "e")).strip("-") + "-" + t["vencimento"][5:7]


def p_tesouro(D, og):
    td = D["td"]
    tit = td["titulos"]
    tipos = sorted({t["tipo"] for t in tit}, key=lambda x: ORDEM_TD.index(x) if x in ORDEM_TD else 99)
    blocos = []
    opcoes = []
    for tp in tipos:
        lin = []
        for t in sorted((t for t in tit if t["tipo"] == tp), key=lambda t: t["vencimento"]):
            idx = INDEX_TD.get(tp, "")
            f = lambda v: "—" if v is None else idx + pct(v)
            g = lambda v: "—" if v is None else B.brl(v)
            lin.append([dbr(t["vencimento"]), f(t["taxa_compra"]), g(t["pu_compra"]), f(t["taxa_venda"]), g(t["pu_venda"])])
            opcoes.append((f"{tp}|{t['vencimento']}", f"{tp} {t['vencimento'][:4]} ({dbr(t['vencimento'])})"))
        ident = re.sub(r"[^a-z0-9]+", "-", tp.lower().replace("+", "-mais").replace("ç", "c").replace("ã", "a")).strip("-")
        blocos.append(f'<h3 id="{ident}">{e(tp)}</h3>' + tabela(["Vencimento", "Taxa de compra (a.a.)", "Preço de compra", "Taxa de venda (a.a.)", "Preço de venda"],
                                                                lin, f"{e(tp)} — taxas e preços de {dbr(td['data_base'])}"))
    # histórico: arquivo separado, carregado sob demanda
    hist = {k: v for k, v in td["historico"].items()}
    B.RAIZ.joinpath("assets", "tesouro").mkdir(parents=True, exist_ok=True)
    (B.RAIZ / "assets" / "tesouro" / "historico.json").write_text(
        json.dumps({"data_base": td["data_base"], "series": hist}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    padrao = next((k for k, _ in opcoes if k.startswith("Tesouro IPCA+|")), opcoes[0][0])
    sel = "".join(f'<option value="{e(k)}"{" selected" if k == padrao else ""}>{e(n)}</option>' for k, n in opcoes)
    n_tipos = len(tipos)
    mod = dt.datetime.fromisoformat(td["arquivo_modificado_em"]).strftime("%d/%m/%Y") if td.get("arquivo_modificado_em") else "—"
    falhou = (f'<div class="aviso"><strong>Dado novo do Tesouro com problema</strong> ({e(td["problema"])}): não foi publicado. '
              f'Os números abaixo são o último dado conferido, com data-base de {dbr(td["data_base"])}.</div>') if td.get("problema") else ""
    falhou += "" if td.get("ok", True) else (f'<div class="aviso"><strong>A última coleta no Tesouro Transparente falhou</strong> '
                                             f'({e(td.get("erro", ""))}). Os números abaixo são da coleta anterior, com data-base de {dbr(td["data_base"])}.</div>')
    corpo = f"""{falhou}
{selo_ref(f"Data-base {dbr(td['data_base'])} · arquivo do Tesouro atualizado em {mod}")}
<div class="texto">
<p>São <strong>{len(tit)} títulos</strong> de {n_tipos} tipos no arquivo de taxas do Tesouro Direto de {dlong(td['data_base'])}. A <strong>taxa de compra</strong> é a que vale para quem compra o título naquele dia; a <strong>taxa de venda</strong> é a que o Tesouro usa para recomprar o título antes do vencimento. Os preços são por título inteiro; no Tesouro Direto dá para comprar frações a partir de 1% do título, respeitado o mínimo de R$ 30.</p>
<p>O arquivo do Tesouro Transparente se chama “taxas dos títulos ofertados”, mas pode incluir títulos que no dia só aceitam resgate antecipado. Antes de qualquer operação, a lista vigente é a do site oficial do Tesouro Direto.</p>
</div>
<h2 id="titulos">Taxas e preços de {dbr(td['data_base'])}</h2>
{"".join(blocos)}
<h2 id="historico">Histórico da taxa de compra</h2>
<div class="grafico grafico-js">
 <label class="seletor" for="td-sel">Título <select id="td-sel">{sel}</select></label>
 <div id="td-graf" class="td-graf" aria-live="polite"><p class="legenda">O gráfico precisa de JavaScript. Os números do dia estão nas tabelas acima.</p></div>
 <p class="legenda">Taxa de compra e taxa de venda no último dia útil de cada semana, nos últimos três anos, em % ao ano. Fonte: Tesouro Nacional, Tesouro Transparente.</p>
</div>
<div class="texto">
<h2 id="como-ler">Como ler a tabela</h2>
<ul>
 <li><strong>Tesouro Selic</strong>: rende a Selic over do período; a taxa da tabela é um ágio ou deságio somado à Selic (por isso é perto de zero).</li>
 <li><strong>Tesouro Prefixado</strong>: a taxa é a rentabilidade bruta ao ano de quem compra hoje e fica até o vencimento, quando recebe R$ 1.000 por título. Conferido em {dbr(CONFERIDO)}: o preço publicado é 1.000 ÷ (1 + taxa)<sup>du/252</sup>, com <em>du</em> os dias úteis entre a liquidação (dia útil seguinte à data-base) e o vencimento — a conta reproduz os preços do arquivo para os quatro prefixados sem cupom testados.</li>
 <li><strong>Tesouro IPCA+, Renda+ e Educa+</strong>: a taxa é o juro <em>real</em>, acima da inflação. O rendimento total é a variação do <a href="{{base}}indicadores/ipca-acumulado-12-meses.html">IPCA</a> mais essa taxa.</li>
 <li><strong>Com juros semestrais</strong>: paga cupons a cada seis meses, em vez de tudo no vencimento — e o imposto incide em cada cupom.</li>
</ul>
<h2 id="marcacao">Por que o preço muda todo dia</h2>
<p>Quem vende um título antes do vencimento recebe o preço do dia, calculado com a taxa de venda daquele dia, e não com a taxa contratada. Se as taxas de mercado subiram desde a compra, o preço cai, e o resgate antecipado pode render menos do que o combinado — ou até devolver menos do que foi aplicado. Isso é a <a href="{{base}}glossario.html#marcacao-a-mercado">marcação a mercado</a>. Levado até o vencimento, o título paga a taxa contratada.</p>
<h2 id="custos">Custos e impostos</h2>
<p class="data-regra"><strong>Regras conferidas em {dlong(CONFERIDO)}</strong> na B3 e no texto das leis.</p>
<ul>
 <li><strong>Taxa de custódia da B3:</strong> 0,20% ao ano sobre o valor dos títulos, proporcional ao tempo; no Tesouro Selic, isenta até R$ 10 mil por CPF (cobrada só sobre o que passar disso). Educa+ e Renda+ têm regras próprias, mais baixas.</li>
 <li><strong>Imposto de renda</strong> sobre o rendimento, pela <a href="{{base}}glossario.html#tabela-regressiva">tabela regressiva</a>: 22,5% até 180 dias, 20% até 360, 17,5% até 720 e 15% acima disso (Lei nº 11.033/2004, art. 1º).</li>
 <li><strong>IOF</strong> se o resgate acontecer nos primeiros 30 dias, de 96% a 0% do rendimento (Decreto nº 6.306/2007, art. 32 e anexo).</li>
</ul>
<p>Para simular o resultado líquido de cada tipo de título ao lado da poupança e de um CDB, use o <a href="{{base}}calculadoras/simulador-renda-fixa.html">simulador de renda fixa</a> — ele já vem preenchido com as taxas do dia desta página.</p>
</div>
{fontes_html([f'<a href="{TD_ABERTO}" rel="noopener">Tesouro Nacional — Tesouro Transparente: Taxas dos Títulos Ofertados pelo Tesouro Direto (licença ODbL)</a>',
              f'<a href="{B3_TARIFAS_TD}" rel="noopener">B3 — Tarifas do Tesouro Direto (taxa de custódia)</a>',
              f'<a href="{LEI_11033}" rel="noopener">Lei nº 11.033/2004, art. 1º — tabela regressiva do imposto de renda</a>',
              f'<a href="{DEC_IOF}" rel="noopener">Decreto nº 6.306/2007, art. 32 e anexo — IOF regressivo</a>'])}
{links_rel([("calculadoras/simulador-renda-fixa.html", "Simulador", "Tesouro × CDB × poupança"), ("indicadores/selic-hoje.html", "Indicador", "Selic hoje"),
            ("guias/como-declarar-renda-fixa-e-tesouro-direto-no-imposto-de-renda.html", "Guia", "Como declarar o Tesouro Direto")], "{base}")}
"""
    js = r"""(function(){var s=document.getElementById('td-sel'),g=document.getElementById('td-graf'),D=null;
function fmt(v){return v==null?'—':v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+'%'}
function br(d){return d.slice(8,10)+'/'+d.slice(5,7)+'/'+d.slice(0,4)}
function desenha(){var k=s.value,p=D.series[k];if(!p||p.length<2){g.innerHTML='<p class="legenda">Sem histórico para este título.</p>';return}
 var W=720,H=330,x0=78,x1=708,y0=16,y1=282,vs=[];p.forEach(function(r){if(r[1]!=null)vs.push(r[1]);if(r[2]!=null)vs.push(r[2])});
 var lo=Math.min.apply(null,vs),hi=Math.max.apply(null,vs),pa=(hi-lo)/4||0.5,m=Math.pow(10,Math.floor(Math.log10(pa)));
 pa=[1,2,2.5,5,10].map(function(x){return x*m}).filter(function(x){return x>=pa})[0];var ymin=Math.floor(lo/pa)*pa,ymax=Math.ceil(hi/pa)*pa;if(ymax==ymin)ymax+=pa;
 var t0=Date.parse(p[0][0]),t1=Date.parse(p[p.length-1][0]);function X(d){return x0+(x1-x0)*(Date.parse(d)-t0)/((t1-t0)||1)}function Y(v){return y1-(y1-y0)*(v-ymin)/(ymax-ymin)}
 function linha(i,c){var a=[];p.forEach(function(r){if(r[i]!=null)a.push(X(r[0]).toFixed(1)+','+Y(r[i]).toFixed(1))});return '<polyline class="'+c+'" points="'+a.join(' ')+'"/>'}
 var o='<svg class="unico" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Taxa de compra e de venda de '+k.replace('|',' ')+'">';
 for(var v=ymin;v<=ymax+1e-9;v+=pa){var y=Y(v).toFixed(1);o+='<line class="grade-y" x1="'+x0+'" x2="'+x1+'" y1="'+y+'" y2="'+y+'"/><text x="'+(x0-10)+'" y="'+(+y+7)+'" text-anchor="end">'+fmt(v)+'</text>'}
 var a0=+p[0][0].slice(0,4),a1=+p[p.length-1][0].slice(0,4);for(var a=a0+1;a<=a1;a++){var x=X(a+'-01-01');if(x>x0+20&&x<x1-10)o+='<text x="'+x.toFixed(1)+'" y="'+(H-14)+'" text-anchor="middle">'+a+'</text>'}
 o+=linha(2,'linha linha-2')+linha(1,'linha')+'</svg>';var u=p[p.length-1];
 g.innerHTML=o+'<p class="legenda"><span class="chave"></span> Taxa de compra · <span class="chave chave-2"></span> Taxa de venda. Último ponto: '+br(u[0])+', compra '+fmt(u[1])+', venda '+fmt(u[2])+'.</p>'}
s.addEventListener('change',function(){if(D)desenha()});
fetch('{base}assets/tesouro/historico.json').then(function(r){return r.json()}).then(function(j){D=j;desenha()}).catch(function(){g.innerHTML='<p class="legenda">Não foi possível carregar o histórico.</p>'});
})();""".replace("{base}", "")
    t = f"Tesouro Direto hoje: taxas e preços · {B.NOME}"
    desc = (f"Taxas e preços do Tesouro Selic, Prefixado, IPCA+, Renda+ e Educa+ em {dbr(td['data_base'])}, com histórico e "
            "custos. Dados abertos do Tesouro Nacional.")
    desc = ajusta_desc(desc, "Educativo.")
    return t, desc, pagina(D, "tesouro-direto.html", t, desc, "Tesouro Direto hoje",
                           f"Taxas e preços dos títulos públicos na data-base de <strong>{dbr(td['data_base'])}</strong>, direto dos dados abertos do Tesouro Nacional.",
                           corpo, None, og, [dataset_ld("Taxas e preços do Tesouro Direto", "Taxas e preços unitários dos títulos do Tesouro Direto",
                                                        f"{B.DOMINIO}/tesouro-direto.html", TD_ABERTO, f"{td['data_base']}", publicador="Tesouro Nacional")],
                           foto="bovespa-arcos", atual="indicadores", js=js)


# --- glossário -------------------------------------------------------------------------

def p_glossario(D, og):
    g = D["glo"]
    if not g:
        return None
    ids = set()
    nav, secoes, termos_ld = [], [], []
    total = 0
    for gr in g["grupos"]:
        itens = []
        for t in gr["termos"]:
            if t["id"] in ids:
                B.falha(f"glossário: id repetido {t['id']}")
            ids.add(t["id"])
            total += 1
            links = "".join(f'<a href="{e(l["href"])}">{e(l["texto"])}</a>' for l in t.get("links", []))
            fontes = "".join(f'<li><a href="{e(f["url"])}" rel="noopener">{e(f["nome"])}</a></li>' for f in t.get("fontes", []))
            sin = (f'<p class="sinonimos">Também: {e(", ".join(t["sinonimos"]))}</p>' if t.get("sinonimos") else "")
            itens.append(f'<section class="termo" id="{e(t["id"])}"><h3>{e(t["termo"])}</h3>{sin}{t["definicao"]}'
                         + (f'<p class="termo-links">{links}</p>' if links else "")
                         + (f'<details class="termo-fontes"><summary>Fonte</summary><ul class="fontes">{fontes}</ul></details>' if fontes else "")
                         + "</section>")
            txt = re.sub(r"<[^>]+>", "", t["definicao"])
            termos_ld.append({"@type": "DefinedTerm", "@id": f"{B.DOMINIO}/glossario.html#{t['id']}", "name": t["termo"],
                              "description": B.html.unescape(txt)[:300], "inDefinedTermSet": f"{B.DOMINIO}/glossario.html"})
        nav.append(f'<li><a href="#{e(gr["id"])}">{e(gr["nome"])}</a> <span class="num">({len(gr["termos"])})</span></li>')
        secoes.append(f'<h2 id="{e(gr["id"])}">{e(gr["nome"])}</h2>' + "".join(itens))
    az = sorted(((t["termo"], t["id"]) for gr in g["grupos"] for t in gr["termos"]), key=lambda x: B.html.unescape(x[0]).lower())
    indice = '<ul class="chips indice-az">' + "".join(f'<li><a href="#{e(i)}">{e(n)}</a></li>' for n, i in az) + "</ul>"
    corpo = f"""<div class="texto">
<p class="data-regra"><strong>Definições conferidas em {dlong(g.get('conferido_em', CONFERIDO))}.</strong> Quando um termo envolve regra legal (imposto, garantia, prazo mínimo), a fonte oficial aparece logo abaixo da definição.</p>
<nav aria-label="Grupos do glossário"><ul class="grupos-glo">{"".join(nav)}</ul></nav>
<h2 id="a-z">De A a Z</h2>
{indice}
{"".join(secoes)}
</div>
"""
    t = f"Glossário do investidor: {total} termos explicados · {B.NOME}"
    if len(t) > B.TITULO_MAX:
        t = f"Glossário do investidor: {total} termos explicados"
    desc = (f"{total} termos do mercado explicados sem jargão: CDI, Selic, IPCA+, come-cotas, DARF, data com, P/VP, ROE, "
            "dividend yield, JCP, marcação a mercado e mais.")
    if len(desc) > B.DESCRICAO_MAX:
        desc = desc[:B.DESCRICAO_MAX - 1].rsplit(",", 1)[0] + "."
    ld = [{"@context": "https://schema.org", "@type": "DefinedTermSet", "@id": f"{B.DOMINIO}/glossario.html", "name": "Glossário do Mercado na Lupa",
           "url": f"{B.DOMINIO}/glossario.html", "inLanguage": "pt-BR", "hasDefinedTerm": termos_ld}]
    return t, desc, pagina(D, "glossario.html", t, desc, "Glossário do investidor",
                           f"{total} termos de juros, renda fixa, bolsa, fundos e imposto de renda, explicados para quem está começando — com links para os dados e os guias do site.",
                           corpo, None, og, ld, foto="viva-voz", atual="glossario")


# --- valores para os simuladores ------------------------------------------------------------

def valores_calc(D):
    """Placeholders {{NOME}} usados nas calculadoras (_src/paginas/calculadoras/*.html)."""
    I, td = D["I"], D["td"]
    tit = [{"t": t["tipo"], "v": t["vencimento"], "c": t["taxa_compra"]} for t in td["titulos"]
           if t["tipo"] in ("Tesouro Selic", "Tesouro Prefixado", "Tesouro IPCA+") and t["taxa_compra"] is not None]
    return {
        "CDI_ANO": B.br(I["cdi"]["ano"]), "CDI_DATA": dbr(I["cdi"]["data"]),
        "SELIC_ANO": B.br(I["selic"]["ano"]), "SELIC_DATA": dbr(I["selic"]["data"]),
        "SELIC_META": B.br(I["meta"]["valor"]), "SELIC_META_DATA": dbr(I["meta"]["data"]),
        "IPCA12": B.br(I["ipca"]["doze"]), "IPCA12_REF": mes_ref(I["ipca"]["ref"]),
        "TR_MES": B.br(I["poup"]["tr"], 4), "TR_DATA": dbr(I["poup"]["tr_ini"]),
        "POUP_MES": B.br(I["poup"]["valor"], 4),
        "TD_DATA": dbr(td["data_base"]), "TD_TITULOS": json.dumps(tit, ensure_ascii=False, separators=(",", ":")),
        "CONFERIDO": dbr(CONFERIDO), "CONFERIDO_LONGO": dlong(CONFERIDO),
    }


def injetar(texto, vals):
    def troca(m):
        k = m.group(1)
        if k not in vals:
            B.falha(f"placeholder desconhecido {{{{{k}}}}}")
        return vals[k]
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", troca, texto)


# --- status ---------------------------------------------------------------------------

def status_html(D):
    S, td, bcb = D["S"], D["td"], D["bcb"]
    lin = []
    for k, s in S.items():
        ok = s.get("ok", True) and not s.get("problema")
        if s.get("problema"):
            situ = f"Com problema: {e(s['problema'])} — publicado o último dado bom"
        else:
            situ = "OK" if ok else f"Falhou em {e(s.get('falhou_em', ''))}: {e(s.get('erro', ''))}"
        ult_p = s["pontos"][-1] if s.get("pontos") else None
        lin.append(f'<tr{"" if ok else " class=\"atrasado\""}><td>{e(s["nome"])}</td><td class="n">{e(s["sgs"])}</td>'
                   f'<td class="n">{dbr(ult_p[0]) if ult_p else "—"}</td><td>{situ}</td></tr>')
    ok_td = td.get("ok", True) and not td.get("problema")
    if td.get("problema"):
        situ_td = f"Com problema: {e(td['problema'])} — publicado o último dado bom"
    else:
        situ_td = "OK" if ok_td else f"Falhou em {e(td.get('falhou_em', ''))}: {e(td.get('erro', ''))}"
    return f"""<h2 id="indicadores">Indicadores do Banco Central</h2>
<p class="data-regra">Última coleta: {coletado(bcb)} (Brasília). Série que falha mantém o último dado bom.</p>
<div class="rolagem"><table class="tabela-status"><caption>Séries do SGS e PTAX</caption><thead><tr><th>Série</th><th class="n">Código</th><th class="n">Último dado</th><th>Situação</th></tr></thead><tbody>
{"".join(lin)}
</tbody></table></div>
<h2 id="tesouro">Tesouro Direto (Tesouro Transparente)</h2>
<dl class="ficha"><dt>Data-base</dt><dd class="num">{dbr(td['data_base'])}</dd><dt>Títulos</dt><dd class="num">{len(td['titulos'])}</dd>
<dt>Coletado em</dt><dd class="num">{e(td.get('coletado_em', '—'))}</dd><dt>Situação</dt><dd>{situ_td}</dd></dl>
"""
