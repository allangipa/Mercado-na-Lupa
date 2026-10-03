#!/usr/bin/env python3
"""Gera o site do Mercado na Lupa.

    python _src/build.py        (a partir da raiz do site)

Lê:
    _src/ativos.json                 a lista de ativos acompanhados
    dados/cotacoes/<CODIGO>.csv      fechamentos da B3 (escritos por _src/atualiza.py)
    dados/pregoes.csv, dados/papeis.json
    dados/cadastro.json              cadastro da CVM (escrito por _src/cvm.py)
    _src/paginas/guias/*.html        guias (front matter JSON no 1º comentário)
    _src/paginas/calculadoras/*.html calculadoras
    _src/eventos.json                (opcional) eventos que explicam variação anormal

Escreve na raiz: index.html, ativos.html, guias.html, calculadoras.html,
ativos/*.html, guias/*.html, calculadoras/*.html, sobre, contato, privacidade,
404, sitemap.xml, robots.txt, ads.txt, assets/marca/*, assets/img/og-*.jpg.

Nunca edite os .html gerados: o próximo build apaga a mudança.

O build é PORTEIRO. Ele PARA quando:
  - falta cotação ou cadastro de um ativo da lista;
  - uma variação diária passa de 25% sem um evento declarado em
    _src/eventos.json (desdobramento, grupamento): número estranho não sai;
  - título passa de 60 caracteres ou repete; descrição fora de 120–155 ou repete;
  - o texto público tem linguagem de recomendação ("compre", "venda",
    "preço-alvo", "carteira recomendada"…);
  - um guia não tem fontes, ou uma página tem link interno quebrado.
"""
import csv
import datetime as dt
import html
import json
import math
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "_src"
DADOS = RAIZ / "dados"
IMG = RAIZ / "assets" / "img"
MARCA = RAIZ / "assets" / "marca"
TTF = SRC / "fontes-ttf"

DOMINIO = "https://mercadonalupa.com.br"
NOME = "Mercado na Lupa"
EMAIL = "allangipa@gmail.com"

# AdSense — mesmo publisher dos outros sites. ADSENSE_LIGADO = False tira
# tudo de todas as páginas e apaga o ads.txt: é o interruptor geral.
ADSENSE_LIGADO = True
ADSENSE_PUB = "pub-4401770243539507"
CONSENTIMENTO_BLOQUEIA = False
CHAVE_CONSENTIMENTO = "ml-consentimento"

TITULO_MAX = 60
DESCRICAO_MIN, DESCRICAO_MAX = 120, 155
VARIACAO_MAX = 25.0  # % num pregão; acima disso o build para sem evento declarado

AVISO_FIXO = "Conteúdo educativo, não é recomendação de investimento. Dados com atraso."

# Linguagem que este site não usa. Vale para o texto visível de toda página.
RECOMENDACAO = re.compile(
    r"\b(compre|comprem|venda j[áa]|vale a pena comprar|hora de comprar|hora de vender|"
    r"pre[çc]o[- ]alvo|carteira recomendada|recomendamos|recomendação de compra|"
    r"melhores a[çc][õo]es para|melhores fiis? para|a[çc][ãa]o barata|oportunidade de compra|"
    r"nota \d|aposta certa|vai subir|vai cair|potencial de valoriza[çc][ãa]o)\b", re.I)

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES_LONGO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
               "setembro", "outubro", "novembro", "dezembro"]

e = lambda s: html.escape(str(s), quote=True)


def falha(msg):
    raise SystemExit("PARADO: " + msg)


# --- números em português ----------------------------------------------------

def br(v, casas=2):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v):
    return "R$ " + br(v)


def compacto(v, moeda=False):
    """2.893.683.494 -> 2,89 bi."""
    pref = "R$ " if moeda else ""
    for lim, suf in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(v) >= lim:
            return f"{pref}{br(v / lim)}{suf}"
    return pref + br(v, 2 if moeda else 0)


def inteiro(v):
    return br(v, 0)


def data_br(d):
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(d)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def data_longa(d):
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(d)
    return f"{d.day} de {MESES_LONGO[d.month - 1]} de {d.year}"


def mes_ano(d):
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(d)
    return f"{MESES_LONGO[d.month - 1]} de {d.year}"


def var_html(v, selo=False):
    if v is None:
        return '<span class="var zero">—</span>'
    if abs(v) < 0.005:
        cls, seta, txt = "zero", "", "0,00%"
    elif v > 0:
        cls, seta, txt = "alta", "▲ ", "+" + br(v) + "%"
    else:
        cls, seta, txt = "baixa", "▼ ", "−" + br(-v) + "%"
    sel = " selo-var" if selo else ""
    return f'<span class="var {cls}{sel}">{seta}{txt}</span>'


# --- carga dos dados -------------------------------------------------------------

def ler_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def carregar():
    lista = ler_json(SRC / "ativos.json")
    papeis = ler_json(DADOS / "papeis.json")
    cad = ler_json(DADOS / "cadastro.json")
    eventos = ler_json(SRC / "eventos.json") if (SRC / "eventos.json").exists() else {}
    with (DADOS / "pregoes.csv").open(encoding="utf-8") as f:
        pregoes = [l["data"] for l in csv.DictReader(f)]
    if not pregoes:
        falha("dados/pregoes.csv vazio")
    ultimo = pregoes[-1]
    ativos = []
    for a in lista:
        c = a["codigo"]
        arq = DADOS / "cotacoes" / f"{c}.csv"
        if not arq.exists():
            falha(f"{c}: sem dados/cotacoes/{c}.csv — rode _src/atualiza.py")
        if c not in papeis:
            falha(f"{c}: sem entrada em dados/papeis.json")
        if c not in cad["ativos"]:
            falha(f"{c}: sem cadastro da CVM — rode _src/cvm.py")
        with arq.open(encoding="utf-8") as f:
            rows = []
            for l in csv.DictReader(f):
                rows.append({"data": l["data"], **{k: float(l[k]) for k in
                             ("abertura", "maxima", "minima", "media", "fechamento", "volume")},
                             "negocios": int(l["negocios"]), "quantidade": int(l["quantidade"])})
        if len(rows) < 2:
            falha(f"{c}: menos de dois pregões gravados")
        ev = eventos.get(c, {})
        for ant, cur in zip(rows, rows[1:]):
            v = (cur["fechamento"] / ant["fechamento"] - 1) * 100
            cur["var"] = None if cur["data"] in ev else v
            if abs(v) > VARIACAO_MAX and cur["data"] not in ev:
                falha(f"{c} {cur['data']}: variação de {v:+.1f}% num pregão. Se for desdobramento, "
                      "grupamento ou outro evento, declare em _src/eventos.json; se não, confira o arquivo da B3.")
        rows[0]["var"] = None
        u = rows[-1]
        tipo = a["tipo"]
        if tipo not in ("acao", "fii") or papeis[c]["fii"] != (tipo == "fii"):
            falha(f"{c}: tipo {tipo!r} em ativos.json não bate com o código BDI da B3")
        ativos.append({"codigo": c, "slug": c.lower(), "tipo": tipo, "nome": a["nome"], "rows": rows, "ult": u,
                       "ant": rows[-2], "papel": papeis[c], "cad": cad["ativos"][c],
                       "negociou_ultimo": u["data"] == ultimo, "evento": ev})
    return ativos, pregoes, ultimo, cad


ESPECIE = {"ON": "ordinárias (ON)", "PN": "preferenciais (PN)", "PNA": "preferenciais classe A (PNA)",
           "PNB": "preferenciais classe B (PNB)", "UNT": "units (UNT)", "CI": "cotas (CI)"}
SEGMENTO = {"NM": "Novo Mercado", "N1": "Nível 1", "N2": "Nível 2", "MA": "Bovespa Mais", "M2": "Bovespa Mais Nível 2"}


def especificacao(a):
    toks = a["papel"]["especificacao"].split()
    esp = ESPECIE.get(toks[0], toks[0]) if toks else ""
    seg = next((SEGMENTO[t] for t in toks[1:] if t in SEGMENTO), None)
    return esp, seg


def nome_curto(a):
    """Petrobras PN, Vale ON, FII Maxi Renda… O nome curto vem de
    _src/ativos.json ("nome"), escrito à mão: o da CVM é razão social, e o da
    B3 é abreviado em 12 letras ("ITAUUNIBANCO")."""
    if a["tipo"] == "acao":
        return f"{a['nome']} {a['papel']['especificacao'].split()[0]}"
    return a["nome"]


def janela(rows, dias):
    fim = dt.date.fromisoformat(rows[-1]["data"])
    ini = (fim - dt.timedelta(days=dias)).isoformat()
    return [r for r in rows if r["data"] > ini]


# --- gráfico SVG ---------------------------------------------------------------

def passo_bonito(amp, n=4):
    if amp <= 0:
        return 1
    bruto = amp / n
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def svg_grafico(a, rows, classe, rotulo):
    W, H, x0, x1, y0, y1 = 720, 330, 82, 708, 16, 282
    vals = [r["fechamento"] for r in rows]
    lo, hi = min(vals), max(vals)
    p = passo_bonito(hi - lo)
    ymin = math.floor(lo / p) * p
    ymax = math.ceil(hi / p) * p
    if ymax == ymin:
        ymax = ymin + p
    n = len(rows)
    X = lambda i: x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5)
    Y = lambda v: y1 - (y1 - y0) * (v - ymin) / (ymax - ymin)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    area = f"M{X(0):.1f},{y1} L" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)) + f" L{X(n-1):.1f},{y1} Z"
    grade = []
    v = ymin
    casas = 2 if p < 1 else (1 if p < 10 and p != int(p) else 0)
    while v <= ymax + 1e-9:
        y = Y(v)
        grade.append(f'<line class="grade-y" x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text x="{x0 - 10}" y="{y + 7:.1f}" text-anchor="end">{br(v, casas)}</text>')
        v += p
    # rótulos do eixo x: começo de mês (períodos longos) ou a cada ~5 pregões
    xs = []
    if classe == "g-1m":
        for i in range(0, n, max(1, n // 4)):
            d = dt.date.fromisoformat(rows[i]["data"])
            xs.append((i, f"{d.day:02d}/{d.month:02d}"))
    else:
        mes_ant = None
        passo = 1 if classe == "g-6m" else 2
        cont = 0
        for i, r in enumerate(rows):
            d = dt.date.fromisoformat(r["data"])
            if d.month != mes_ant:
                if mes_ant is not None and cont % passo == 0 and i > 2:
                    xs.append((i, MESES[d.month - 1] + ("/" + str(d.year)[2:] if d.month == 1 else "")))
                if mes_ant is not None:
                    cont += 1
                mes_ant = d.month
    eixo = "".join(f'<text x="{X(i):.1f}" y="{H - 14}" text-anchor="middle">{e(t)}</text>' for i, t in xs)
    i_min, i_max = vals.index(lo), vals.index(hi)
    marca = f'<circle class="ponto" cx="{X(n-1):.1f}" cy="{Y(vals[-1]):.1f}" r="6"/>'
    tid = f"t-{a['slug']}-{classe}"
    titulo = (f"{a['codigo']}: fechamento diário de {data_br(rows[0]['data'])} a {data_br(rows[-1]['data'])}. "
              f"Mínimo de {brl(lo)} em {data_br(rows[i_min]['data'])}, máximo de {brl(hi)} em {data_br(rows[i_max]['data'])}.")
    return (f'<svg class="{classe}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{tid}">'
            f'<title id="{tid}">{e(titulo)}</title>{"".join(grade)}<path class="area" d="{area}"/>'
            f'<polyline class="linha" points="{pts}"/>{marca}{eixo}</svg>'), (lo, hi, rows[i_min]["data"], rows[i_max]["data"])


def bloco_grafico(a):
    periodos = [("12m", "12 meses", 366), ("6m", "6 meses", 183), ("1m", "1 mês", 31)]
    svgs, legendas = [], []
    for k, nome, dias in periodos:
        rs = janela(a["rows"], dias)
        s, (lo, hi, dlo, dhi) = svg_grafico(a, rs, f"g-{k}", nome)
        svgs.append(s)
    return ('<div class="grafico">'
            # os rádios precisam ser irmãos de .paineis: o CSS liga cada um ao seu SVG
            + "".join(f'<input type="radio" class="sr" name="per-{a["slug"]}" id="p-{k}"{" checked" if k == "12m" else ""}>' for k, _, _ in periodos)
            + '<div class="periodos" role="group" aria-label="Período do gráfico">'
            + "".join(f'<label for="p-{k}">{nome}</label>' for k, nome, _ in periodos)
            + '</div><div class="paineis">' + "".join(svgs) + '</div>'
            + '<p class="legenda">Preço de fechamento diário, em reais, sem ajuste por proventos, desdobramentos ou grupamentos. '
              'Fonte: B3, série histórica de cotações.</p></div>')


# --- peças comuns --------------------------------------------------------------

LUPA_SVG = ('<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
            '<circle cx="27" cy="27" r="19" fill="var(--papel)"/>'
            '<path d="M14.5 33.5 L21.5 26.5 L27 30 L36.5 19.5" fill="none" stroke="var(--tinta)" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>'
            '<circle cx="36.5" cy="19.5" r="3.1" fill="var(--ouro)"/>'
            '<circle cx="27" cy="27" r="19" fill="none" stroke="var(--acao)" stroke-width="5"/>'
            '<path d="M41 41 L56 56" stroke="var(--tinta)" stroke-width="7.5" stroke-linecap="round"/></svg>')

# Arquivo do ícone (favicon), com cores fixas.
LUPA_ARQUIVO = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                '<circle cx="27" cy="27" r="19" fill="#fff"/>'
                '<path d="M14.5 33.5 L21.5 26.5 L27 30 L36.5 19.5" fill="none" stroke="#0F1B2D" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>'
                '<circle cx="36.5" cy="19.5" r="3.1" fill="#B7791F"/>'
                '<circle cx="27" cy="27" r="19" fill="none" stroke="#1D4ED8" stroke-width="5"/>'
                '<path d="M41 41 L56 56" stroke="#0F1B2D" stroke-width="7.5" stroke-linecap="round"/></svg>\n')


def adsense_head():
    if not ADSENSE_LIGADO:
        return "<!-- AdSense desligado em _src/build.py -->"
    return (f'<meta name="google-adsense-account" content="ca-{ADSENSE_PUB}">\n'
            '<link rel="preconnect" href="https://pagead2.googlesyndication.com" crossorigin>')


def consentimento(base):
    """A faixa de cookies. O script do AdSense não fica no HTML: entra por
    aqui, e só quando pode — mesmo desenho dos outros sites da casa."""
    if not ADSENSE_LIGADO:
        return ""
    return f"""<div class="consentimento" id="consentimento" role="dialog" aria-live="polite" aria-label="Aviso de cookies" hidden>
  <div class="casca">
    <p>Este site usa cookies do Google AdSense para exibir anúncios e medir audiência. Não pedimos cadastro nem e-mail, e as calculadoras não enviam o que você digita. Detalhes na <a href="{base}privacidade.html">política de privacidade</a>.</p>
    <div class="botoes">
      <button type="button" data-consent="recusar">Recusar anúncios</button>
      <button type="button" data-consent="aceitar" class="principal">Entendi</button>
    </div>
  </div>
</div>
<script>
(function(){{
  var CHAVE='{CHAVE_CONSENTIMENTO}', PUB='{ADSENSE_PUB}', BLOQUEIA={'true' if CONSENTIMENTO_BLOQUEIA else 'false'};
  function ler(){{try{{return localStorage.getItem(CHAVE)}}catch(e){{return null}}}}
  function gravar(v){{try{{localStorage.setItem(CHAVE,v)}}catch(e){{}}}}
  function carrega(){{
    if(!PUB||document.getElementById('ads-google'))return;
    var s=document.createElement('script');s.id='ads-google';s.async=true;s.crossOrigin='anonymous';
    s.src='https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-'+PUB;
    document.head.appendChild(s);
  }}
  // "Rever escolha de cookies", no rodapé: apaga a escolha salva e recarrega.
  document.querySelectorAll('[data-rever-cookies]').forEach(function(a){{
    a.addEventListener('click',function(ev){{
      ev.preventDefault();
      try{{localStorage.removeItem(CHAVE)}}catch(e){{}}
      location.reload();
    }});
  }});
  var escolha=ler();
  if(escolha==='aceitar'||(escolha===null&&!BLOQUEIA))carrega();
  var caixa=document.getElementById('consentimento');
  if(escolha===null&&caixa){{
    caixa.hidden=false;
    caixa.addEventListener('click',function(ev){{
      var b=ev.target.closest('[data-consent]');if(!b)return;
      var v=b.dataset.consent;gravar(v);caixa.hidden=true;
      if(v==='aceitar')carrega();else{{var x=document.getElementById('ads-google');if(x)x.remove();}}
    }});
  }}
  // Europa, Reino Unido, Suíça: quem pergunta é a mensagem do Google (CMP
  // certificada). Se ela diz que o GDPR se aplica, esta faixa sai da frente.
  if(escolha===null&&caixa){{
    var n=0,t=setInterval(function(){{
      if(typeof window.__tcfapi==='function'){{
        clearInterval(t);
        window.__tcfapi('addEventListener',2,function(tc,ok){{if(ok&&tc&&tc.gdprApplies)caixa.hidden=true;}});
      }}else if(++n>40)clearInterval(t);
    }},250);
  }}
}})();
</script>
"""


CSS_INLINE = None


def css_inline():
    global CSS_INLINE
    if CSS_INLINE is None:
        css = (SRC / "site.css").read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        css = re.sub(r"\n\s*\n+", "\n", css).strip()
        # input de rádio visualmente escondido, mas acessível
        css += "\n.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
        CSS_INLINE = css
    return CSS_INLINE


def cabeca(titulo, descricao, url, imagem, base, jsonld, tipo="website", indexar=True):
    if indexar:
        canon = (f'<link rel="canonical" href="{e(url)}">\n'
                 '<meta name="robots" content="max-image-preview:large">')
    else:
        canon = '<meta name="robots" content="noindex, follow">'
    lds = jsonld if isinstance(jsonld, list) else [jsonld]
    ld = "\n".join(f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False)}</script>' for j in lds)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descricao)}">
{canon}
<meta name="theme-color" content="#0F1B2D">
<link rel="icon" href="{base}assets/marca/lupa.svg" type="image/svg+xml">
<link rel="icon" href="{base}assets/marca/lupa-64.png" type="image/png" sizes="64x64">
<link rel="apple-touch-icon" href="{base}assets/marca/lupa-180.png">
<link rel="preload" href="/assets/fontes/archivo-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fontes/plex-mono-latin-500.woff2" as="font" type="font/woff2" crossorigin>
{adsense_head()}
<style>{css_inline()}</style>
<meta property="og:type" content="{tipo}">
<meta property="og:site_name" content="{e(NOME)}">
<meta property="og:locale" content="pt_BR">
<meta property="og:title" content="{e(titulo)}">
<meta property="og:description" content="{e(descricao)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(imagem)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
{ld}
</head>
<body>
<a class="pular" href="#conteudo">Pular para o conteúdo</a>
"""


def topo(base, atual=""):
    cur = lambda k: ' aria-current="page"' if k == atual else ""
    return f"""<header class="topo">
  <div class="casca">
    <a class="marca" href="{base}index.html" aria-label="{NOME}, página inicial">{LUPA_SVG}<span>Mercado <i>na Lupa</i></span></a>
    <nav class="nav" aria-label="Principal">
      <a href="{base}ativos.html"{cur('ativos')}>Ativos</a>
      <a href="{base}guias.html"{cur('guias')}>Guias</a>
      <a href="{base}calculadoras.html"{cur('calculadoras')}>Calculadoras</a>
      <a href="{base}sobre.html"{cur('sobre')}>Sobre</a>
    </nav>
  </div>
</header>
"""


def linha_pregao(ultimo):
    return (f'<p class="pregao casca">Cotações de fechamento do pregão de {data_br(ultimo)}. '
            'Fonte: B3. Dados com atraso, apenas informativos.</p>')


def rodape(base, ultimo=None):
    rever = ' <a href="#" role="button" data-rever-cookies>Rever escolha de cookies</a>.' if ADSENSE_LIGADO else ""
    pregao = linha_pregao(ultimo) if ultimo else ""
    return f"""{pregao}<footer class="rodape">
  <div class="casca">
    <div>
      <h2>{NOME}</h2>
      <p>Dados públicos do mercado brasileiro — cotações da B3 e cadastros da CVM — explicados para quem está começando. Com fonte, sem palpite.</p>
    </div>
    <div>
      <h2>Navegue</h2>
      <ul>
        <li><a href="{base}ativos.html">Ativos acompanhados</a></li>
        <li><a href="{base}guias.html">Guias</a> · <a href="{base}calculadoras.html">Calculadoras</a></li>
        <li><a href="{base}sobre.html">Sobre</a> · <a href="{base}contato.html">Contato</a></li>
      </ul>
    </div>
    <div>
      <h2>Este site</h2>
      <ul>
        <li>Exibe anúncios do Google AdSense. <a href="{base}privacidade.html">Política de privacidade</a>.{rever}</li>
        <li>Da mesma casa: <a href="https://guiaprodutonalupa.com.br" rel="noopener">Guia Produto na Lupa</a> e <a href="https://viagemnalupa.com.br" rel="noopener">Viagem na Lupa</a>.</li>
      </ul>
    </div>
    <p class="fixo"><strong>Conteúdo educativo, não é recomendação de investimento.</strong> Dados com atraso. Nada aqui é oferta, análise ou indicação de compra ou venda de valores mobiliários. Decisões de investimento são de quem as toma.</p>
  </div>
</footer>
"""


JS_COMUM = r"""
function lerNum(s){s=String(s).trim().replace(/\s|R\$|%/g,'');if(!s)return NaN;
 if(s.indexOf(',')>=0)s=s.replace(/\./g,'').replace(',','.');
 else if(/^-?\d{1,3}(\.\d{3})+$/.test(s))s=s.replace(/\./g,'');
 return /^-?\d*\.?\d+$/.test(s)?parseFloat(s):NaN}
function fmt(v,c){return v.toLocaleString('pt-BR',{minimumFractionDigits:c,maximumFractionDigits:c})}
function brl(v){return 'R$ '+fmt(v,2)}
function pct(v,c){return fmt(v,c==null?2:c)+'%'}
function duracao(m){var a=Math.floor(m/12),r=m%12,p=[];
 if(a)p.push(a+(a===1?' ano':' anos'));if(r)p.push(r+(r===1?' mês':' meses'));return p.join(' e ')||'0 meses'}
"""


def fim(extra=""):
    return (f"<script>{extra}</script>\n" if extra else "") + "</body>\n</html>\n"


def migalhas_ld(*itens):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": u}
                                for i, (n, u) in enumerate(itens, start=1)]}


def migalhas_html(base, *itens):
    partes = [f'<a href="{base}index.html">Início</a>']
    for nome, href in itens[:-1]:
        partes.append(f'<a href="{href}">{e(nome)}</a>')
    partes.append(f'<span aria-current="page">{e(itens[-1][0])}</span>')
    return '<nav class="migalhas" aria-label="Você está em">' + " › ".join(partes) + "</nav>"


ORG = {"@type": "Organization", "name": NOME, "url": DOMINIO + "/",
       "logo": {"@type": "ImageObject", "url": f"{DOMINIO}/assets/marca/lupa-512.png", "width": 512, "height": 512},
       "email": EMAIL}


# --- imagens: ícones e og -------------------------------------------------------

def fonte(nome, tam):
    return ImageFont.truetype(str(TTF / nome), tam)


def desenha_lupa(tam, fundo=None, cabo="#0F1B2D"):
    """Mesma geometria do SVG, desenhada em 4x e reduzida (borda lisa)."""
    k = 4
    S = tam * k
    im = Image.new("RGBA", (S, S), fundo or (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = S / 64
    P = lambda x, y: (x * u, y * u)
    d.ellipse([P(8, 8), P(46, 46)], fill="#FFFFFF")
    d.line([P(14.5, 33.5), P(21.5, 26.5), P(27, 30), P(36.5, 19.5)], fill="#0F1B2D", width=int(3.4 * u), joint="curve")
    for x, y in ((14.5, 33.5), (36.5, 19.5)):
        r = 1.7 * u
        d.ellipse([x * u - r, y * u - r, x * u + r, y * u + r], fill="#0F1B2D")
    r = 3.1 * u
    d.ellipse([36.5 * u - r, 19.5 * u - r, 36.5 * u + r, 19.5 * u + r], fill="#B7791F")
    w = 5 * u
    d.ellipse([P(8, 8)[0] - w / 2 + 0, P(8, 8)[1] - w / 2, P(46, 46)[0] + w / 2, P(46, 46)[1] + w / 2], outline="#1D4ED8", width=int(w))
    d.line([P(41, 41), P(56, 56)], fill=cabo, width=int(7.5 * u))
    r = 3.75 * u
    for x, y in ((41, 41), (56, 56)):
        d.ellipse([x * u - r, y * u - r, x * u + r, y * u + r], fill=cabo)
    return im.resize((tam, tam), Image.LANCZOS)


def gerar_marca():
    MARCA.mkdir(parents=True, exist_ok=True)
    (MARCA / "lupa.svg").write_text(LUPA_ARQUIVO, encoding="utf-8")
    for t in (64, 180, 512):
        fundo = (255, 255, 255, 255) if t == 180 else None
        desenha_lupa(t, fundo).save(MARCA / f"lupa-{t}.png", optimize=True)


def og(nome_arq, rotulo, titulo, sub):
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#0F1B2D")
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 10, W, H], fill="#1D4ED8")
    lupa = desenha_lupa(150, cabo="#E7ECF3")
    im.paste(lupa, (W - 150 - 70, 70), lupa)
    d.text((80, 92), "MERCADO NA LUPA", font=fonte("IBMPlexMono-SemiBold.ttf", 30), fill="#8DB2FF")
    d.text((80, 150), rotulo, font=fonte("Archivo-Regular.ttf", 30), fill="#A9B4C4")
    # título quebrado em até 3 linhas
    f = fonte("Fraunces-SemiBold.ttf", 76 if len(titulo) < 30 else 62)
    linhas, atual = [], ""
    for p in titulo.split():
        t = (atual + " " + p).strip()
        if d.textlength(t, font=f) > W - 160 - 40 and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    linhas.append(atual)
    y = 230
    for l in linhas[:3]:
        d.text((80, y), l, font=f, fill="#E7ECF3")
        y += int(f.size * 1.15)
    d.text((80, H - 90), sub, font=fonte("Archivo-Regular.ttf", 28), fill="#A9B4C4")
    IMG.mkdir(parents=True, exist_ok=True)
    im.save(IMG / nome_arq, "JPEG", quality=84, optimize=True, progressive=True)
    return f"{DOMINIO}/assets/img/{nome_arq}"


# --- conteúdo em arquivo (guias e calculadoras) ------------------------------------

def ler_pagina(arq):
    txt = arq.read_text(encoding="utf-8")
    m = re.match(r"\s*<!--(\{.*?\})-->\s*", txt, re.S)
    if not m:
        falha(f"{arq.name}: falta o front matter JSON no primeiro comentário")
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError as ex:
        falha(f"{arq.name}: front matter inválido: {ex}")
    for k in ("titulo", "descricao", "h1", "resumo", "publicado", "atualizado", "fontes"):
        if k not in meta:
            falha(f"{arq.name}: front matter sem '{k}'")
    corpo = txt[m.end():]
    script = ""
    s = re.search(r"<script>(.*?)</script>\s*$", corpo, re.S)
    if s:
        script, corpo = s.group(1), corpo[:s.start()]
    meta.update(slug=arq.stem, corpo=corpo, script=script, arquivo=arq)
    return meta


def conferir_texto(nome, html_txt):
    """Trava de linguagem de recomendação, no texto visível."""
    visivel = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html_txt, flags=re.S)
    visivel = html.unescape(visivel)
    for m in RECOMENDACAO.finditer(visivel):
        antes = visivel[max(0, m.start() - 70):m.start()]
        # menção negada ("não dá preço-alvo", "nem nota") é o site dizendo o que NÃO faz
        if re.search(r"\bn[ãa]o\b|\bnem\b|\bsem\b", antes, re.I):
            continue
        ctx = visivel[max(0, m.start() - 60):m.end() + 60].replace("\n", " ")
        falha(f"{nome}: linguagem de recomendação ({m.group(0)!r}): …{ctx}…")


# --- páginas -------------------------------------------------------------------

def titulo_ativo(a):
    nc = nome_curto(a)
    for t in (f"{a['codigo']} ({nc}): cotação e histórico · {NOME}",
              f"{a['codigo']}: cotação de fechamento e histórico · {NOME}",
              f"{a['codigo']}: cotação e histórico · {NOME}"):
        if len(t) <= TITULO_MAX:
            return t
    falha(f"{a['codigo']}: sem título de até {TITULO_MAX}")


def descricao_ativo(a):
    nc = nome_curto(a)
    tipo = "da ação" if a["tipo"] == "acao" else "da cota do fundo imobiliário"
    for d in (f"Cotação de fechamento {tipo} {a['codigo']} ({nc}) na B3: variação do dia, mínima, máxima, volume, gráfico de 12 meses e dados da CVM.",
              f"Fechamento de {a['codigo']} ({nc}) na B3: variação, mínima, máxima, volume, gráfico de 12 meses e cadastro da CVM.",
              f"Cotação de fechamento de {a['codigo']} na B3: variação do dia, mínima, máxima, volume, gráfico de 12 meses e dados públicos da CVM."):
        if DESCRICAO_MIN <= len(d) <= DESCRICAO_MAX:
            return d
    falha(f"{a['codigo']}: sem descrição entre {DESCRICAO_MIN} e {DESCRICAO_MAX}")


def texto_ativo(a):
    c, cad = a["codigo"], a["cad"]
    esp, seg = especificacao(a)
    isin = a["papel"]["isin"]
    if a["tipo"] == "acao":
        p1 = (f"A <strong>{e(cad['razao_social'])}</strong> é uma companhia aberta registrada na Comissão de Valores "
              f"Mobiliários (CVM) desde {data_br(cad['registro_cvm'])}, sob o código CVM {e(cad['codigo_cvm'])}, "
              f"com sede em {e(cad['municipio'])} ({e(cad['uf'])}). No cadastro da CVM, o setor de atividade "
              f"informado é “{e(cad['setor'])}”.")
        p2 = (f"<strong>{c}</strong> é o código de negociação das ações {esp} da companhia na B3"
              + (f", no segmento de listagem {seg}" if seg else "") + f". O código ISIN do papel é {isin}.")
        if esp.startswith("ordinárias"):
            p3 = "Ações ordinárias dão direito a voto nas assembleias de acionistas."
        elif esp.startswith("preferenciais"):
            p3 = ("Ações preferenciais, em regra, não dão direito a voto, e têm em troca alguma preferência prevista "
                  "em lei e no estatuto, como prioridade no recebimento de dividendos.")
        else:
            p3 = ""
        return f"<p>{p1}</p><p>{p2} {p3}</p>"
    ref = mes_ano(cad["referencia"])
    p1 = (f"O <strong>{e(cad['razao_social'])}</strong> é um fundo de investimento imobiliário (CNPJ {e(cad['cnpj'])}) "
          f"em funcionamento desde {data_br(cad['inicio_funcionamento'])}, administrado por {e(cad['administrador'].title())}. "
          f"No informe mensal entregue à CVM referente a {ref}, o fundo declarou {inteiro(cad['cotistas'])} cotistas, "
          f"patrimônio líquido de {compacto(cad['patrimonio_liquido'], True)} e valor patrimonial de "
          f"{brl(cad['vp_cota'])} por cota.")
    # Segmento de atuação fora (decisão do dono, 03/10/2026): o campo do informe da CVM
    # nem sempre bate com a estratégia do fundo (ex.: MXRF11 aparecia como "Logística").
    p2 = (f"A gestão é declarada como {e(cad['gestao'].lower())}. <strong>{c}</strong> é o código de negociação das cotas na B3, "
          f"com ISIN {isin}.")
    return f"<p>{p1}</p><p>{p2}</p>"


def ficha_ativo(a):
    cad = a["cad"]
    esp, seg = especificacao(a)
    linhas = [("Razão social", cad["razao_social"]), ("CNPJ", cad["cnpj"])]
    if a["tipo"] == "acao":
        linhas += [("Código CVM", cad["codigo_cvm"]), ("Setor (CVM)", cad["setor"]),
                   ("Controle acionário (CVM)", cad["controle"].capitalize()),
                   ("Sede", f"{cad['municipio']} ({cad['uf']})"),
                   ("Registro na CVM", data_br(cad["registro_cvm"])),
                   ("Espécie", esp)]
        if seg:
            linhas.append(("Segmento de listagem", seg))
    else:
        dy = cad.get("dy_mes")
        linhas += [("Administrador", cad["administrador"].title()), ("Início de funcionamento", data_br(cad["inicio_funcionamento"])),
                   ("Mandato", cad["mandato"] or "não informado"),
                   ("Público-alvo", cad["publico_alvo"].capitalize()),
                   (f"Cotistas ({mes_ano(cad['referencia'])})", inteiro(cad["cotistas"])),
                   ("Cotas emitidas", inteiro(cad["cotas_emitidas"])),
                   ("Patrimônio líquido", compacto(cad["patrimonio_liquido"], True)),
                   ("Valor patrimonial por cota", brl(cad["vp_cota"]))]
        if dy is not None:
            linhas.append((f"Dividend yield do mês informado à CVM", br(dy * 100) + "%"))
    linhas += [("Código ISIN", a["papel"]["isin"]), ("Nome no pregão (B3)", a["papel"]["nome_pregao"])]
    return '<dl class="ficha">' + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in linhas) + "</dl>"


def pagina_ativo(a, todos, ultimo, og_url):
    base = "../"
    c, u, ant = a["codigo"], a["ult"], a["ant"]
    url = f"{DOMINIO}/ativos/{a['slug']}.html"
    titulo, desc = titulo_ativo(a), descricao_ativo(a)
    nc = nome_curto(a)
    tipo_txt = "Ação" if a["tipo"] == "acao" else "Fundo imobiliário"
    a12 = janela(a["rows"], 366)
    lo12 = min(r["minima"] for r in a12)
    hi12 = max(r["maxima"] for r in a12)
    aviso_neg = ""
    if not a["negociou_ultimo"]:
        aviso_neg = (f'<div class="aviso"><strong>Sem negócio no último pregão.</strong> {c} não foi negociado em lote padrão '
                     f'em {data_br(ultimo)}; os números abaixo são do último pregão em que houve negócio, {data_br(u["data"])}.</div>')
    ev_txt = ""
    if u["var"] is None and u["data"] in a["evento"]:
        ev_txt = f'<div class="aviso"><strong>Evento no papel:</strong> {e(a["evento"][u["data"]])}. A variação do dia não é comparável e não é exibida.</div>'
    numeros = [("Abertura", brl(u["abertura"])), ("Mínima do dia", brl(u["minima"])), ("Máxima do dia", brl(u["maxima"])),
               ("Preço médio", brl(u["media"])), ("Fechamento anterior", brl(ant["fechamento"])),
               ("Volume financeiro", compacto(u["volume"], True)), ("Negócios", inteiro(u["negocios"])),
               ("Quantidade negociada", compacto(u["quantidade"]))]
    nums = '<dl class="numeros">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in numeros) + "</dl>"
    ultimos = list(reversed(a["rows"][-10:]))
    tabela = ("<div class=\"rolagem\"><table><caption>Últimos 10 pregões com negócio</caption><thead><tr><th>Data</th>"
              "<th class=\"n\">Fechamento</th><th class=\"n\">Variação</th><th class=\"n\">Mínima</th><th class=\"n\">Máxima</th>"
              "<th class=\"n\">Volume</th></tr></thead><tbody>"
              + "".join(f"<tr><td class=\"n\">{data_br(r['data'])}</td><td class=\"n\">{br(r['fechamento'])}</td>"
                        f"<td class=\"n\">{var_html(r['var'])}</td><td class=\"n\">{br(r['minima'])}</td>"
                        f"<td class=\"n\">{br(r['maxima'])}</td><td class=\"n\">{compacto(r['volume'], True)}</td></tr>" for r in ultimos)
              + "</tbody></table></div>")
    if a["tipo"] == "acao":
        guias = [("o-que-e-p-l", "O que é P/L"), ("o-que-e-dividend-yield", "O que é dividend yield"),
                 ("como-funciona-o-imposto-de-renda-na-bolsa", "Como funciona o imposto de renda na bolsa")]
    else:
        guias = [("o-que-e-dividend-yield", "O que é dividend yield"),
                 ("como-funciona-o-imposto-de-renda-na-bolsa", "Imposto de renda em fundos imobiliários")]
    outros = [x for x in todos if x["tipo"] == a["tipo"] and x is not a]
    cad = a["cad"]
    fontes = [("B3 — Série histórica de cotações (arquivo COTAHIST do pregão)", "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/"),
              (cad["fonte"], cad["fonte_url"])]
    corpo = f"""<main id="conteudo"><div class="casca">
{migalhas_html(base, ("Ativos", base + "ativos.html"), (c, ""))}
<div class="cab-ativo">
  <div>
    <p class="rotulo tipo">{tipo_txt} · B3</p>
    <h1><span class="cod">{c}</span> — {e(nc)}</h1>
    <p class="razao">{e(cad['razao_social'])}</p>
  </div>
  <div class="preco">
    <div class="valor num"><small>R$</small>{br(u['fechamento'])}</div>
    <div style="margin-top:.5rem">{var_html(u['var'], selo=True)} <span class="quando">no dia</span></div>
    <p class="quando">Fechamento de {data_br(u['data'])}, comparado com {data_br(ant['data'])}</p>
  </div>
</div>
{aviso_neg}{ev_txt}
{nums}
<h2 id="grafico">Histórico de fechamento</h2>
{bloco_grafico(a)}
<p class="data-regra" style="margin-top:.8rem">Em 12 meses, o preço oscilou entre <span class="num">{brl(lo12)}</span> (mínima intradiária) e <span class="num">{brl(hi12)}</span> (máxima intradiária).</p>
<div class="grade grade-2" style="margin-top:1rem">
<section><h2 id="o-que-e">O que é {c}</h2>{texto_ativo(a)}</section>
<section><h2 id="ficha">Ficha</h2>{ficha_ativo(a)}</section>
</div>
<h2 id="pregoes">Últimos pregões</h2>
{tabela}
<h2 id="como-ler">Como ler esta página</h2>
<ul>
 <li><strong>Fechamento</strong> é o preço do último negócio do pregão no mercado à vista, em lote padrão, como publicado pela B3.</li>
 <li><strong>Variação do dia</strong> compara esse fechamento com o do pregão anterior em que houve negócio. Não há ajuste por proventos: no dia em que o papel fica “ex” um dividendo, a queda de preço aparece como variação.</li>
 <li><strong>Volume financeiro</strong> é a soma, em reais, de todos os negócios do dia com o papel.</li>
 <li>Os dados chegam <strong>depois do fechamento</strong>, uma vez por dia. Para cotação em tempo real, use o site da B3 ou da sua corretora.</li>
</ul>
<h2 id="guias">Para entender os números</h2>
<ul>{''.join(f'<li><a href="{base}guias/{s}.html">{t}</a></li>' for s, t in guias)}</ul>
<h2 id="outros">Outros {'ações' if a['tipo'] == 'acao' else 'fundos imobiliários'} acompanhados</h2>
<ul class="chips">{''.join(f'<li><a href="{x["slug"]}.html">{x["codigo"]}</a></li>' for x in outros)}</ul>
<h2 id="fontes">Fontes</h2>
<ul class="fontes">{''.join(f'<li><a href="{e(uu)}" rel="noopener">{e(t)}</a></li>' for t, uu in fontes)}
<li>Cadastro da CVM atualizado em {data_br(json.loads((DADOS / 'cadastro.json').read_text(encoding='utf-8'))['gerado_em'])}.</li></ul>
<div class="aviso"><strong>{AVISO_FIXO}</strong> Esta página reúne dados públicos sobre {c} e não é análise nem indicação de compra ou venda.</div>
</div></main>
"""
    sobre = ({"@type": "Corporation", "name": cad["razao_social"], "tickerSymbol": f"BVMF:{c}"} if a["tipo"] == "acao"
             else {"@type": "InvestmentFund", "name": cad["razao_social"]})
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": titulo, "description": desc, "url": url,
           "inLanguage": "pt-BR", "dateModified": u["data"], "about": sobre, "publisher": ORG},
          migalhas_ld((NOME, DOMINIO + "/"), ("Ativos", f"{DOMINIO}/ativos.html"), (c, url))]
    return cabeca(titulo, desc, url, og_url, base, ld) + topo(base, "ativos") + corpo + rodape(base, ultimo) + consentimento(base) + fim()


def destaques(ativos, ultimo):
    hoje = [a for a in ativos if a["negociou_ultimo"] and a["ult"]["var"] is not None]
    altas = sorted([a for a in hoje if a["ult"]["var"] > 0], key=lambda a: -a["ult"]["var"])[:3]
    baixas = sorted([a for a in hoje if a["ult"]["var"] < 0], key=lambda a: a["ult"]["var"])[:3]
    vol = sorted([a for a in ativos if a["negociou_ultimo"]], key=lambda a: -a["ult"]["volume"])[:3]

    def lista(xs, valor):
        if not xs:
            return '<p class="data-regra">Nenhum ativo da lista nesta condição no pregão.</p>'
        return '<ul class="lista-dest">' + "".join(
            f'<li><a href="ativos/{a["slug"]}.html">{a["codigo"]}</a><span class="nome">{e(nome_curto(a))}</span>{valor(a)}</li>'
            for a in xs) + "</ul>"
    return f"""<div class="grade grade-3 destaques">
  <section class="cartao"><h3>Maiores altas</h3>{lista(altas, lambda a: var_html(a['ult']['var']))}</section>
  <section class="cartao"><h3>Maiores baixas</h3>{lista(baixas, lambda a: var_html(a['ult']['var']))}</section>
  <section class="cartao"><h3>Mais negociados (volume)</h3>{lista(vol, lambda a: '<span class="num">' + compacto(a['ult']['volume'], True) + '</span>')}</section>
</div>"""


def tabela_ativos(ativos, base, caption):
    linhas = []
    for a in ativos:
        u = a["ult"]
        linhas.append(f'<tr><td><a href="{base}ativos/{a["slug"]}.html">{a["codigo"]}</a><br><span class="nome">{e(nome_curto(a))}</span></td>'
                      f'<td class="n">{br(u["fechamento"])}</td><td class="n">{var_html(u["var"])}</td>'
                      f'<td class="n">{compacto(u["volume"], True)}</td></tr>')
    return (f'<div class="rolagem"><table><caption>{caption}</caption><thead><tr><th>Ativo</th><th class="n">Fechamento (R$)</th>'
            '<th class="n">Variação</th><th class="n">Volume</th></tr></thead><tbody>' + "".join(linhas) + "</tbody></table></div>")


def cartoes(itens, base, pasta, rotulo):
    return '<ul class="cartoes grade grade-3">' + "".join(
        f'<li><a class="cartao" href="{base}{pasta}/{g["slug"]}.html"><span class="rotulo">{rotulo}</span><h3>{e(g["h1"])}</h3><p>{e(g["resumo"])}</p></a></li>'
        for g in itens) + "</ul>"


TITULO_HOME = f"{NOME}: cotações da B3, guias e calculadoras"
DESC_HOME = ("Cotações de fechamento da B3 explicadas, com histórico e dados da CVM, guias para quem está começando e "
             "calculadoras de juros. Educativo e com fonte.")


def home(ativos, ultimo, guias, calcs, og_url):
    base = ""
    busca_dados = json.dumps({a["codigo"]: f"ativos/{a['slug']}.html" for a in ativos})
    acoes = [a for a in ativos if a["tipo"] == "acao"]
    fiis = [a for a in ativos if a["tipo"] == "fii"]
    corpo = f"""<main id="conteudo"><div class="casca">
<section class="abertura">
  <p class="rotulo">Dados públicos · B3 e CVM</p>
  <h1>O mercado brasileiro, com lupa e com fonte.</h1>
  <p class="lead">Cotação de fechamento, histórico e cadastro oficial de ações e fundos imobiliários, explicados sem palpite. Para quem quer entender antes de decidir qualquer coisa.</p>
  <form class="busca" role="search" id="busca" action="ativos.html">
    <label for="cod" class="sr">Código do ativo</label>
    <input id="cod" name="q" autocomplete="off" spellcheck="false" placeholder="Digite um código, ex.: PETR4" list="codigos" maxlength="8">
    <datalist id="codigos">{''.join(f'<option value="{a["codigo"]}">{e(nome_curto(a))}</option>' for a in ativos)}</datalist>
    <button class="botao" type="submit">Ver</button>
  </form>
  <p class="busca-msg" id="busca-msg" aria-live="polite"></p>
  <ul class="chips">{''.join(f'<li><a href="ativos/{a["slug"]}.html">{a["codigo"]}</a></li>' for a in ativos)}</ul>
</section>

<h2 id="pregao">Destaques do pregão de {data_br(ultimo)}</h2>
<p class="data-regra">Entre os {len(ativos)} ativos acompanhados pelo site. É uma fotografia do dia, não um sinal: o que subiu hoje pode cair amanhã.</p>
{destaques(ativos, ultimo)}

<div class="grade grade-2" style="margin-top:1.4rem">
<section><h2>Ações</h2>{tabela_ativos(acoes, base, f"Fechamento em {data_br(ultimo)}")}</section>
<section><h2>Fundos imobiliários</h2>{tabela_ativos(fiis, base, f"Fechamento em {data_br(ultimo)}")}</section>
</div>

<h2 id="guias">Guias para começar</h2>
{cartoes(guias, base, "guias", "Guia")}
<h2 id="calculadoras">Calculadoras</h2>
{cartoes(calcs, base, "calculadoras", "Calculadora")}

<div class="aviso"><strong>{AVISO_FIXO}</strong> O {NOME} reúne e explica dados públicos. Não indica ativos, não monta carteira e não diz o que comprar ou vender.</div>
</div></main>
"""
    js = f"""(function(){{var M={busca_dados},f=document.getElementById('busca'),i=document.getElementById('cod'),m=document.getElementById('busca-msg');
f.addEventListener('submit',function(ev){{ev.preventDefault();var c=i.value.trim().toUpperCase().replace(/[^A-Z0-9]/g,'');
if(!c){{m.textContent='Digite um código de negociação, como PETR4 ou MXRF11.';return}}
if(M[c]){{location.href=M[c];return}}
m.textContent=c+' ainda não está na lista acompanhada pelo site. Os disponíveis estão logo abaixo.';}});}})();"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": NOME, "url": DOMINIO + "/", "inLanguage": "pt-BR",
           "description": DESC_HOME, "publisher": ORG}, {"@context": "https://schema.org", **ORG}]
    return cabeca(TITULO_HOME, DESC_HOME, DOMINIO + "/", og_url, base, ld) + topo(base) + corpo + rodape(base, ultimo) + consentimento(base) + fim(js)


TITULO_ATIVOS = f"Ações e fundos imobiliários acompanhados · {NOME}"
DESC_ATIVOS = ("Lista das ações e dos fundos imobiliários acompanhados pelo site, com o fechamento e a variação do último "
               "pregão da B3 e o histórico de cada um.")


def pagina_ativos(ativos, ultimo, og_url):
    base = ""
    acoes = [a for a in ativos if a["tipo"] == "acao"]
    fiis = [a for a in ativos if a["tipo"] == "fii"]
    corpo = f"""<main id="conteudo"><div class="casca">
{migalhas_html(base, ("Ativos", ""))}
<h1>Ativos acompanhados</h1>
<p class="lead">Nesta primeira versão, o site acompanha {len(acoes)} ações e {len(fiis)} fundos imobiliários entre os mais conhecidos da B3. A lista não é seleção nem recomendação: é o ponto de partida, e vai crescer.</p>
<h2>Ações</h2>{tabela_ativos(acoes, base, f"Fechamento em {data_br(ultimo)}")}
<h2>Fundos imobiliários</h2>{tabela_ativos(fiis, base, f"Fechamento em {data_br(ultimo)}")}
<div class="aviso"><strong>{AVISO_FIXO}</strong></div>
</div></main>
"""
    u = f"{DOMINIO}/ativos.html"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": TITULO_ATIVOS, "description": DESC_ATIVOS,
           "url": u, "inLanguage": "pt-BR"}, migalhas_ld((NOME, DOMINIO + "/"), ("Ativos", u))]
    return cabeca(TITULO_ATIVOS, DESC_ATIVOS, u, og_url, base, ld) + topo(base, "ativos") + corpo + rodape(base, ultimo) + consentimento(base) + fim()


def pagina_conteudo(g, pasta, rotulo_pasta, og_url, artigo):
    base = "../"
    url = f"{DOMINIO}/{pasta}/{g['slug']}.html"
    fontes = ""
    if g["fontes"]:
        fontes = ('<h2 id="fontes">Fontes</h2><ul class="fontes">'
                  + "".join(f'<li><a href="{e(f["url"])}" rel="noopener">{e(f["nome"])}</a></li>' for f in g["fontes"]) + "</ul>")
    datas = f'Publicado em {data_longa(g["publicado"])}' + (f' · atualizado em {data_longa(g["atualizado"])}' if g["atualizado"] != g["publicado"] else "")
    largura = "texto" if artigo else ""
    corpo = f"""<main id="conteudo"><div class="casca">
{migalhas_html(base, (rotulo_pasta, base + pasta + ".html"), (g['h1'], ""))}
<article class="{largura}">
<p class="rotulo">{'Guia' if artigo else 'Calculadora'} · {datas}</p>
<h1>{e(g['h1'])}</h1>
{g['corpo']}
{fontes}
</article>
</div></main>
"""
    tipo_ld = "Article" if artigo else "WebPage"
    ld0 = {"@context": "https://schema.org", "@type": tipo_ld, "name": g["titulo"], "description": g["descricao"], "url": url,
           "inLanguage": "pt-BR", "datePublished": g["publicado"], "dateModified": g["atualizado"], "publisher": ORG}
    if artigo:
        ld0.update(headline=g["h1"], author=ORG, image=og_url, mainEntityOfPage={"@type": "WebPage", "@id": url})
    ld = [ld0, migalhas_ld((NOME, DOMINIO + "/"), (rotulo_pasta, f"{DOMINIO}/{pasta}.html"), (g["h1"], url))]
    js = (JS_COMUM + g["script"]) if g["script"] else ""
    return cabeca(g["titulo"], g["descricao"], url, og_url, base, ld, tipo="article" if artigo else "website") \
        + topo(base, pasta) + corpo + rodape(base) + consentimento(base) + fim(js)


def pagina_hub(itens, pasta, titulo, desc, h1, lead, rotulo, og_url):
    base = ""
    u = f"{DOMINIO}/{pasta}.html"
    corpo = f"""<main id="conteudo"><div class="casca">
{migalhas_html(base, (h1, ""))}
<h1>{e(h1)}</h1>
<p class="lead">{lead}</p>
<div style="margin-top:1.6rem">{cartoes(itens, base, pasta, rotulo)}</div>
<div class="aviso"><strong>{AVISO_FIXO}</strong></div>
</div></main>
"""
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "description": desc, "url": u, "inLanguage": "pt-BR"},
          migalhas_ld((NOME, DOMINIO + "/"), (h1, u))]
    return cabeca(titulo, desc, u, og_url, base, ld) + topo(base, pasta) + corpo + rodape(base) + consentimento(base) + fim()


def pagina_404(og_url):
    base = "/"
    return (cabeca(f"Página não encontrada · {NOME}", "Esta página não existe.", DOMINIO + "/404.html", og_url, base,
                   {"@context": "https://schema.org", "@type": "WebPage", "name": "404"}, indexar=False)
            + topo(base) + f"""<main id="conteudo"><div class="casca estreita">
  <p class="rotulo">Erro 404</p>
  <h1>Nada nesta lente.</h1>
  <p class="lead">Esta página não existe, ou mudou de endereço. Se você procurava um ativo, ele pode ainda não estar na lista acompanhada.</p>
  <p><a class="botao" href="/ativos.html">Ver os ativos</a> <a class="botao claro" href="/index.html">Página inicial</a></p>
</div></main>
""" + rodape(base) + consentimento(base) + fim())


TITULO_SOBRE = f"Sobre o {NOME}: de onde vêm os dados"
DESC_SOBRE = (f"O que é o {NOME}: de onde vêm as cotações e os cadastros, como os números são conferidos, por que o site "
              "não recomenda ativos e quem faz.")
TITULO_CONTATO = f"Contato · {NOME}"
DESC_CONTATO = (f"Como falar com o {NOME} por e-mail: correção de dado com fonte, sugestão de ativo ou guia, pedidos sobre "
                "seus dados (LGPD) e imprensa.")
TITULO_PRIV = f"Política de privacidade · {NOME}"
DESC_PRIV = (f"Como o {NOME} trata dados, cookies e publicidade do Google AdSense: o que coleta, o que não coleta e "
             "quais são os seus direitos sob a LGPD.")
TITULO_GUIAS = f"Guias de investimento para iniciantes · {NOME}"
DESC_GUIAS = ("Guias curtos e com fonte para entender a bolsa: dividend yield, P/L e o imposto de renda em ações e fundos "
              "imobiliários, com as regras de 2026.")
TITULO_CALCS = f"Calculadoras financeiras · {NOME}"
DESC_CALCS = ("Calculadoras gratuitas de juros compostos, reserva de emergência e tempo até o primeiro milhão, com a "
              "fórmula explicada. Simulações educativas.")


def pagina_sobre(og_url):
    base = ""
    corpo = f"""<main id="conteudo"><div class="casca texto">
{migalhas_html(base, ("Sobre", ""))}
<h1>Sobre o {NOME}</h1>
<p class="lead">Um site de dados públicos sobre o mercado brasileiro, feito para quem está começando e quer entender o que os números querem dizer.</p>

<h2>O que é</h2>
<p>O <strong>{NOME}</strong> é um projeto editorial independente, feito no Brasil. Reúne a cotação de fechamento de ações e fundos imobiliários negociados na B3, o histórico de preços e o cadastro oficial de cada empresa ou fundo na CVM, e explica conceitos básicos em guias curtos e calculadoras.</p>

<h2>De onde vêm os dados</h2>
<ul>
 <li><strong>Cotações:</strong> série histórica de cotações da B3 (arquivo COTAHIST), publicada pela própria bolsa depois de cada pregão, lida segundo o layout oficial do arquivo. O site é atualizado uma vez por dia útil, à noite. Os dados têm atraso e não servem para negociar.</li>
 <li><strong>Cadastro:</strong> dados abertos da CVM — o cadastro de companhias abertas e o informe mensal dos fundos imobiliários.</li>
 <li><strong>Regras de imposto e conceitos:</strong> o texto das leis no portal do Planalto, publicações da Receita Federal, da CVM, do Banco Central e da B3, sempre listados ao fim de cada guia.</li>
</ul>

<h2>Como os números são conferidos</h2>
<p>O programa que lê o arquivo da B3 confere o arquivo inteiro antes de gravar qualquer número: tamanho de cada registro, cabeçalho, contagem do rodapé, moeda, faixa de preço do dia e coerência entre quantidade, preço médio e volume. Se algo não bater — inclusive uma mudança de layout pela B3 —, a atualização para e nada é publicado. Uma variação diária acima de 25% também trava a publicação até que alguém confira se houve desdobramento, grupamento ou erro. Página desatualizada é melhor que número errado.</p>

<h2>O que este site não faz</h2>
<p>Não recomenda ativos, não monta carteira, não dá preço-alvo nem nota, e não diz o que comprar ou vender. O site não é casa de análise, consultoria ou intermediário, e seu conteúdo não é relatório de análise de valores mobiliários nos termos da regulamentação da CVM. A lista de ativos acompanhados é só um ponto de partida, escolhida por serem papéis conhecidos e muito negociados, e não por qualquer juízo sobre eles.</p>

<h2>Correções</h2>
<p>Viu um número ou uma regra errada? Escreva pela página de <a href="contato.html">contato</a>, de preferência com a fonte. O erro confirmado é corrigido, e a data de atualização da página muda.</p>

<h2>Quem faz</h2>
<p>O {NOME} é mantido de forma independente, sem vínculo com corretora, banco, gestora, empresa listada ou órgão público. É da mesma casa do <a href="https://guiaprodutonalupa.com.br" rel="noopener">Guia Produto na Lupa</a> e do <a href="https://viagemnalupa.com.br" rel="noopener">Viagem na Lupa</a>. O site se mantém com anúncios do Google AdSense, descritos na <a href="privacidade.html">política de privacidade</a>; nenhum anunciante interfere no conteúdo.</p>
</div></main>
"""
    u = DOMINIO + "/sobre.html"
    return (cabeca(TITULO_SOBRE, DESC_SOBRE, u, og_url, base,
                   [{"@context": "https://schema.org", "@type": "AboutPage", "name": TITULO_SOBRE, "description": DESC_SOBRE, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Sobre", u))])
            + topo(base, "sobre") + corpo + rodape(base) + consentimento(base) + fim())


def pagina_contato(og_url):
    base = ""
    corpo = f"""<main id="conteudo"><div class="casca texto">
{migalhas_html(base, ("Contato", ""))}
<h1>Fale com o {NOME}</h1>
<p class="lead">Correção, sugestão ou pedido sobre seus dados: o caminho é um só.</p>
<div class="aviso"><strong>E-mail:</strong> <a href="mailto:{EMAIL}">{EMAIL}</a></div>
<h2>Para que escrever</h2>
<ul>
 <li><strong>Correções.</strong> Um número, uma data ou uma regra de imposto errada. Mande a fonte junto: é o que permite corrigir rápido.</li>
 <li><strong>Sugestões.</strong> Um ativo que você gostaria de ver acompanhado, um guia ou uma calculadora.</li>
 <li><strong>Seus dados.</strong> Pedidos sob a LGPD, conforme a <a href="privacidade.html">política de privacidade</a>.</li>
 <li><strong>Imprensa e parcerias.</strong></li>
</ul>
<h2>O que não respondemos</h2>
<p>Pedidos de recomendação — se vale comprar ou vender um ativo, ou como montar uma carteira. O site não faz isso, por princípio e porque essa atividade é regulada. Para isso, procure um profissional certificado.</p>
<h2>Como respondemos</h2>
<p>Não há formulário nem cadastro: a conversa é por e-mail, e o seu endereço não é usado para mais nada além de responder.</p>
</div></main>
"""
    u = DOMINIO + "/contato.html"
    return (cabeca(TITULO_CONTATO, DESC_CONTATO, u, og_url, base,
                   [{"@context": "https://schema.org", "@type": "ContactPage", "name": TITULO_CONTATO, "description": DESC_CONTATO, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Contato", u))])
            + topo(base, "contato") + corpo + rodape(base) + consentimento(base) + fim())


PRIVACIDADE = """<main id="conteudo"><div class="casca texto">
{{MIGALHAS}}
<p class="rotulo">Documento · atualizado em {{DATA}}</p>
<h1>Política de privacidade</h1>
<p class="lead">O que o {{NOME}} coleta, o que não coleta, quem mais está envolvido e o que você pode exigir.</p>

<div class="aviso"><strong>O resumo.</strong> Não pedimos cadastro, não temos formulário e não guardamos seu e-mail. As calculadoras fazem a conta no seu próprio navegador: o que você digita nelas não é enviado a lugar nenhum. O que existe são cookies de publicidade do Google, que você pode recusar na faixa da primeira visita, rever pelo link “Rever escolha de cookies”, no rodapé, ou desligar nas configurações do Google.</div>

<h2>1. Quem é o responsável</h2>
<p>O <strong>{{NOME}}</strong> é um projeto editorial independente, publicado em mercadonalupa.com.br. Para qualquer assunto desta política — inclusive pedidos de exclusão ou de informação —, o contato é <a href="mailto:{{EMAIL}}">{{EMAIL}}</a>.</p>

<h2>2. O que coletamos, e o que não</h2>
<p>Não há cadastro, login, comentários, newsletter nem formulário. Nenhuma página pede nome, e-mail, telefone, CPF ou dados da sua carteira de investimentos. A busca por código de ativo e as calculadoras funcionam inteiramente no seu navegador.</p>
<p>O que existe é o que qualquer site recebe por ser acessado: o servidor de hospedagem registra o endereço IP, a data e a hora, a página pedida e o navegador usado. Esses registros servem para segurança e diagnóstico de falha, e não são usados para identificar pessoas.</p>

<h2>3. Cookies e publicidade</h2>
<p>Este site exibe anúncios por meio do <strong>Google AdSense</strong>. Para isso, o Google e seus parceiros usam cookies para selecionar e medir os anúncios.</p>
<ul>
 <li>O Google, como fornecedor terceirizado, utiliza cookies para exibir anúncios neste site.</li>
 <li>O <strong>cookie DART</strong> permite que o Google veicule anúncios com base nas visitas do usuário a este e a outros sites da internet.</li>
 <li>Parceiros e redes de terceiros também podem usar cookies, identificadores de dispositivo ou tecnologia semelhante para medir e personalizar os anúncios.</li>
 <li>Nenhum desses dados passa por nós: o site não recebe, não armazena e não tem acesso ao que essas redes coletam.</li>
</ul>
<p>Você pode desativar a publicidade personalizada em <a href="https://adssettings.google.com" rel="noopener">adssettings.google.com</a>. As regras do Google estão em <a href="https://policies.google.com/technologies/ads?hl=pt-BR" rel="noopener">policies.google.com/technologies/ads</a>, e para sair da publicidade comportamental de várias redes existe o <a href="https://www.aboutads.info/choices/" rel="noopener">aboutads.info/choices</a>.</p>
<p>Anúncios exibidos aqui são escolhidos pelo Google, não por nós. Um anúncio de corretora, banco ou produto financeiro não é indicação do site.</p>

<h2>4. O que guardamos no seu navegador</h2>
<p>Uma única coisa, e ela não sai do seu aparelho: quando você responde à faixa de cookies, a escolha fica no armazenamento local do navegador, sob a chave <code>{{CHAVE}}</code>. Serve só para não perguntar de novo a cada página. Não é cookie, não é enviada a servidor nenhum e some quando você limpa os dados do site ou clica em “Rever escolha de cookies”.</p>

<h2>5. Conteúdo de terceiros</h2>
<p>Um único serviço externo participa da exibição destas páginas: o Google AdSense. Se você recusar na faixa, o script de anúncios é retirado e deixa de ser carregado. Fontes tipográficas, gráficos e imagens vêm deste mesmo domínio. Os links para a B3, a CVM, o Planalto e a Receita Federal só levam você a esses sites se você clicar.</p>

<h2>6. Seus direitos sob a LGPD</h2>
<p>A Lei nº 13.709/2018 garante o direito de confirmar se há tratamento de dados seus, de acessá-los, corrigi-los, pedir anonimização ou eliminação, solicitar portabilidade, saber com quem foram compartilhados e revogar consentimento. Aqui a base de dados que poderíamos entregar é praticamente vazia, mas qualquer pedido feito pelo e-mail acima será respondido. Para os dados que o Google coleta através dos anúncios, o pedido deve ser feito ao próprio Google.</p>

<h2>7. Crianças e adolescentes</h2>
<p>O conteúdo não se dirige a menores de 13 anos, e não coletamos conscientemente dados de crianças.</p>

<h2>8. Mudanças nesta política</h2>
<p>Se algo mudar — uma nova rede de anúncios, uma ferramenta de medição, uma área de comentários —, esta página muda junto, e a data no topo é atualizada.</p>
</div></main>
"""


def pagina_privacidade(og_url):
    base = ""
    corpo = (PRIVACIDADE.replace("{{NOME}}", NOME).replace("{{EMAIL}}", EMAIL).replace("{{CHAVE}}", CHAVE_CONSENTIMENTO)
             .replace("{{DATA}}", "3 de outubro de 2026").replace("{{MIGALHAS}}", migalhas_html(base, ("Privacidade", ""))))
    u = DOMINIO + "/privacidade.html"
    return (cabeca(TITULO_PRIV, DESC_PRIV, u, og_url, base,
                   [{"@context": "https://schema.org", "@type": "WebPage", "name": TITULO_PRIV, "description": DESC_PRIV, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Política de privacidade", u))])
            + topo(base) + corpo + rodape(base) + consentimento(base) + fim())


# --- conferências ----------------------------------------------------------------

def conferir_seo(paginas):
    erros, vt, vd = [], {}, {}
    for nome, (t, d) in paginas.items():
        if len(t) > TITULO_MAX:
            erros.append(f"{nome}: título com {len(t)} caracteres: {t!r}")
        if not DESCRICAO_MIN <= len(d) <= DESCRICAO_MAX:
            erros.append(f"{nome}: descrição com {len(d)} caracteres ({DESCRICAO_MIN}–{DESCRICAO_MAX})")
        if t in vt:
            erros.append(f"{nome}: título igual ao de {vt[t]}")
        if d in vd:
            erros.append(f"{nome}: descrição igual à de {vd[d]}")
        vt[t], vd[d] = nome, nome
    if erros:
        falha("SEO\n  " + "\n  ".join(erros))


def conferir_links(arquivos):
    """Todo href/src interno tem de apontar para arquivo que existe, e toda
    âncora #id para um id da página de destino."""
    ids = {}
    for f in arquivos:
        ids[f.resolve()] = set(re.findall(r'\sid="([^"]+)"', f.read_text(encoding="utf-8")))
    erros = []
    for f in arquivos:
        txt = f.read_text(encoding="utf-8")
        for ref in re.findall(r'(?:href|src)="([^"]+)"', txt):
            if re.match(r"(https?:|mailto:|data:|#$)", ref) or ref.startswith("//"):
                continue
            alvo, _, ancora = ref.partition("#")
            if not alvo:
                destino = f.resolve()
            elif alvo.startswith("/"):
                destino = (RAIZ / alvo.lstrip("/")).resolve()
            else:
                destino = (f.parent / alvo).resolve()
            if not destino.exists():
                erros.append(f"{f.relative_to(RAIZ)}: {ref} não existe")
            elif ancora and destino in ids and ancora not in ids[destino]:
                erros.append(f"{f.relative_to(RAIZ)}: âncora #{ancora} não existe em {destino.name}")
    if erros:
        falha("links quebrados\n  " + "\n  ".join(sorted(set(erros))))


def data_git(caminho):
    rel = str(Path(caminho).resolve().relative_to(RAIZ)).replace("\\", "/")
    try:
        sujo = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
        if sujo:
            return dt.date.today().isoformat()
        datas = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel], cwd=RAIZ, capture_output=True, text=True).stdout.split()
        if datas:
            return datas[0]
    except OSError:
        pass
    return dt.date.today().isoformat()


# --- main --------------------------------------------------------------------------

def main():
    ativos, pregoes, ultimo, cad = carregar()
    guias = sorted((ler_pagina(f) for f in (SRC / "paginas" / "guias").glob("*.html")), key=lambda g: g["slug"])
    calcs = sorted((ler_pagina(f) for f in (SRC / "paginas" / "calculadoras").glob("*.html")), key=lambda g: g["slug"])
    ordem_guias = ["o-que-e-dividend-yield", "o-que-e-p-l", "como-funciona-o-imposto-de-renda-na-bolsa"]
    guias.sort(key=lambda g: ordem_guias.index(g["slug"]) if g["slug"] in ordem_guias else 99)
    for g in guias:
        if not g["fontes"]:
            falha(f"guia {g['slug']}: sem fontes")

    seo = {"home": (TITULO_HOME, DESC_HOME), "ativos": (TITULO_ATIVOS, DESC_ATIVOS), "sobre": (TITULO_SOBRE, DESC_SOBRE),
           "contato": (TITULO_CONTATO, DESC_CONTATO), "privacidade": (TITULO_PRIV, DESC_PRIV),
           "guias": (TITULO_GUIAS, DESC_GUIAS), "calculadoras": (TITULO_CALCS, DESC_CALCS)}
    seo.update({f"ativos/{a['slug']}": (titulo_ativo(a), descricao_ativo(a)) for a in ativos})
    seo.update({f"guias/{g['slug']}": (g["titulo"], g["descricao"]) for g in guias})
    seo.update({f"calculadoras/{g['slug']}": (g["titulo"], g["descricao"]) for g in calcs})
    conferir_seo(seo)

    gerar_marca()
    og_home = og("og-home.jpg", "Dados públicos · B3 e CVM", "O mercado brasileiro, com lupa e com fonte.", "mercadonalupa.com.br")
    og_a = {a["codigo"]: og(f"og-{a['slug']}.jpg", ("Ação" if a["tipo"] == "acao" else "Fundo imobiliário") + " · B3",
                            f"{a['codigo']} — {nome_curto(a)}", "Cotação de fechamento, histórico e cadastro") for a in ativos}
    og_g = {g["slug"]: og(f"og-guia-{g['slug']}.jpg", "Guia", g["h1"], "mercadonalupa.com.br") for g in guias}
    og_c = {g["slug"]: og(f"og-calc-{g['slug']}.jpg", "Calculadora", g["h1"], "Simulação educativa") for g in calcs}

    saidas = {}
    saidas["index.html"] = home(ativos, ultimo, guias, calcs, og_home)
    saidas["ativos.html"] = pagina_ativos(ativos, ultimo, og_home)
    for a in ativos:
        saidas[f"ativos/{a['slug']}.html"] = pagina_ativo(a, ativos, ultimo, og_a[a["codigo"]])
    for g in guias:
        saidas[f"guias/{g['slug']}.html"] = pagina_conteudo(g, "guias", "Guias", og_g[g["slug"]], True)
    for g in calcs:
        saidas[f"calculadoras/{g['slug']}.html"] = pagina_conteudo(g, "calculadoras", "Calculadoras", og_c[g["slug"]], False)
    saidas["guias.html"] = pagina_hub(guias, "guias", TITULO_GUIAS, DESC_GUIAS, "Guias",
                                      "Conceitos da bolsa explicados do zero, com exemplo e fonte. Cada guia diz a data em que as regras foram conferidas.", "Guia", og_home)
    saidas["calculadoras.html"] = pagina_hub(calcs, "calculadoras", TITULO_CALCS, DESC_CALCS, "Calculadoras",
                                             "Simulações que rodam no seu navegador — nada do que você digita sai dele. Cada calculadora mostra a fórmula que usa.", "Calculadora", og_home)
    saidas["sobre.html"] = pagina_sobre(og_home)
    saidas["contato.html"] = pagina_contato(og_home)
    saidas["privacidade.html"] = pagina_privacidade(og_home)
    saidas["404.html"] = pagina_404(og_home)

    for nome, txt in saidas.items():
        conferir_texto(nome, txt)

    # grava, e apaga páginas geradas que não existem mais
    for pasta in ("ativos", "guias", "calculadoras"):
        (RAIZ / pasta).mkdir(exist_ok=True)
        for velho in (RAIZ / pasta).glob("*.html"):
            if f"{pasta}/{velho.name}" not in saidas:
                velho.unlink()
                print("removido:", f"{pasta}/{velho.name}")
    escritos = []
    for nome, txt in saidas.items():
        p = RAIZ / nome
        p.write_text(txt, encoding="utf-8")
        escritos.append(p)

    ads = RAIZ / "ads.txt"
    if ADSENSE_LIGADO:
        ads.write_text("# Declaração de vendedor autorizado (IAB ads.txt)\n"
                       "# Gerado por _src/build.py a partir de ADSENSE_PUB. Não editar à mão.\n"
                       f"google.com, {ADSENSE_PUB}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
    elif ads.exists():
        ads.unlink()

    # sitemap: ativos e home mudam a cada pregão; guias e calculadoras pela
    # data do arquivo-fonte no git; páginas fixas pelo build.py.
    fixas = data_git(Path(__file__))
    datas = {DOMINIO + "/": ultimo, f"{DOMINIO}/ativos.html": ultimo}
    datas.update({f"{DOMINIO}/ativos/{a['slug']}.html": a["ult"]["data"] for a in ativos})
    for pasta, itens in (("guias", guias), ("calculadoras", calcs)):
        ds = []
        for g in itens:
            d = max(data_git(g["arquivo"]), g["atualizado"])
            ds.append(d)
            datas[f"{DOMINIO}/{pasta}/{g['slug']}.html"] = d
        datas[f"{DOMINIO}/{pasta}.html"] = max(ds + [fixas])
    for pg in ("sobre", "contato", "privacidade"):
        datas[f"{DOMINIO}/{pg}.html"] = fixas
    (RAIZ / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in datas.items()) + "</urlset>\n", encoding="utf-8")
    (RAIZ / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /_src/\nDisallow: /dados/\n\nSitemap: {DOMINIO}/sitemap.xml\n", encoding="utf-8")

    conferir_links(escritos)
    atraso = (dt.date.today() - dt.date.fromisoformat(ultimo)).days
    print(f"ok: {len(saidas)} páginas · {len(ativos)} ativos · {len(guias)} guias · {len(calcs)} calculadoras · "
          f"último pregão {data_br(ultimo)}" + (f" · ATENÇÃO: {atraso} dias sem pregão novo" if atraso > 5 else ""))


if __name__ == "__main__":
    main()
