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


def passo_bonito(amp, n=4):
    """Passo "redondo" para as linhas de grade dos gráficos em SVG (páginas de indicadores)."""
    if amp <= 0:
        return 1
    bruto = amp / n
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


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


TIPOS = {"acao": ("Ação", "Ações", "acoes"), "fii": ("Fundo imobiliário", "Fundos imobiliários", "fundos-imobiliarios"),
         "bdr": ("BDR", "BDRs", "bdrs")}
BDI_TIPO = {"02": "acao", "12": "fii", "34": "bdr", "35": "bdr"}


def evento_info(v):
    """eventos.json aceita o formato antigo (texto) e o novo (dict com fonte).
    tipo "evento" (padrão): desdobramento, grupamento etc. — a variação do dia
    não é comparável e não é exibida. tipo "mercado": variação real, conferida
    e com fonte — é exibida normalmente; a declaração só libera a trava."""
    if isinstance(v, str):
        return {"evento": v, "fonte": None, "fonte_nome": None, "tipo": "evento"}
    return {"tipo": "evento", "fonte": None, "fonte_nome": None, **v}


def carregar():
    lista = ler_json(SRC / "ativos.json")
    papeis = ler_json(DADOS / "papeis.json")
    cad = ler_json(DADOS / "cadastro.json")
    eventos = ler_json(SRC / "eventos.json") if (SRC / "eventos.json").exists() else {}
    eventos = {c: {d: evento_info(v) for d, v in ds.items()} for c, ds in eventos.items()}
    com = ler_json(DADOS / "comunicados.json") if (DADOS / "comunicados.json").exists() else {"docs": [], "geral": [], "fontes": {}}
    por_chave = {}
    for d in com["docs"]:
        por_chave.setdefault(d["k"], []).append(d)
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
        if a["tipo"] != "bdr" and c not in cad["ativos"] and c not in cad.get("sem_cadastro", {}):
            falha(f"{c}: fora do cadastro da CVM — rode _src/cvm.py")
        with arq.open(encoding="utf-8") as f:
            rows = []
            for l in csv.DictReader(f):
                rows.append({"data": l["data"], **{k: float(l[k]) for k in
                             ("abertura", "maxima", "minima", "media", "fechamento", "volume")},
                             "negocios": int(l["negocios"]), "quantidade": int(l["quantidade"])})
        if len(rows) < 2:
            falha(f"{c}: menos de dois pregões gravados")
        ev = eventos.get(c, {})
        datas = {r["data"] for r in rows}
        longo = DADOS / "historico" / f"{c}.csv"
        if longo.exists():
            with longo.open(encoding="utf-8") as f:
                datas |= {l["data"] for l in csv.DictReader(f)}
        for d in ev:
            if d not in datas:
                falha(f"{c}: _src/eventos.json declara {d}, que não é pregão com negócio do papel — data errada?")
        for ant, cur in zip(rows, rows[1:]):
            v = (cur["fechamento"] / ant["fechamento"] - 1) * 100
            cur["var"] = None if (cur["data"] in ev and ev[cur["data"]]["tipo"] == "evento") else v
            if abs(v) > VARIACAO_MAX and cur["data"] not in ev:
                falha(f"{c} {cur['data']}: variação de {v:+.1f}% num pregão. Se for desdobramento, "
                      "grupamento ou outro evento, declare em _src/eventos.json (python _src/eventos_b3.py procura na B3); "
                      "se não, confira o arquivo da B3.")
        rows[0]["var"] = None
        u = rows[-1]
        tipo = a["tipo"]
        bdi = papeis[c].get("bdi") or ("12" if papeis[c]["fii"] else "02")
        if tipo not in TIPOS or BDI_TIPO.get(bdi) != tipo:
            falha(f"{c}: tipo {tipo!r} em ativos.json não bate com o código BDI {bdi} da B3")
        chave = a.get("cnpj") if tipo != "bdr" else ("cvm:" + a["codigo_cvm"].lstrip("0") if a.get("codigo_cvm") else None)
        ativos.append({"codigo": c, "slug": c.lower(), "tipo": tipo, "nome": a["nome"], "rows": rows, "ult": u,
                       "ant": rows[-2], "papel": papeis[c], "cad": cad["ativos"].get(c), "info": a,
                       "sem_cadastro": cad.get("sem_cadastro", {}).get(c), "indices": a.get("indices", []),
                       "negociou_ultimo": u["data"] == ultimo, "evento": ev,
                       "comunicados": [d for d in por_chave.get(chave, []) if not d.get("p")][:10] if chave else [],
                       "comunicados_todos": por_chave.get(chave, []) if chave else []})
    if len({a["codigo"] for a in ativos}) != len(ativos):
        falha("código repetido em _src/ativos.json")
    return ativos, pregoes, ultimo, cad, com


ESPECIE = {"ON": "ordinárias (ON)", "PN": "preferenciais (PN)", "PNA": "preferenciais classe A (PNA)",
           "PNB": "preferenciais classe B (PNB)", "PNC": "preferenciais classe C (PNC)", "UNT": "units (UNT)", "CI": "cotas (CI)"}
PROGRAMA_BDR = {"DRN": "não patrocinado", "DR1": "patrocinado nível I", "DR2": "patrocinado nível II",
                "DR3": "patrocinado nível III"}
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
    if a["tipo"] == "bdr":
        return f"{a['nome']} BDR"
    return a["nome"]


def janela(rows, dias):
    fim = dt.date.fromisoformat(rows[-1]["data"])
    ini = (fim - dt.timedelta(days=dias)).isoformat()
    return [r for r in rows if r["data"] > ini]


# --- gráfico (desenhado no navegador) -------------------------------------------
# Antes o build escrevia três SVGs por página. Com 245 ativos isso pesava no
# repositório: a janela de 12 meses anda todo dia e TODAS as coordenadas mudam,
# então cada página era quase um arquivo novo por pregão. Agora a página leva a
# série de fechamentos (desde 02/01/2025) num JSON enxuto, que só cresce no fim,
# e um script pequeno desenha os três períodos com o mesmo desenho de antes.
# Sem JavaScript, fica o resumo em texto (mínima e máxima de 12 meses) e a tabela.

def serie_json(rows):
    """[dias desde o pregão anterior, fechamento, ...]; o 1º par traz a data inicial à parte."""
    d0 = dt.date.fromisoformat(rows[0]["data"])
    plano, ant = [], d0
    for r in rows:
        d = dt.date.fromisoformat(r["data"])
        plano += [(d - ant).days, r["fechamento"]]
        ant = d
    return json.dumps({"d0": rows[0]["data"], "s": plano}, separators=(",", ":"))


GRAFICO_JS = r"""
(function(){var G=document.querySelector('.grafico[data-cod]');if(!G)return;
var J=JSON.parse(document.getElementById('serie').textContent),M=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
var rows=[],t=Date.parse(J.d0+'T00:00:00Z');for(var i=0;i<J.s.length;i+=2){t+=J.s[i]*864e5;rows.push([new Date(t),J.s[i+1]])}
function br(v,c){return v.toLocaleString('pt-BR',{minimumFractionDigits:c,maximumFractionDigits:c})}
function dt(d){return ('0'+d.getUTCDate()).slice(-2)+'/'+('0'+(d.getUTCMonth()+1)).slice(-2)+'/'+d.getUTCFullYear()}
function passo(a){if(a<=0)return 1;var b=a/4,m=Math.pow(10,Math.floor(Math.log10(b)));var k=[1,2,2.5,5,10];for(var i=0;i<k.length;i++)if(b<=k[i]*m)return k[i]*m;return 10*m}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;')}
function svg(rs,cl){var W=720,H=330,x0=82,x1=708,y0=16,y1=282,v=rs.map(function(r){return r[1]}),lo=Math.min.apply(0,v),hi=Math.max.apply(0,v),p=passo(hi-lo),
 a=Math.floor(lo/p)*p,b=Math.ceil(hi/p)*p;if(b===a)b=a+p;var n=rs.length,
 X=function(i){return x0+(x1-x0)*(n>1?i/(n-1):.5)},Y=function(y){return y1-(y1-y0)*(y-a)/(b-a)},
 pts=v.map(function(y,i){return X(i).toFixed(1)+','+Y(y).toFixed(1)}).join(' '),o=[],c=p<1?2:(p<10&&p!==Math.floor(p)?1:0);
 for(var y=a;y<=b+1e-9;y+=p){var yy=Y(y).toFixed(1);o.push('<line class="grade-y" x1="'+x0+'" x2="'+x1+'" y1="'+yy+'" y2="'+yy+'"/><text x="'+(x0-10)+'" y="'+(+yy+7).toFixed(1)+'" text-anchor="end">'+br(y,c)+'</text>')}
 var xs=[];if(cl==='g-1m'){for(var i=0;i<n;i+=Math.max(1,Math.floor(n/4))){var d=rs[i][0];xs.push([i,('0'+d.getUTCDate()).slice(-2)+'/'+('0'+(d.getUTCMonth()+1)).slice(-2)])}}
 else{var ma=null,ps=cl==='g-6m'?1:2,ct=0;for(var i=0;i<n;i++){var d=rs[i][0],m=d.getUTCMonth();if(m!==ma){if(ma!==null&&ct%ps===0&&i>2)xs.push([i,M[m]+(m===0?'/'+String(d.getUTCFullYear()).slice(2):'')]);if(ma!==null)ct++;ma=m}}}
 var eixo=xs.map(function(q){return '<text x="'+X(q[0]).toFixed(1)+'" y="'+(H-14)+'" text-anchor="middle">'+q[1]+'</text>'}).join('');
 var il=v.indexOf(lo),ih=v.indexOf(hi),id='t-'+cl,tit=G.getAttribute('data-cod')+': fechamento diário de '+dt(rs[0][0])+' a '+dt(rs[n-1][0])+'. Mínimo de R$ '+br(lo,2)+' em '+dt(rs[il][0])+', máximo de R$ '+br(hi,2)+' em '+dt(rs[ih][0])+'.';
 return '<svg class="'+cl+'" viewBox="0 0 '+W+' '+H+'" role="img" aria-labelledby="'+id+'"><title id="'+id+'">'+esc(tit)+'</title>'+o.join('')+
  '<path class="area" d="M'+X(0).toFixed(1)+','+y1+' L'+pts.split(' ').join(' L')+' L'+X(n-1).toFixed(1)+','+y1+' Z"/><polyline class="linha" points="'+pts+'"/><circle class="ponto" cx="'+X(n-1).toFixed(1)+'" cy="'+Y(v[n-1]).toFixed(1)+'" r="6"/>'+eixo+'</svg>'}
var fim=rows[rows.length-1][0],h='';[['g-12m',366],['g-6m',183],['g-1m',31]].forEach(function(q){var ini=+fim-q[1]*864e5,rs=rows.filter(function(r){return +r[0]>ini});h+=svg(rs,q[0])});
G.querySelector('.paineis').innerHTML=h;G.classList.add('pronto');})();"""


def bloco_grafico(a):
    periodos = [("12m", "12 meses"), ("6m", "6 meses"), ("1m", "1 mês")]
    return (f'<div class="grafico" data-cod="{a["codigo"]}">'
            # os rádios precisam ser irmãos de .paineis: o CSS liga cada um ao seu SVG
            + "".join(f'<input type="radio" class="sr" name="per-{a["slug"]}" id="p-{k}"{" checked" if k == "12m" else ""}>' for k, _ in periodos)
            + '<div class="periodos" role="group" aria-label="Período do gráfico">'
            + "".join(f'<label for="p-{k}">{nome}</label>' for k, nome in periodos)
            + '</div><div class="paineis"><p class="sem-js">O gráfico é desenhado no navegador e precisa de JavaScript. '
              'Os números do período estão no texto logo abaixo e na tabela de pregões.</p></div>'
            + f'<script type="application/json" id="serie">{serie_json(a["rows"])}</script>'
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


# --- fotos de fundo, selo do ativo, ícones ------------------------------------------
# As fotos são preparadas por _src/fundos.py (recorte, dessaturação, escurecimento,
# WebP + JPEG em várias larguras); o crédito de cada uma vem de _src/fundos.json.

FUNDOS = {k: v for k, v in ler_json(SRC / "fundos.json").items() if not k.startswith("_")} \
    if (SRC / "fundos.json").exists() else {}
FUNDO_DIR = RAIZ / "assets" / "img" / "fundo"
# carteiras dos índices e critérios da lista (escrito por _src/carteiras.py)
CARTEIRAS = ler_json(SRC / "carteiras.json") if (SRC / "carteiras.json").exists() else {}
# No celular a foto é recortada pela altura (object-fit: cover), então ocupa
# mais que a largura da tela: o sizes avisa o navegador para não pegar a pequena.
FUNDO_SIZES = "(max-width: 700px) 200vw, 100vw"
LICENCA_DERIVADA = {"CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/"}


def _fundo_arquivos(chave):
    if chave not in FUNDOS:
        falha(f"foto de fundo {chave!r} não está em _src/fundos.json")
    arqs = sorted(FUNDO_DIR.glob(f"{chave}-*.jpg"), key=lambda f: int(f.stem.rsplit("-", 1)[1]))
    if not arqs:
        falha(f"foto de fundo {chave!r} sem arquivos em assets/img/fundo — rode python _src/fundos.py")
    saida = []
    for jpg in arqs:
        if not jpg.with_suffix(".webp").exists():
            falha(f"{jpg.name}: falta a versão WebP — rode python _src/fundos.py")
        with Image.open(jpg) as im:
            saida.append((jpg.stem, im.size))
    return saida


def fundo_srcset(chave, base, ext):
    return ", ".join(f"{base}assets/img/fundo/{n}.{ext} {w}w" for n, (w, h) in _fundo_arquivos(chave))


def fundo_preload(chave, base):
    """A foto do topo é o candidato a LCP: o navegador fica sabendo dela no <head>."""
    return (f'<link rel="preload" as="image" type="image/webp" imagesrcset="{fundo_srcset(chave, base, "webp")}" '
            f'imagesizes="{FUNDO_SIZES}" fetchpriority="high">')


def fundo_picture(chave, base):
    arqs = _fundo_arquivos(chave)
    medio = arqs[min(1, len(arqs) - 1)]
    w, h = medio[1]
    # decorativa (alt vazio): o conteúdo está no texto por cima; o crédito vem logo abaixo
    return (f'<picture class="fundo"><source type="image/webp" srcset="{fundo_srcset(chave, base, "webp")}" sizes="{FUNDO_SIZES}">'
            f'<img src="{base}assets/img/fundo/{medio[0]}.jpg" srcset="{fundo_srcset(chave, base, "jpg")}" sizes="{FUNDO_SIZES}" '
            f'width="{w}" height="{h}" alt="" loading="eager" fetchpriority="high" decoding="async"></picture>')


def credito_fundo(chave):
    f = FUNDOS[chave]
    deriv = ""
    if f["licenca"] in LICENCA_DERIVADA:
        deriv = f' · esta versão também sob <a href="{LICENCA_DERIVADA[f["licenca"]]}" rel="license noopener">{f["licenca"]}</a>'
    return (f'<p class="credito-foto">Foto: {e(f["descricao"])} — <a href="{e(f["origem"])}" rel="noopener">{e(f["autor"])}</a>, '
            f'Wikimedia Commons · <a href="{e(f["licenca_url"])}" rel="license noopener">{e(f["licenca"])}</a> · '
            f'recortada, dessaturada e escurecida{deriv}</p>')


def faixa(chave, base, conteudo, classe=""):
    """Cabeçalho com foto de fundo e camada escura (texto claro nos dois temas)."""
    cl = f" {classe}" if classe else ""
    return (f'<div class="faixa{cl}">{fundo_picture(chave, base)}{LINHA_FUNDO}'
            f'<div class="casca faixa-conteudo">{conteudo}{credito_fundo(chave)}</div></div>\n')


def creditos_md():
    linhas = ["# Créditos das imagens", "",
              "Gerado por `_src/build.py` a partir de `_src/fundos.json`. Não editar à mão.", "",
              "Fotos de fundo do site (topo da página inicial e faixa das páginas internas). Todas vêm do",
              "Wikimedia Commons, sob licença que permite uso comercial com atribuição. Cada página exibe o",
              "crédito da foto que usa. Modificação em todas: recorte, redução de tamanho, dessaturação e",
              "escurecimento, mais uma camada escura em CSS por cima.", ""]
    for chave, f in FUNDOS.items():
        arqs = ", ".join(f"`assets/img/fundo/{n}.webp|.jpg`" for n, _ in _fundo_arquivos(chave))
        linhas += [f"## {f['descricao']}", "",
                   f"- Obra: “{f['titulo']}” — {f['origem']}",
                   f"- Autor: {f['autor']}",
                   f"- Licença: {f['licenca']} — {f['licenca_url']}",
                   f"- Modificação: recortada, dessaturada e escurecida"
                   + (f"; a versão adaptada é distribuída sob {f['licenca']}" if f["licenca"] in LICENCA_DERIVADA else ""),
                   f"- Usada em: {f['usada_em']}",
                   f"- Arquivos: {arqs}", ""]
    return "\n".join(linhas)


# Linha de gráfico decorativa (sobre as fotos e nas texturas).
LINHA_FUNDO = ('<svg class="linha-fundo" viewBox="0 0 1200 160" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
               '<polyline points="0,128 70,118 130,124 200,96 260,104 330,82 400,90 460,64 540,78 600,56 670,70 730,44 '
               '800,58 870,36 930,48 1000,28 1070,40 1130,18 1200,26"/></svg>')


PAISES = ler_json(SRC / "paises.json")["bdrs"] if (SRC / "paises.json").exists() else {}


def pais(a):
    """Bandeira do selo: Brasil para ações e FIIs (emissores do cadastro da CVM); para BDR,
    o país de _src/paises.json (só os conferidos; os outros ficam sem bandeira)."""
    if a["tipo"] in ("acao", "fii"):
        return "br"
    return PAISES.get(a["codigo"], {}).get("pais", "").lower() or None


def selo(a, tam=""):
    """Selo do ativo: o código num quadrado (ação) ou círculo (fundo imobiliário),
    em cor por tipo, com a bandeira do país da empresa no canto. Desenhado em CSS,
    sem logotipo de empresa nem imagem externa. É decorativo: o código aparece em
    texto ao lado."""
    m = re.match(r"(.+?)(\d{1,2})$", a["codigo"])
    letras, num = (m.group(1), m.group(2)) if m else (a["codigo"], "")
    cl = f" selo-{tam}" if tam else ""
    p = pais(a)
    band = f' data-pais="{p}"' if p else ""
    return f'<span class="selo selo-{a["tipo"]}{cl}"{band} aria-hidden="true"><b>{letras}</b><i>{num}</i></span>'


def _icone(corpo):
    return ('<svg class="icone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{corpo}</svg>')


ICONES = {
    # guias
    "o-que-e-dividend-yield": _icone('<ellipse cx="9" cy="6.5" rx="6" ry="2.5"/><path d="M3 6.5v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4"/>'
                                     '<path d="M3 10.5v4c0 1.4 2.7 2.5 6 2.5"/><path d="M15 21l6-6"/><circle cx="15.5" cy="15.5" r="1"/><circle cx="20.5" cy="20.5" r="1"/>'),
    "o-que-e-p-l": _icone('<path d="M12 4v16M8 20h8M5 7h14"/><path d="M5 7l-3 6.5a3 3 0 0 0 6 0z"/><path d="M19 7l-3 6.5a3 3 0 0 0 6 0z"/>'),
    "como-funciona-o-imposto-de-renda-na-bolsa": _icone('<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9.5 17l5-6"/>'
                                                        '<circle cx="10" cy="11.5" r="1"/><circle cx="14" cy="16.5" r="1"/>'),
    # calculadoras
    "juros-compostos": _icone('<path d="M4 4v16h16"/><path d="M7 16c4.5 0 7.5-2.5 11-10"/><path d="M14.5 6H18v3.5"/>'),
    "primeiro-milhao": _icone('<path d="M5 21V4"/><path d="M5 4.5h12l-2.5 3.5L17 11.5H5"/><path d="M9 21h-4"/>'),
    "reserva-de-emergencia": _icone('<path d="M12 3l7 3v5.5c0 4.5-3 7.8-7 9.5-4-1.7-7-5-7-9.5V6z"/><path d="M9 12l2 2 4-4.5"/>'),
}
ICONE_PADRAO = _icone('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M7 12l2.5-2.5 2 1.5 2.5-3"/>')
SETA = _icone('<path d="M5 12h14M13 6l6 6-6 6"/>').replace('class="icone"', 'class="seta"')
ICONE_ALTA = _icone('<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>')
ICONE_BAIXA = _icone('<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>')
ICONE_VOLUME = _icone('<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>')


def divisor():
    return ('<div class="divisor" aria-hidden="true"><span>'
            '<svg viewBox="0 0 40 16" focusable="false"><polyline points="2,12 10,8 16,10 24,4 30,6 38,2"/></svg>'
            '</span></div>')


# Links do rodapé (guias e calculadoras), preenchido em main() antes de gerar as páginas.
RODAPE_LINKS = {"guias": [], "calculadoras": []}


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


ATIVO_JS_SRC = SRC / "ativo.js"
ATIVO_JS_VER = __import__("hashlib").sha1(ATIVO_JS_SRC.read_bytes()).hexdigest()[:10] if ATIVO_JS_SRC.exists() else "0"

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


def cabeca(titulo, descricao, url, imagem, base, jsonld, tipo="website", indexar=True, extra=""):
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
{extra}<meta property="og:type" content="{tipo}">
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
      <a href="{base}indicadores.html"{cur('indicadores')}>Indicadores</a>
      <a href="{base}comunicados.html"{cur('comunicados')}>Comunicados</a>
      <a href="{base}noticias.html"{cur('noticias')}>Notícias</a>
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
    guias = "".join(f'<li><a href="{base}guias/{sl}.html">{e(t)}</a></li>' for sl, t in RODAPE_LINKS["guias"])
    calcs = "".join(f'<li><a href="{base}calculadoras/{sl}.html">{e(t)}</a></li>' for sl, t in RODAPE_LINKS["calculadoras"])
    return f"""{pregao}<footer class="rodape">
  {LINHA_FUNDO}
  <div class="casca">
    <div class="rodape-marca">
      <a class="marca" href="{base}index.html" aria-label="{NOME}, página inicial">{LUPA_SVG}<span>Mercado <i>na Lupa</i></span></a>
      <p>Dados públicos do mercado brasileiro — cotações da B3, cadastros e comunicados da CVM, indicadores do Banco Central e do Tesouro — explicados para quem está começando. Com fonte, sem palpite.</p>
      <p class="fontes-selos" aria-label="Fontes dos dados"><span>B3</span><span>CVM</span><span>BC</span><span>Tesouro</span></p>
    </div>
    <div>
      <h2>Guias</h2>
      <ul>{guias}</ul>
    </div>
    <div>
      <h2>Calculadoras</h2>
      <ul>{calcs}</ul>
    </div>
    <div>
      <h2>Navegue</h2>
      <ul>
        <li><a href="{base}acoes.html">Ações</a> · <a href="{base}fundos-imobiliarios.html">Fundos imobiliários</a> · <a href="{base}bdrs.html">BDRs</a></li>
        <li><a href="{base}comunicados.html">Comunicados</a> · <a href="{base}noticias.html">Notícias</a></li>
        <li><a href="{base}indicadores.html">Indicadores de hoje</a> · <a href="{base}tesouro-direto.html">Tesouro Direto</a></li>
        <li><a href="{base}glossario.html">Glossário</a></li>
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
    <p class="assinatura">© {dt.date.today().year} {NOME} · mercadonalupa.com.br · <a href="{base}status.html">Status dos dados</a></p>
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


# --- selo de atualização ------------------------------------------------------------
# O HTML leva a data do último pregão lido (data-pregao); um script pequeno compara
# com o relógio do visitante, em Brasília (UTC−3 fixo: o Brasil não tem horário de
# verão desde 2019), contando só dias úteis da B3 (_src/feriados-b3.json). Depois
# das 19h de Brasília o dia corrente conta como encerrado.
# Verde: nenhum pregão faltando. Âmbar: falta 1. Vermelho: faltam 2 ou mais.

FERIADOS_ARQ = SRC / "feriados-b3.json"
FERIADOS_INFO = {k: v for k, v in ler_json(FERIADOS_ARQ).items() if not k.startswith("_")}
FERIADOS = {d: nome for ano in FERIADOS_INFO.values() for d, nome in ano["datas"].items()}
HORA_FECHAMENTO = 19  # horário de Brasília a partir do qual o pregão do dia conta como encerrado
BRASILIA = dt.timezone(dt.timedelta(hours=-3), "BRT")


def dia_util(d):
    return d.weekday() < 5 and d.isoformat() not in FERIADOS


def proximos_uteis(depois_de, n):
    d, saida = dt.date.fromisoformat(depois_de), []
    while len(saida) < n:
        d += dt.timedelta(days=1)
        if dia_util(d):
            saida.append(d)
    return saida


def conferir_feriados(pregoes):
    """Avisa (não para: o selo não pode travar a publicação das cotações) se a lista
    de feriados não cobre o ano, se é provisória, ou se bate mal com os pregões gravados."""
    avisos = []
    hoje = dt.date.today()
    for ano in sorted({hoje.year, (hoje + dt.timedelta(days=45)).year}):
        info = FERIADOS_INFO.get(str(ano))
        if not info:
            avisos.append(f"_src/feriados-b3.json não tem {ano}: o selo vai contar só fim de semana")
        elif info.get("provisorio") and (ano == hoje.year or hoje.month >= 11):
            avisos.append(f"feriados de {ano} em _src/feriados-b3.json são PROVISÓRIOS — confira o calendário da B3")
    gravados = set(pregoes)
    for d in sorted(FERIADOS):
        if d in gravados:
            avisos.append(f"{d} está em _src/feriados-b3.json, mas tem pregão gravado")
    for ano, info in FERIADOS_INFO.items():
        d = dt.date(int(ano), 1, 1)
        while d.year == int(ano) and d.isoformat() <= pregoes[-1]:
            if d.isoformat() >= pregoes[0] and dia_util(d) and d.isoformat() not in gravados:
                avisos.append(f"{d.isoformat()} é dia útil pela lista, mas não tem pregão gravado")
            d += dt.timedelta(days=1)
    for a in avisos:
        print("ATENÇÃO (selo):", a)


def selo_dados(ultimo, extra_cls=""):
    """Sem JS: só a data. Com JS: cor, ícone e a palavra do estado."""
    cl = f" {extra_cls}" if extra_cls else ""
    return (f'<p class="selo-dados{cl}" data-pregao="{ultimo}"><span class="selo-ponto" aria-hidden="true"></span>'
            f'<span class="selo-txt">Pregão de {data_br(ultimo)}</span></p>')


def selo_js(teste=False):
    fer = json.dumps({d: 1 for d in sorted(FERIADOS)}, separators=(",", ":"))
    # ?hoje=AAAA-MM-DD (ou AAAA-MM-DDTHH, hora de Brasília) só vale na status.html
    return ("(function(){var F=" + fer + ",H=" + str(HORA_FECHAMENTO) + ",TESTE=" + ("true" if teste else "false") + ",D=864e5;"
            r"""
function iso(d){return d.toISOString().slice(0,10)}
function br(s){return s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(0,4)}
function util(d){var w=d.getUTCDay();return w>0&&w<6&&!F[iso(d)]}
function agora(){var t=Date.now()-3*36e5;
 if(TESTE){var m=/[?&]hoje=(\d{4}-\d{2}-\d{2})(?:T(\d{1,2}))?/.exec(location.search);
  if(m){var b=Date.parse(m[1]+'T00:00:00Z');if(!isNaN(b))t=b+(m[2]?+m[2]:12)*36e5}}
 return new Date(t)}
function esperado(n){var d=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate()));
 if(!(util(d)&&n.getUTCHours()>=H)){do{d=new Date(+d-D)}while(!util(d))}return d}
function faltam(p,e){var d=new Date(Date.parse(p+'T00:00:00Z')),c=0;
 while(c<99){d=new Date(+d+D);if(d>e)break;if(util(d))c++}return c}
var n=agora(),e=esperado(n),EST=[['ok','✓','Atualizado'],['aviso','!','Pode estar desatualizado'],['atraso','×','Desatualizado']];
function estado(p){var f=faltam(p,e);return {f:f,s:EST[f>=2?2:f]}}
window.MLselo={agora:n,esperado:iso(e),estado:estado};
document.querySelectorAll('.selo-dados[data-pregao]').forEach(function(el){
 var p=el.getAttribute('data-pregao'),r=estado(p);el.setAttribute('data-estado',r.s[0]);
 el.querySelector('.selo-ponto').textContent=r.s[1];
 el.querySelector('.selo-txt').textContent=el.classList.contains('selo-mini')?r.s[2]:r.s[2]+' · pregão de '+br(p);
 if(r.f>=1)el.title=(r.f===1?'Falta 1 pregão':'Faltam '+r.f+' pregões')+' desde '+br(p)+' (último esperado: '+br(iso(e))+')';
});
})();""")


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
    """Imagem og 1200×630. Guarda o texto que a gerou no comentário do JPEG e não
    redesenha se nada mudou: com 245 ativos, isso tira segundos do build e evita
    reescrever arquivos iguais."""
    assinatura = f"og1|{rotulo}|{titulo}|{sub}".encode("utf-8")
    arq = IMG / nome_arq
    if arq.exists():
        try:
            with Image.open(arq) as velho:
                if velho.info.get("comment") == assinatura:
                    return f"{DOMINIO}/assets/img/{nome_arq}"
        except OSError:
            pass
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
    im.save(arq, "JPEG", quality=84, optimize=True, progressive=True, comment=assinatura)
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
              f"{a['codigo']} ({nc}): cotação · {NOME}",
              f"{a['codigo']}: cotação de fechamento e histórico · {NOME}",
              f"{a['codigo']}: cotação e histórico · {NOME}"):
        if len(t) <= TITULO_MAX:
            return t
    falha(f"{a['codigo']}: sem título de até {TITULO_MAX}")


def descricao_ativo(a):
    nc, c = nome_curto(a), a["codigo"]
    if a["tipo"] == "bdr":
        nome = a["nome"]
        cands = [f"Cotação de fechamento do BDR {c} ({nome}) na B3, em reais: variação do dia, mínima, máxima, volume, gráfico de 12 meses e o que é um BDR.",
                 f"Fechamento do BDR {c} ({nome}) na B3, em reais: variação, mínima, máxima, volume, gráfico de 12 meses e o que é um BDR.",
                 f"Cotação de fechamento do BDR {c} na B3, em reais: variação do dia, mínima, máxima, volume, gráfico de 12 meses e o que é um BDR."]
    else:
        tipo = "da ação" if a["tipo"] == "acao" else "da cota do fundo imobiliário"
        fonte = "dados da CVM" if a["cad"] else "dados públicos"
        cands = [f"Cotação de fechamento {tipo} {c} ({nc}) na B3: variação do dia, mínima, máxima, volume, gráfico de 12 meses e {fonte}.",
                 f"Fechamento de {c} ({nc}) na B3: variação, mínima, máxima, volume, gráfico de 12 meses e {fonte}.",
                 f"Fechamento de {c} ({nc}) na B3: variação, mínima, máxima, volume e gráfico de 12 meses.",
                 f"Cotação de fechamento de {c} na B3: variação do dia, mínima, máxima, volume, gráfico de 12 meses e {fonte} sobre o papel."]
    for d in cands:
        if DESCRICAO_MIN <= len(d) <= DESCRICAO_MAX:
            return d
    falha(f"{a['codigo']}: sem descrição entre {DESCRICAO_MIN} e {DESCRICAO_MAX}")


TEXTO_BDR = ("<p>Um <strong>BDR</strong> (Brazilian Depositary Receipt, ou certificado de depósito de valores mobiliários) "
             "é um papel negociado na B3, em reais, que representa ações de uma empresa estrangeira guardadas no exterior "
             "por uma instituição depositária. Quem compra o BDR não compra a ação diretamente na bolsa de origem: compra "
             "o certificado emitido no Brasil, cujo preço acompanha o da ação lá fora, convertido pelo câmbio e pela proporção "
             "entre BDR e ação definida no programa.</p>")


def texto_ativo(a):
    c, cad = a["codigo"], a["cad"]
    isin = a["papel"]["isin"]
    if a["tipo"] == "bdr":
        inf = a["info"]
        prog = inf.get("programa", "")
        p1 = (f"<p><strong>{c}</strong> é o código de negociação na B3 de um BDR {PROGRAMA_BDR.get(prog, '')} "
              f"(especificação {e(prog)} no arquivo da B3) que tem por trás a empresa estrangeira <strong>{e(inf['emissor'])}</strong>, "
              f"segundo o cadastro de BDRs da B3. O ISIN do papel é {isin}.</p>")
        if prog == "DRN":
            p2 = ("<p>No BDR <strong>não patrocinado</strong>, o programa é aberto por uma instituição depositária no Brasil, "
                  "sem participação da empresa estrangeira, que não presta informações à CVM por causa dele.</p>")
        else:
            p2 = ("<p>No BDR <strong>patrocinado</strong>, a própria empresa estrangeira contrata o programa e tem registro na CVM; "
                  "por isso os comunicados dela aparecem nos dados abertos da CVM.</p>")
        p3 = ("<p><strong>O preço desta página é o do BDR na B3, em reais.</strong> Não é a cotação da ação na bolsa de origem, "
              "que é em outra moeda e por ação, e não por certificado.</p>")
        return TEXTO_BDR + p1 + p2 + p3
    esp, seg = especificacao(a)
    if not cad:
        if a["tipo"] == "fii":
            tipo = "cotas do fundo imobiliário"
            extra = (" O site não achou o cadastro deste fundo nos dados abertos da CVM (o ISIN da B3 não aparece no informe "
                     "mensal dos fundos imobiliários), e por isso não mostra razão social, administrador nem patrimônio: "
                     "é melhor não mostrar do que mostrar dado de outro fundo.")
        else:
            tipo = "ações"
            extra = " O cadastro da companhia não foi achado ativo nos dados abertos da CVM, e por isso esta página não traz razão social nem setor."
        return (f"<p><strong>{c}</strong> é o código de negociação de {tipo} na B3, com o nome de pregão "
                f"“{e(a['papel']['nome_pregao'])}” e ISIN {isin}.{extra}</p>")
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
        elif esp.startswith("units"):
            p3 = ("Units são certificados que reúnem mais de uma ação da companhia, em geral ordinárias e preferenciais, "
                  "e são negociados como um papel só.")
        else:
            p3 = ""
        if "IBOV" in a["indices"]:
            p3 += " O papel faz parte da carteira teórica vigente do Ibovespa."
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
          f"com ISIN {isin}." + (" O fundo faz parte da carteira teórica vigente do IFIX." if "IFIX" in a["indices"] else ""))
    return f"<p>{p1}</p><p>{p2}</p>"


def ficha_ativo(a):
    cad = a["cad"]
    if a["tipo"] == "bdr":
        inf = a["info"]
        linhas = [("Empresa estrangeira (B3)", inf["emissor"]),
                  ("Programa", f"BDR {PROGRAMA_BDR.get(inf.get('programa'), '')} ({inf.get('programa')})"),
                  ("Moeda da cotação", "Real (R$), na B3")]
    elif not cad:
        linhas = [("Cadastro na CVM", "não identificado")]
    elif a["tipo"] == "acao":
        esp, seg = especificacao(a)
        linhas = [("Razão social", cad["razao_social"]), ("CNPJ", cad["cnpj"]),
                  ("Código CVM", cad["codigo_cvm"]), ("Setor (CVM)", cad["setor"]),
                  ("Controle acionário (CVM)", cad["controle"].capitalize()),
                  ("Sede", f"{cad['municipio']} ({cad['uf']})"),
                  ("Registro na CVM", data_br(cad["registro_cvm"])),
                  ("Espécie", esp)]
        if seg:
            linhas.append(("Segmento de listagem", seg))
    else:
        dy = cad.get("dy_mes")
        linhas = [("Razão social", cad["razao_social"]), ("CNPJ", cad["cnpj"]),
                  ("Administrador", cad["administrador"].title()), ("Início de funcionamento", data_br(cad["inicio_funcionamento"])),
                  ("Mandato", cad["mandato"] or "não informado"),
                  ("Público-alvo", cad["publico_alvo"].capitalize()),
                  (f"Cotistas ({mes_ano(cad['referencia'])})", inteiro(cad["cotistas"])),
                  ("Cotas emitidas", inteiro(cad["cotas_emitidas"])),
                  ("Patrimônio líquido", compacto(cad["patrimonio_liquido"], True)),
                  ("Valor patrimonial por cota", brl(cad["vp_cota"]))]
        if dy is not None:
            linhas.append(("Dividend yield do mês informado à CVM", br(dy * 100) + "%"))
    if a["indices"]:
        linhas.append(("Índice (carteira vigente)", ", ".join({"IBOV": "Ibovespa", "IFIX": "IFIX"}.get(i, i) for i in a["indices"])))
    linhas += [("Código ISIN", a["papel"]["isin"]), ("Nome no pregão (B3)", a["papel"]["nome_pregao"])]
    return '<dl class="ficha">' + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in linhas) + "</dl>"


def lista_comunicados(docs, mostrar_ativo=None):
    """Lista de documentos oficiais (CVM / Fundos.NET). mostrar_ativo: função doc -> HTML do(s) código(s)."""
    itens = []
    for d in docs:
        quem = f' · <span class="com-ativo">{mostrar_ativo(d)}</span>' if mostrar_ativo else ""
        itens.append(f'<li><span class="com-meta"><time datetime="{d["d"]}">{data_br(d["d"])}</time> · {e(d["c"])}{quem}</span>'
                     f'<a href="{e(d["u"])}" rel="noopener nofollow">{e(d["a"])}</a></li>')
    return '<ul class="comunicados">' + "".join(itens) + "</ul>"


def outros_ativos(a, todos):
    """Até 12 do mesmo tipo: na ação, primeiro as do mesmo setor da CVM; depois pelo volume do último pregão."""
    mesmo = [x for x in todos if x["tipo"] == a["tipo"] and x is not a]
    setor = (a["cad"] or {}).get("setor") if a["tipo"] == "acao" else None
    chave = lambda x: (0 if (setor and (x["cad"] or {}).get("setor") == setor) else 1, -x["ult"]["volume"])
    return sorted(mesmo, key=chave)[:12]


# --- indicadores, dividendos, comparação ---------------------------------------
# Tudo calculado aqui sai de dado oficial com data: COTAHIST (B3) para preço e volume,
# DFP/ITR e informe mensal (CVM) para balanço e rendimentos, SGS (Banco Central) para
# CDI e IPCA. O que não tem fonte vira "—" com a explicação no "?".

FUND = ler_json(DADOS / "fundamentos.json") if (DADOS / "fundamentos.json").exists() else {"empresas": {}, "fiis": {}, "units": {}, "fontes": {}}
BCB = ler_json(DADOS / "bcb.json") if (DADOS / "bcb.json").exists() else {"series": {}}
REFERENCIAS_ETF = {"BOVA11": "Ibovespa", "SMAL11": "Small Caps (SMLL)", "IVVB11": "S&P 500 em reais", "XFIX11": "IFIX",
                   "DIVO11": "IDIV (dividendos)"}
GUIA = {"pl": "o-que-e-p-l", "dy": "o-que-e-dividend-yield"}


def setor_comparacao(a):
    """Setor de atividade do cadastro da CVM. "Emp. Adm. Part. - X" é a holding do setor X
    (convenção da própria CVM), então entra junto com X."""
    s = (a["cad"] or {}).get("setor") or ""
    return re.sub(r"^Emp\. Adm\. Part\. - ", "", s).strip() or None


def serie_longa(a):
    """Fechamentos desde 2021 (dados/historico, só data e fechamento) + 2025 em diante.
    Na parte antiga, a série começa DEPOIS da última variação acima de 25% que não tenha
    evento declarado: número sem explicação não vai para o gráfico."""
    rows = [(r["data"], r["fechamento"]) for r in a["rows"]]
    arq = DADOS / "historico" / f"{a['codigo']}.csv"
    corte = None
    if arq.exists():
        with arq.open(encoding="utf-8") as f:
            antes = [(l["data"], float(l["fechamento"])) for l in csv.DictReader(f) if l["data"] < rows[0][0]]
        tudo = antes + rows
        for i in range(1, len(antes) + 1):
            (d0, p0), (d1, p1) = tudo[i - 1], tudo[i]
            if abs(p1 / p0 - 1) * 100 > VARIACAO_MAX and d1 not in a["evento"]:
                corte = d1
        if corte:
            tudo = [x for x in tudo if x[0] >= corte]
        rows = tudo
    return rows, corte


def fatores_desdobramento(a):
    """[(data, razão de preço)] dos eventos em ações declarados (desdobramento, grupamento,
    bonificação), e as datas de cisão (sem razão: a comparação não vale)."""
    sp, cis = [], []
    for d, x in a["evento"].items():
        if x["tipo"] != "evento":
            continue
        if x.get("fator_preco"):
            sp.append((d, x["fator_preco"]))
        elif "isão" in x["evento"]:
            cis.append(d)
    return sorted(sp), sorted(cis)


def var_12m(a, serie):
    fim = serie[-1]
    alvo = (dt.date.fromisoformat(fim[0]) - dt.timedelta(days=365)).isoformat()
    antes = [x for x in serie if x[0] <= alvo]
    if not antes:
        return None, "o histórico disponível do papel tem menos de 12 meses"
    ini = antes[-1]
    sp, cis = fatores_desdobramento(a)
    if any(ini[0] < d <= fim[0] for d in cis):
        return None, "houve cisão no período, e o preço de antes não é comparável com o de depois"
    p0 = ini[1]
    for d, f in sp:
        if ini[0] < d <= fim[0]:
            p0 *= f
    return (fim[1] / p0 - 1) * 100, ini[0]


def liquidez(a, pregoes):
    ult30 = pregoes[-30:]
    vol = {r["data"]: r["volume"] for r in a["rows"]}
    return sum(vol.get(d, 0.0) for d in ult30) / len(ult30), ult30[0], ult30[-1]


def unit_fator(a):
    esp = a["papel"]["especificacao"].split()[0]
    if esp != "UNT":
        return 1, None
    u = FUND.get("units", {}).get(a["codigo"])
    return (u["acoes"], u["composicao"]) if u else (None, None)


def fundamentos_acao(a):
    """Por ação: lucro, PL, proventos, receita (12 meses) e ações, com as datas-base."""
    e = FUND["empresas"].get(a["info"].get("cnpj") or "")
    if not e:
        return None
    fu, comp = unit_fator(a)
    return {"e": e, "ttm": e.get("ttm") or {}, "acoes": e.get("acoes"), "fu": fu, "comp": comp}


def rendimentos_fii(a):
    return FUND["fiis"].get(a["info"].get("cnpj") or "", [])


def pct(v, casas=2):
    return ("+" if v > 0 else "−" if v < 0 else "") + br(abs(v), casas) + "%"


def indicadores(a, pregoes):
    """Lista de cartões: (chave, rótulo, valor_html, ajuda_html)."""
    u = a["ult"]
    preco = u["fechamento"]
    serie, corte = a["serie"], a["corte"]
    cards = []
    cot_aj = (f"Preço do último negócio de {a['codigo']} no pregão de {data_br(u['data'])}, no mercado à vista da B3 "
              f"(série histórica COTAHIST). A pílula é a variação sobre o fechamento anterior com negócio ({data_br(a['ant']['data'])}).")
    cards.append(("cotacao", "Cotação", f'<span class="ind-valor num">R$ {br(preco)}</span> {var_html(u["var"], selo=True)}', cot_aj))
    v12, info = var_12m(a, serie)
    if v12 is None:
        val, aj = "—", f"Sem número: {info}."
    else:
        sp, _ = fatores_desdobramento(a)
        seta = "▲" if v12 > 0 else "▼" if v12 < 0 else ""
        cl = "alta" if v12 > 0 else "baixa" if v12 < 0 else "zero"
        val = f'<span class="ind-valor num var {cl}">{seta} {pct(v12)}</span>'
        corr = " Desdobramentos e grupamentos do período foram descontados, para a conta não mostrar um salto que não é ganho nem perda." if any(info < d <= u["data"] for d, _ in sp) else ""
        aj = (f"Fechamento de {data_br(u['data'])} comparado com o de {data_br(info)}, o último pregão até um ano antes "
              f"(COTAHIST, B3). Preço bruto: não inclui proventos (dividendos, JCP, rendimentos).{corr}")
    cards.append(("var12", "Variação (12M)", val, aj))
    liq, i30, f30 = liquidez(a, pregoes)
    cards.append(("liq", "Liquidez diária", f'<span class="ind-valor num">{compacto(liq, True)}</span>',
                  f"Média do volume financeiro negociado por pregão nos últimos 30 pregões da B3, de {data_br(i30)} a {data_br(f30)} "
                  "(dia sem negócio conta como zero). Fonte: COTAHIST, B3."))
    if a["tipo"] == "acao":
        f = fundamentos_acao(a)
        base = ""
        if f and f["ttm"].get("fim"):
            base = (f"Lucro dos 12 meses até {data_br(f['ttm']['fim'])} ({e(f['ttm']['doc'])}; {e(f['ttm'].get('lucro_fonte') or '')}), "
                    f"patrimônio de {data_br(f['e']['pl_data'])} e ações da composição do capital de {data_br(f['e']['acoes_data'])}, menos as em tesouraria — "
                    "dados abertos da CVM (DFP/ITR).")
        motivo = None
        if not f:
            motivo = "a companhia não tem demonstrações nos dados abertos da CVM lidos pelo site."
        elif not f["acoes"]:
            motivo = (f["e"].get("acoes_motivo") or "sem número de ações") + "."
        elif not f["fu"]:
            motivo = "a composição desta unit (quantas ações ela reúne) não está no formulário cadastral da CVM."
        unit_txt = f" Esta unit reúne {f['fu']} ações ({e(f['comp'])}, segundo o formulário cadastral da CVM), então o lucro e o patrimônio por ação são multiplicados por {f['fu']}." if f and f.get("comp") else ""
        if motivo:
            for k, rot, g in (("pl", "P/L", "pl"), ("pvp", "P/VP", None), ("dy", "DY (12M)", "dy")):
                cards.append((k, rot, '<span class="ind-valor num">—</span>', f"Sem número: {motivo}"))
        else:
            n, fu, t, pl = f["acoes"], f["fu"], f["ttm"], f["e"]["pl"]
            lpa = t["lucro"] / n * fu if t.get("lucro") is not None else None
            if lpa is None:
                cards.append(("pl", "P/L", '<span class="ind-valor num">—</span>', "Sem lucro de 12 meses nos dados da CVM."))
            elif lpa <= 0:
                cards.append(("pl", "P/L", '<span class="ind-valor num">n/a <small>(prejuízo)</small></span>',
                              f"A companhia teve prejuízo nos 12 meses (R$ {compacto(t['lucro'])}), e P/L com lucro negativo não tem leitura. {base}{unit_txt}"))
            else:
                cards.append(("pl", "P/L", f'<span class="ind-valor num">{br(preco / lpa)}</span>',
                              f"Preço ÷ lucro por ação. Lucro por ação = lucro líquido de 12 meses atribuído aos controladores ÷ número de ações "
                              f"= R$ {br(lpa, 4)}. {base}{unit_txt}"))
            if pl is None:
                cards.append(("pvp", "P/VP", '<span class="ind-valor num">—</span>', "Sem patrimônio líquido nos dados da CVM."))
            elif pl <= 0:
                cards.append(("pvp", "P/VP", '<span class="ind-valor num">n/a <small>(PL negativo)</small></span>', f"Patrimônio líquido negativo. {base}"))
            else:
                vpa = pl / n * fu
                cards.append(("pvp", "P/VP", f'<span class="ind-valor num">{br(preco / vpa)}</span>',
                              f"Preço ÷ valor patrimonial por ação. Valor patrimonial por ação = patrimônio líquido atribuído aos controladores ÷ "
                              f"número de ações = R$ {br(vpa, 4)}. {base}{unit_txt}"))
            if t.get("prov") is None:
                cards.append(("dy", "DY (12M)", '<span class="ind-valor num">—</span>',
                              "Sem número: a demonstração das mutações do patrimônio líquido (DMPL) desta companhia na CVM não permite separar os proventos com segurança."))
            else:
                dps = t["prov"] / n * fu
                cards.append(("dy", "DY (12M)", f'<span class="ind-valor num">{br(dps / preco * 100)}%</span>',
                              f"Proventos de 12 meses por ação ÷ preço. Proventos = dividendos e juros sobre capital próprio declarados no período, "
                              f"como aparecem na DMPL (CVM), R$ {br(dps, 4)} por {'unit' if fu > 1 else 'ação'}. É o valor declarado no período do balanço "
                              f"(até {data_br(t['fim'])}), não o pago nos últimos 12 meses corridos; JCP entra bruto, antes do imposto. {base}"))
    elif a["tipo"] == "fii":
        ms = rendimentos_fii(a)
        cad = a["cad"]
        if cad and cad.get("vp_cota"):
            cards.append(("pvp", "P/VP", f'<span class="ind-valor num">{br(preco / cad["vp_cota"])}</span>',
                          f"Preço ÷ valor patrimonial da cota informado pelo fundo à CVM no informe mensal de {mes_ano(cad['referencia'])}: "
                          f"R$ {br(cad['vp_cota'], 4)}."))
        else:
            cards.append(("pvp", "P/VP", '<span class="ind-valor num">—</span>', "Sem informe mensal do fundo identificado na CVM."))
        ult12 = ms[-12:]
        ok12 = len(ult12) == 12 and meses_seguidos([m[0] for m in ult12])
        if ok12:
            soma = sum(m[1] for m in ult12)
            cards.insert(1, ("dy", "DY (12M)", f'<span class="ind-valor num">{br(soma / preco * 100)}%</span>',
                             f"Rendimentos por cota dos 12 meses de {mes_curto(ult12[0][0])} a {mes_curto(ult12[-1][0])} ÷ preço. "
                             f"Rendimento de cada mês = percentual de dividend yield do mês × valor patrimonial da cota, como o fundo informa à CVM "
                             f"no informe mensal (o informe não traz o valor pago por cota nem a data com). Soma: R$ {br(soma, 4)} por cota."))
        else:
            cards.insert(1, ("dy", "DY (12M)", '<span class="ind-valor num">—</span>',
                             "Sem número: faltam informes mensais do fundo na CVM para fechar 12 meses seguidos."))
    ordem = {"acao": ["cotacao", "var12", "pl", "pvp", "dy", "liq"], "fii": ["cotacao", "dy", "pvp", "liq", "var12"],
             "bdr": ["cotacao", "var12", "liq"]}[a["tipo"]]
    por = {c[0]: c for c in cards}
    return [por[k] for k in ordem if k in por]


def meses_seguidos(ms):
    for a, b in zip(ms, ms[1:]):
        y, m = int(a[:4]), int(a[5:7])
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        if b != f"{y2}-{m2:02d}":
            return False
    return True


def mes_curto(ym):
    return f"{MESES[int(ym[5:7]) - 1]}/{ym[:4]}"


def cartoes_indicadores(cards):
    itens = []
    for k, rot, val, aj in cards:
        g = {"dy": "o-que-e-dividend-yield", "pl": "o-que-e-p-l"}.get(k)
        guia = f' <a href="../guias/{g}.html">Leia o guia</a>.' if g else ""
        itens.append(f'<div class="ind" id="ind-{k}"><div class="ind-topo"><span class="ind-rot">{e(rot)}</span>'
                     f'<details class="ajuda"><summary aria-label="O que é {e(rot)} e de onde vem">?</summary>'
                     f'<div class="ajuda-txt"><p>{aj}{guia}</p></div></details></div>{val}</div>')
    return '<div class="indicadores">' + "".join(itens) + "</div>"


# --- histórico de dividendos ------------------------------------------------------

def preco_fim_ano(serie):
    """Último fechamento de cada ano civil na série."""
    out = {}
    for d, p in serie:
        out[d[:4]] = p
    return out


def dividendos(a):
    """Anos (com o 'Últ. 12M'): valor por ação/cota e DY sobre o preço do fim do ano.
    Devolve dict com 'anos' [(rótulo, valor, dy%)], cartões e linhas da tabela."""
    pfa = preco_fim_ano(a["serie"])
    ano_atual = a["ult"]["data"][:4]
    preco = a["ult"]["fechamento"]
    if a["tipo"] == "acao":
        f = fundamentos_acao(a)
        if not f or not f["acoes"] or not f["fu"]:
            return None
        e_, fu = f["e"], f["fu"]
        anos = []
        for y, v in sorted(e_["anos"].items()):
            if v.get("prov") is None or not v.get("acoes"):
                continue
            dps = v["prov"] / v["acoes"] * fu
            dy = dps / pfa[y] * 100 if y in pfa and y != ano_atual else None
            payout = v["prov"] / v["lucro"] * 100 if v.get("lucro") and v["lucro"] > 0 else None
            anos.append({"rot": y, "v": dps, "dy": dy, "payout": payout})
        t = f["ttm"]
        if t.get("prov") is not None:
            dps = t["prov"] / f["acoes"] * fu
            anos.append({"rot": "Últ. 12M", "v": dps, "dy": dps / preco * 100,
                         "payout": t["prov"] / t["lucro"] * 100 if t.get("lucro") and t["lucro"] > 0 else None})
        if not anos:
            return None
        fonte = ("Proventos (dividendos e JCP) declarados em cada exercício, da demonstração das mutações do patrimônio líquido "
                 "(DFP), divididos pelas ações do fim do exercício; dados abertos da CVM. Só entram os anos em que o número de ações "
                 "é o mesmo de hoje (sem desdobramento no meio), para o valor por ação ser comparável.")
    else:
        ms = rendimentos_fii(a)
        if not ms:
            return None
        por = {}
        for m, rend, vp, dy in ms:
            por.setdefault(m[:4], []).append(rend)
        anos = []
        for y, vs in sorted(por.items()):
            if y == ano_atual or len(vs) < 12:
                continue
            anos.append({"rot": y, "v": sum(vs), "dy": sum(vs) / pfa[y] * 100 if y in pfa else None, "payout": None})
        ult12 = ms[-12:]
        if len(ult12) == 12 and meses_seguidos([m[0] for m in ult12]):
            s = sum(m[1] for m in ult12)
            anos.append({"rot": "Últ. 12M", "v": s, "dy": s / preco * 100, "payout": None})
        if not anos:
            return None
        fonte = ("Rendimento por cota de cada mês = percentual de dividend yield do mês × valor patrimonial da cota, do informe "
                 "mensal do fundo na CVM; o ano soma os 12 meses (ano incompleto não entra). DY anual = soma do ano ÷ último "
                 "fechamento do ano na B3.")
    ult5 = [x for x in anos if x["rot"] != "Últ. 12M"][-5:]
    dy5 = [x["dy"] for x in ult5 if x["dy"] is not None]
    pay5 = [x["payout"] for x in ult5 if x["payout"] is not None]
    atual = anos[-1] if anos[-1]["rot"] == "Últ. 12M" else None
    return {"anos": anos, "fonte": fonte,
            "dy_atual": atual["dy"] if atual else None,
            "dy_medio5": sum(dy5) / len(dy5) if len(dy5) == 5 else None,
            "payout_atual": atual["payout"] if atual else None,
            "payout_medio5": sum(pay5) / len(pay5) if len(pay5) == 5 else None,
            "anos5": [x["rot"] for x in ult5]}


def secao_dividendos(a):
    dv = dividendos(a)
    if a["tipo"] == "bdr":
        return ""
    unid = "cota" if a["tipo"] == "fii" else ("unit" if a["papel"]["especificacao"].startswith("UNT") else "ação")
    if not dv:
        return (f'<h2 id="dividendos">Histórico de dividendos</h2><p class="data-regra">Sem histórico de proventos com fonte oficial aberta '
                f'para {a["codigo"]}: {"o fundo não tem informes mensais identificados na CVM" if a["tipo"] == "fii" else "faltam na CVM o número de ações ou proventos separáveis na DMPL"}. '
                'O site não estima nem completa esse dado.</p>')
    fmt = lambda v, f=br: "—" if v is None else f(v) + "%"
    anos5 = ", ".join(dv["anos5"])
    cards = [("DY atual (12M)", fmt(dv["dy_atual"]), "Proventos dos últimos 12 meses ÷ preço de hoje. " + dv["fonte"]),
             ("DY médio (5 anos)", fmt(dv["dy_medio5"]), f"Média simples do DY de cada um dos 5 últimos anos completos ({anos5}), "
                                                           "cada um sobre o último fechamento do próprio ano. Sem os 5 anos com preço e proventos, fica “—”.")]
    if a["tipo"] == "acao":
        cards += [("Payout atual", fmt(dv["payout_atual"]), "Proventos declarados nos 12 meses ÷ lucro líquido dos 12 meses atribuído aos controladores (CVM). "
                                                          "Com prejuízo no período, fica “—”."),
                  ("Payout médio (5 anos)", fmt(dv["payout_medio5"]), f"Média simples do payout de cada um dos 5 últimos exercícios ({anos5}), da DFP (CVM).")]
    cards_html = '<div class="indicadores ind-4">' + "".join(
        f'<div class="ind"><div class="ind-topo"><span class="ind-rot">{e(r)}</span><details class="ajuda"><summary aria-label="Como é calculado: {e(r)}">?</summary>'
        f'<div class="ajuda-txt"><p>{e(aj)}</p></div></details></div><span class="ind-valor num">{v}</span></div>' for r, v, aj in cards) + "</div>"
    dados = json.dumps([[x["rot"], round(x["v"], 6), None if x["dy"] is None else round(x["dy"], 4)] for x in dv["anos"]], separators=(",", ":"))
    tabela_anos = ("<div class=\"rolagem\"><table><caption>Proventos por ano, por " + unid + "</caption><thead><tr><th>Ano</th><th class=\"n\">Valor (R$)</th>"
                   "<th class=\"n\">DY</th>" + ("<th class=\"n\">Payout</th>" if a["tipo"] == "acao" else "") + "</tr></thead><tbody>"
                   + "".join(f"<tr><td>{x['rot']}</td><td class=\"n\">{br(x['v'], 4)}</td><td class=\"n\">{fmt(x['dy'])}</td>"
                             + (f"<td class=\"n\">{fmt(x['payout'])}</td>" if a["tipo"] == "acao" else "") + "</tr>" for x in reversed(dv["anos"]))
                   + "</tbody></table></div>")
    if a["tipo"] == "fii":
        ms = rendimentos_fii(a)[-24:]
        eventos = ("<h3>Rendimentos mês a mês</h3><div class=\"rolagem\"><table class=\"ver-mais\" data-mostra=\"6\"><caption>Do informe mensal à CVM, mais recente primeiro</caption>"
                   "<thead><tr><th>Tipo</th><th>Mês de referência</th><th class=\"n\">Valor por cota (R$)</th><th class=\"n\">DY do mês sobre o valor patrimonial</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>Rendimento</td><td>{mes_curto(m)}</td><td class=\"n\">{br(r, 4)}</td><td class=\"n\">{br(dy * 100, 4)}%</td></tr>" for m, r, vp, dy in reversed(ms))
                   + "</tbody></table></div><p class=\"data-regra\">O informe mensal não traz data com nem data de pagamento, e o valor por cota é "
                     "derivado (percentual informado × valor patrimonial da cota): pode diferir em centavos do anúncio do fundo. Os anúncios oficiais "
                     "de rendimento ficam em <a href=\"#comunicados\">Últimos comunicados</a>.</p>")
    else:
        avisos = [d for d in a["comunicados_todos"] if d.get("p")][:12]
        eventos = ("<h3>Avisos oficiais sobre proventos</h3>"
                   + (lista_comunicados(avisos) if avisos else "<p class=\"data-regra\">Nenhum aviso sobre proventos no período coletado.</p>")
                   + "<p class=\"data-regra\">Tipo, data com, data de pagamento e valor de cada provento estão nesses documentos, entregues pela companhia "
                     "à CVM. O site não monta uma tabela com esses campos porque eles não existem como dado aberto estruturado na CVM, e a página "
                     "de proventos da B3 é de uso pessoal pelos termos de uso dela.</p>")
    return (f'<h2 id="dividendos">Histórico de dividendos</h2>{cards_html}'
            f'<div class="div-grafico" data-unid="{unid}"><div class="botoes" role="group" aria-label="Medida">'
            '<button type="button" data-med="dy" aria-pressed="true">Dividend yield (%)</button>'
            f'<button type="button" data-med="v" aria-pressed="false">Valor por {unid} (R$)</button></div>'
            '<div class="botoes" role="group" aria-label="Período"><button type="button" data-per="5" aria-pressed="true">5A</button>'
            '<button type="button" data-per="10" aria-pressed="false">10A</button><button type="button" data-per="0" aria-pressed="false">MÁX</button></div>'
            f'<div class="div-barras" role="img" aria-label="Proventos por ano"></div><script type="application/json" class="div-dados">{dados}</script></div>'
            f'{tabela_anos}<p class="data-regra">Fonte: {e(dv["fonte"])}</p>{eventos}')


# --- comparação com outras ações do setor ---------------------------------------------

def linha_par(a, pregoes):
    f = fundamentos_acao(a)
    preco = a["ult"]["fechamento"]
    v12, _ = var_12m(a, a["serie"])
    d = {"dy": None, "pl": None, "pvp": None, "roe": None, "mg": None, "pl_neg": False}
    if f and f["ttm"]:
        t, e_ = f["ttm"], f["e"]
        if t.get("lucro") is not None and e_.get("pl") and e_["pl"] > 0:
            d["roe"] = t["lucro"] / e_["pl"] * 100
        if t.get("lucro") is not None and t.get("receita"):
            d["mg"] = t["lucro"] / t["receita"] * 100
        if f["acoes"] and f["fu"]:
            n, fu = f["acoes"], f["fu"]
            if t.get("lucro") is not None:
                if t["lucro"] > 0:
                    d["pl"] = preco / (t["lucro"] / n * fu)
                else:
                    d["pl_neg"] = True
            if e_.get("pl") and e_["pl"] > 0:
                d["pvp"] = preco / (e_["pl"] / n * fu)
            if t.get("prov") is not None:
                d["dy"] = t["prov"] / n * fu / preco * 100
    return {"a": a, "preco": preco, "v12": v12, **d}


def secao_pares(a, todos, pregoes):
    setor = setor_comparacao(a)
    if a["tipo"] != "acao" or not setor:
        return ""
    pares = [x for x in todos if x["tipo"] == "acao" and setor_comparacao(x) == setor]
    if len(pares) < 2:
        return ""
    pares.sort(key=lambda x: (x is not a, -x["ult"]["volume"]))
    datas = sorted({(fundamentos_acao(x) or {}).get("ttm", {}).get("fim") for x in pares} - {None})
    num = lambda v, suf="": "—" if v is None else br(v) + suf
    linhas = []
    for i, x in enumerate(pares):
        p = linha_par(x, pregoes)
        v12 = p["v12"]
        pil = "—" if v12 is None else var_html(v12, selo=True)
        pl_txt = "n/a" if p["pl_neg"] else num(p["pl"])
        attr = lambda v: "" if v is None else round(v, 4)
        linhas.append(f'<tr{" class=\"este\"" if x is a else ""} data-c="{x["codigo"]}" data-preco="{p["preco"]}" data-v12="{attr(v12)}" data-dy="{attr(p["dy"])}" '
                      f'data-pl="{attr(p["pl"])}" data-pvp="{attr(p["pvp"])}" data-roe="{attr(p["roe"])}" data-mg="{attr(p["mg"])}">'
                      f'<td><div class="ativo-cel">{selo(x, "p")}<div><a href="{x["slug"]}.html">{x["codigo"]}</a><br><span class="nome">{e(nome_curto(x))}</span></div></div></td>'
                      f'<td class="n">{br(p["preco"])}</td><td class="n">{pil}</td><td class="n">{num(p["dy"], "%")}</td><td class="n">{pl_txt}</td>'
                      f'<td class="n">{num(p["pvp"])}</td><td class="n">{num(p["roe"], "%")}</td><td class="n">{num(p["mg"], "%")}</td></tr>')
    cols = [("c", "Ativo"), ("preco", "Cotação (R$)"), ("v12", "Variação 12M"), ("dy", "DY"), ("pl", "P/L"), ("pvp", "P/VP"),
            ("roe", "ROE"), ("mg", "Margem líquida")]
    cab = "".join(f'<th{"" if k == "c" else " class=\"n\""}><button type="button" data-ord="{k}">{r}</button></th>' for k, r in cols)
    ajuda = (f"Ações acompanhadas pelo site com o mesmo setor de atividade no cadastro da CVM (“{e(setor)}”; holdings do setor, que a CVM marca como "
             "“Emp. Adm. Part.”, entram junto). Preço e variação de 12 meses: COTAHIST (B3), variação sem proventos e descontados desdobramentos. "
             "DY = proventos de 12 meses (DMPL) ÷ ações ÷ preço. P/L = preço ÷ (lucro de 12 meses ÷ ações); “n/a” quando houve prejuízo. "
             "P/VP = preço ÷ (patrimônio líquido ÷ ações). ROE = lucro líquido de 12 meses ÷ patrimônio líquido. Margem líquida = lucro "
             "líquido de 12 meses ÷ receita líquida de 12 meses (bancos e seguradoras não têm “receita de venda” e ficam sem margem). "
             f"Lucro, patrimônio e proventos: dados abertos da CVM (DFP/ITR), data-base {', '.join(data_br(d) for d in datas)}. Sem fonte, “—”.")
    return (f'<h2 id="pares">Comparando {a["codigo"]} com outras ações do setor</h2>'
            f'<div class="pares-topo"><p class="data-regra">Setor: {e(setor)} (cadastro da CVM). A ordem inicial é pelo volume do último pregão; '
            'toque no título de uma coluna para ordenar.</p><details class="ajuda"><summary aria-label="Fórmulas e data-base">?</summary>'
            f'<div class="ajuda-txt"><p>{ajuda}</p></div></details></div>'
            f'<div class="rolagem"><table class="pares ver-mais" data-mostra="5"><caption>{len(pares)} ações de {e(setor)} acompanhadas pelo site</caption>'
            f'<thead><tr>{cab}</tr></thead><tbody>{"".join(linhas)}</tbody></table></div>')


# --- arquivos de série (carregados sob demanda pelo navegador) -----------------------------

def compacta(serie):
    d0 = dt.date.fromisoformat(serie[0][0])
    plano, ant = [], d0
    for d, p in serie:
        dd = dt.date.fromisoformat(d)
        plano += [(dd - ant).days, p]
        ant = dd
    return {"d0": serie[0][0], "s": plano}


def ajustes_fii(a):
    """Fatores de ajuste por rendimento (FII): rendimento do mês de referência aplicado no
    primeiro pregão do mês seguinte, fator = 1 − rendimento ÷ fechamento anterior.
    Aproximação declarada: o informe da CVM não traz a data com."""
    ms = rendimentos_fii(a)
    if not ms:
        return []
    datas = [d for d, _ in a["serie"]]
    precos = dict(a["serie"])
    out = []
    for m, rend, vp, dy in ms:
        y, mm = int(m[:4]), int(m[5:7])
        prox = f"{y + 1}-01" if mm == 12 else f"{y}-{mm + 1:02d}"
        dia = next((d for d in datas if d[:7] == prox), None)
        if not dia or rend <= 0:
            continue
        i = datas.index(dia)
        if i == 0:
            continue
        ant = precos[datas[i - 1]]
        if rend < ant:
            out.append([dia, round(1 - rend / ant, 8)])
    return out


def escreve_series(ativos, pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    escritos = set()
    for a in ativos:
        sp, _ = fatores_desdobramento(a)
        dado = {"c": a["codigo"], "t": a["tipo"], **compacta(a["serie"]), "sp": [[d, f] for d, f in sp]}
        if a["tipo"] == "fii":
            aj = ajustes_fii(a)
            if aj:
                dado["aj"] = aj
        txt = json.dumps(dado, separators=(",", ":"))
        arq = pasta / f"{a['slug']}.json"
        if not arq.exists() or arq.read_text(encoding="utf-8") != txt:
            arq.write_text(txt, encoding="utf-8")
        escritos.add(arq.name)
    # referências: ETFs da B3 (COTAHIST), CDI e IPCA (Banco Central)
    ref = {"etf": {}, "nomes": REFERENCIAS_ETF}
    for c in REFERENCIAS_ETF:
        rs = []
        h = DADOS / "historico" / f"{c}.csv"
        if h.exists():
            with h.open(encoding="utf-8") as f:
                rs += [(l["data"], float(l["fechamento"])) for l in csv.DictReader(f)]
        cot = DADOS / "cotacoes" / f"{c}.csv"
        if cot.exists():
            with cot.open(encoding="utf-8") as f:
                rs += [(l["data"], float(l["fechamento"])) for l in csv.DictReader(f) if not rs or l["data"] > rs[-1][0]]
        if rs:
            for (d0, p0), (d1, p1) in zip(rs, rs[1:]):
                if abs(p1 / p0 - 1) * 100 > VARIACAO_MAX:
                    falha(f"{c} (referência) {d1}: variação de {(p1 / p0 - 1) * 100:+.1f}% — confira antes de publicar")
            ref["etf"][c] = compacta(rs)
    cdi = BCB["series"].get("cdi", {}).get("pontos")
    ipca = BCB["series"].get("ipca", {}).get("pontos")
    if cdi:
        ref["cdi"] = {"d": [p[0] for p in cdi], "v": [p[1] for p in cdi]}
    if ipca:
        ref["ipca"] = {"m": [p[0][:7] for p in ipca], "v": [p[1] for p in ipca]}
    ref["lista"] = [[a["codigo"], a["slug"], nome_curto(a)] for a in sorted(ativos, key=lambda a: a["codigo"])]
    txt = json.dumps(ref, ensure_ascii=False, separators=(",", ":"))
    arq = pasta / "_ref.json"
    if not arq.exists() or arq.read_text(encoding="utf-8") != txt:
        arq.write_text(txt, encoding="utf-8")
    escritos.add(arq.name)
    for velho in pasta.glob("*.json"):
        if velho.name not in escritos:
            velho.unlink()


ICONE_TIPO = {
    # desenhos próprios, genéricos por tipo (nenhum logotipo de empresa)
    "acao": _icone('<path d="M3 21h18"/><path d="M5 21V10l5 3V10l5 3V6l4 2v13"/><path d="M8 17h1M12 17h1M16 17h1"/>'),
    "fii": _icone('<path d="M4 21V5l8-3v19"/><path d="M12 9h8v12"/><path d="M7 7h2M7 11h2M7 15h2M15 13h2M15 17h2"/><path d="M2 21h20"/>'),
    "bdr": _icone('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.6 2.6 3.9 5.6 3.9 9s-1.3 6.4-3.9 9c-2.6-2.6-3.9-5.6-3.9-9S9.4 5.6 12 3z"/>'),
}
ICONE_COMPARTILHAR = _icone('<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.6M8.2 13.2l7.6 4.6"/>')
ICONE_ESTRELA = _icone('<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8L3.5 9.7l5.9-.8z"/>')


def secao_comparacao(a):
    ser = "o preço do ativo com os rendimentos reinvestidos (aproximação pelo informe mensal da CVM)" if a["tipo"] == "fii" else "só a variação de preço do ativo (sem proventos)"
    return f"""<h2 id="comparacao">Comparação com índices</h2>
<div class="comp" data-slug="{a['slug']}" data-cod="{a['codigo']}" data-tipo="{a['tipo']}">
<div class="graf-ctl"><div class="botoes" role="group" aria-label="Período da comparação">
<button type="button" data-p="1A" aria-pressed="true">1A</button><button type="button" data-p="2A" aria-pressed="false">2A</button><button type="button" data-p="5A" aria-pressed="false">5A</button></div>
<details class="ajuda"><summary aria-label="De onde vêm as séries da comparação">?</summary><div class="ajuda-txt"><p>Rentabilidade acumulada no período, em %.
<strong>{a['codigo']}</strong>: {ser}, do COTAHIST (B3), com desdobramentos e grupamentos descontados.
<strong>CDI</strong>: taxa DI diária do Banco Central (SGS, série 12), acumulada dia a dia.
<strong>IPCA</strong>: variação mensal do Banco Central (SGS, série 433), acumulada mês a mês (o mês corrente entra quando o IBGE divulga).
<strong>Índices da B3</strong>: o site não republica a série dos índices; usa o ETF negociado na própria B3 que acompanha cada um
(BOVA11 para o Ibovespa, SMAL11 para o SMLL, XFIX11 para o IFIX, DIVO11 para o IDIV, IVVB11 para o S&amp;P 500 em reais), pelo preço de
fechamento do COTAHIST. ETF cobra taxa de administração e pode se afastar do índice; distribuições do ETF, se houver, não estão incluídas.</p></div></details></div>
<div class="comp-legenda" role="group" aria-label="Séries do gráfico"></div>
<div class="comp-area"><p class="sem-js">A comparação é desenhada no navegador e precisa de JavaScript.</p></div>
<form class="simulador" onsubmit="return false">
<p class="sim-linha"><label for="sim-valor">Se você tivesse investido R$</label> <input id="sim-valor" inputmode="decimal" value="1.000" size="9">
<span class="sim-per">há 1 ano</span>, hoje teria:</p>
<ul class="sim-res" aria-live="polite"></ul>
<p class="aviso sim-aviso"><strong>Simulação com dados passados.</strong> Valores brutos, sem impostos, taxas e custos de corretagem. Rentabilidade passada não garante resultado futuro. Isto não é recomendação de investimento.
{"O valor do ativo inclui os rendimentos reinvestidos, pela aproximação do informe mensal da CVM; os ETFs entram só pelo preço." if a["tipo"] == "fii" else "O valor do ativo e o dos ETFs são só a variação de preço, sem proventos; o CDI é a taxa acumulada."}</p>
</form>
</div>"""


def pagina_ativo(a, todos, ultimo, og_url, cad_gerado, pregoes):
    base = "../"
    c, u, ant = a["codigo"], a["ult"], a["ant"]
    url = f"{DOMINIO}/ativos/{a['slug']}.html"
    titulo, desc = titulo_ativo(a), descricao_ativo(a)
    nc = nome_curto(a)
    tipo_txt, tipo_pl, tipo_pg = TIPOS[a["tipo"]]
    tipo_min = tipo_pl if a["tipo"] == "bdr" else tipo_pl.lower()
    a12 = janela(a["rows"], 366)
    lo12 = min(r["minima"] for r in a12)
    hi12 = max(r["maxima"] for r in a12)
    aviso_neg = ""
    if not a["negociou_ultimo"]:
        lote = "" if a["tipo"] == "bdr" else " em lote padrão"
        aviso_neg = (f'<div class="aviso"><strong>Sem negócio no último pregão.</strong> {c} não foi negociado{lote} '
                     f'em {data_br(ultimo)}; os números abaixo são do último pregão em que houve negócio, {data_br(u["data"])}.</div>')
    ev_txt = ""
    if u["var"] is None and u["data"] in a["evento"]:
        ev_txt = (f'<div class="aviso"><strong>Evento no papel:</strong> {e(a["evento"][u["data"]]["evento"])} '
                  'A variação do dia não é comparável e não é exibida.</div>')
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
    elif a["tipo"] == "fii":
        guias = [("o-que-e-dividend-yield", "O que é dividend yield"),
                 ("como-funciona-o-imposto-de-renda-na-bolsa", "Imposto de renda em fundos imobiliários")]
    else:
        guias = [("como-funciona-o-imposto-de-renda-na-bolsa", "Como funciona o imposto de renda na bolsa"),
                 ("o-que-e-dividend-yield", "O que é dividend yield")]
    outros = outros_ativos(a, todos)
    cad = a["cad"]
    fontes = [("B3 — Série histórica de cotações (arquivo COTAHIST do pregão)",
               "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/")]
    if cad:
        fontes.append((cad["fonte"], cad["fonte_url"]))
    if a["tipo"] == "acao":
        fontes.append(("CVM — demonstrações financeiras (DFP e ITR) de companhias abertas", "https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp"))
    if a["tipo"] == "bdr":
        fontes.append(("B3 — BDRs listados (nome da empresa e tipo do programa)",
                       "https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/bdrs.htm"))
    fontes.append(("Banco Central — SGS (CDI, série 12; IPCA, série 433)", "https://www3.bcb.gov.br/sgspub/"))
    for i in a["indices"]:
        fontes.append(({"IBOV": "B3 — composição da carteira do Ibovespa", "IFIX": "B3 — composição da carteira do IFIX"}[i],
                       CARTEIRAS[i]["fonte"]))
    razao = cad["razao_social"] if cad else (a["info"]["emissor"] if a["tipo"] == "bdr" else a["papel"]["nome_pregao"])
    pares_html = secao_pares(a, todos, pregoes)
    secoes = [("resumo", "Resumo")] + ([("dividendos", "Dividendos")] if a["tipo"] != "bdr" else []) \
        + [("comparacao", "Comparação")] + ([("pares", "Setor")] if pares_html else []) + [("o-que-e", "Sobre")]
    cab = f"""{migalhas_html(base, ("Ativos", base + "ativos.html"), (tipo_pl, f"{base}{tipo_pg}.html"), (c, ""))}
<div class="cab-ativo">
  <div class="cab-id">
    <span class="icone-tipo" title="{tipo_txt}">{ICONE_TIPO[a["tipo"]]}</span>
    <div>
    <p class="rotulo tipo">{tipo_txt} · B3</p>
    <h1><span class="cod">{c}</span> — {e(nc)}</h1>
    <p class="razao">{e(razao)}</p>
    <p class="acoes-ativo"><button type="button" class="botao claro compartilhar" data-titulo="{e(c)} — {e(nc)}">{ICONE_COMPARTILHAR}<span>Compartilhar</span></button>
    <button type="button" class="botao claro favoritar" data-cod="{c}" aria-pressed="false" hidden>{ICONE_ESTRELA}<span>Favoritar</span></button></p>
    </div>
  </div>
  <div class="preco">
    <div class="valor num"><small>R$</small>{br(u['fechamento'])}</div>
    <div style="margin-top:.5rem">{var_html(u['var'], selo=True)} <span class="quando">no dia</span></div>
    <p class="quando">Fechamento de {data_br(u['data'])}, comparado com {data_br(ant['data'])}</p>
    {selo_dados(ultimo)}
  </div>
</div>
<nav class="ancoras" aria-label="Seções da página">{" · ".join(f'<a href="#{k}">{r}</a>' for k, r in secoes)}</nav>"""
    evs = [(d, x) for d, x in sorted(a["evento"].items(), reverse=True) if d >= a12[0]["data"]]
    ev_hist = ""
    if evs:
        ev_hist = ('<h2 id="eventos">Eventos e variações fora do comum no período</h2><ul class="fontes">'
                   + "".join(f'<li><strong>{data_br(d)}</strong> — {e(x["evento"])}'
                             + (f' Fonte: <a href="{e(x["fonte"])}" rel="noopener nofollow">{e(x["fonte_nome"] or "fonte")}</a>.' if x["fonte"] else "")
                             + "</li>" for d, x in evs) + "</ul>"
                   + '<p class="data-regra">O gráfico “Real” e a tabela mostram o preço como foi negociado, sem ajuste: num desdobramento '
                     'ou grupamento, a linha dá um salto que não é ganho nem perda.</p>')
    quem = "pela companhia" if a["tipo"] != "fii" else "pelo administrador do fundo"
    if a["comunicados"]:
        com_html = ('<h2 id="comunicados">Últimos comunicados</h2>' + lista_comunicados(a["comunicados"])
                    + f'<p class="data-regra">Documentos entregues {quem} à CVM, com link para o arquivo oficial. '
                      'A lista vem dos dados abertos da CVM; veja também <a href="../comunicados.html">os comunicados mais recentes de todos os ativos</a>.</p>')
    elif a["tipo"] == "bdr":
        com_html = ""
    else:
        com_html = ('<h2 id="comunicados">Últimos comunicados</h2><p class="data-regra">Nenhum fato relevante, comunicado ou aviso '
                    'deste papel nos dados abertos da CVM do período coletado.</p>')
    aviso_bdr = ('<div class="aviso"><strong>Preço em reais, do BDR na B3.</strong> Não é a cotação da ação da empresa na bolsa de origem.</div>'
                 if a["tipo"] == "bdr" else "")
    lote = ", em lote padrão," if a["tipo"] == "acao" else ""
    provento = "rendimento" if a["tipo"] == "fii" else "dividendo"
    inicio = a["serie"][0][0]
    corte_txt = (f" A série longa começa em {data_br(inicio)}: antes disso houve variação acima de 25% num pregão sem evento "
                 "declarado nas fontes, e o site não mostra número sem explicação.") if a["corte"] else ""
    aj_txt = (" “Ajustada” desconta os rendimentos do preço anterior a cada pagamento, como se fossem reinvestidos; o rendimento vem do "
              "informe mensal da CVM e é aplicado no primeiro pregão do mês seguinte ao de referência (o informe não traz a data com), "
              "então é uma aproximação.") if a["tipo"] == "fii" else ""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("bovespa-arcos", base, cab, "faixa-ativo")}<div class="casca">
{aviso_neg}{ev_txt}{aviso_bdr}
<section id="resumo" aria-label="Resumo">
{cartoes_indicadores(indicadores(a, pregoes))}
<h2 id="grafico">Histórico de fechamento</h2>
<div class="grafico2" data-slug="{a['slug']}" data-cod="{c}">
<div class="graf-ctl"><div class="botoes per" role="group" aria-label="Período do gráfico"></div>
<div class="botoes aj" role="group" aria-label="Tipo de série" hidden><button type="button" data-aj="0" aria-pressed="true">Real</button><button type="button" data-aj="1" aria-pressed="false">Ajustada</button></div>
<label class="comparar">Comparar com <select><option value="">—</option></select></label></div>
<div class="graf-area"><p class="sem-js">O gráfico é desenhado no navegador e precisa de JavaScript. Os números do período estão logo abaixo e na tabela de pregões.</p></div>
<p class="legenda">Preço de fechamento diário em reais, desde {data_br(inicio)}. “Real” é o preço como foi negociado, sem ajuste por proventos, desdobramentos ou grupamentos.{aj_txt} Ao comparar, as duas séries começam em 100 no início do período. Fonte: B3, série histórica de cotações.{corte_txt}</p>
</div>
<p class="data-regra" style="margin-top:.8rem">Em 12 meses, o preço oscilou entre <span class="num">{brl(lo12)}</span> (mínima intradiária) e <span class="num">{brl(hi12)}</span> (máxima intradiária).</p>
{nums}
</section>
{secao_dividendos(a)}
{secao_comparacao(a)}
{pares_html}
<div class="grade grade-2" style="margin-top:1rem">
<section><h2 id="o-que-e">O que é {c}</h2>{texto_ativo(a)}</section>
<section><h2 id="ficha">Ficha</h2>{ficha_ativo(a)}</section>
</div>
<h2 id="pregoes">Últimos pregões</h2>
{tabela}
{ev_hist}
{com_html}
<h2 id="como-ler">Como ler esta página</h2>
<ul>
 <li><strong>Fechamento</strong> é o preço do último negócio do pregão no mercado à vista{lote} como publicado pela B3.</li>
 <li><strong>Variação do dia</strong> compara esse fechamento com o do pregão anterior em que houve negócio. Não há ajuste por proventos: no dia em que o papel fica “ex” um {provento}, a queda de preço aparece como variação.</li>
 <li><strong>Volume financeiro</strong> é a soma, em reais, de todos os negócios do dia com o papel.</li>
 <li>Cada indicador tem um <strong>?</strong> com a fórmula, a fonte e a data-base. Sem fonte oficial, aparece “—”.</li>
 <li>Os dados chegam <strong>depois do fechamento</strong>, uma vez por dia. Para cotação em tempo real, use o site da B3 ou da sua corretora.</li>
</ul>
<h2 id="guias">Para entender os números</h2>
<ul>{''.join(f'<li><a href="{base}guias/{s}.html">{t}</a></li>' for s, t in guias)}</ul>
<h2 id="outros">{'Outras ações acompanhadas' if a['tipo'] == 'acao' else f'Outros {tipo_min} acompanhados'}</h2>
<ul class="outros-ativos">{''.join(f'<li><a class="cartao" href="{x["slug"]}.html">{selo(x, "p")}<span><b>{x["codigo"]}</b><small>{e(nome_curto(x))}</small></span></a></li>' for x in outros)}</ul>
<p><a href="{base}{tipo_pg}.html">Ver a lista completa de {tipo_min}</a></p>
<h2 id="fontes">Fontes</h2>
<ul class="fontes">{''.join(f'<li><a href="{e(uu)}" rel="noopener">{e(t)}</a></li>' for t, uu in fontes)}
{f'<li>Cadastro da CVM atualizado em {data_br(cad_gerado)}.</li>' if cad else ''}</ul>
<div class="aviso"><strong>{AVISO_FIXO}</strong> Esta página reúne dados públicos sobre {c} e não é análise nem indicação de compra ou venda.</div>
</div></main>
"""
    if a["tipo"] == "fii":
        sobre = {"@type": "InvestmentFund", "name": razao}
    else:
        sobre = {"@type": "Corporation", "name": razao, "tickerSymbol": f"BVMF:{c}"}
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": titulo, "description": desc, "url": url,
           "inLanguage": "pt-BR", "dateModified": u["data"], "about": sobre, "publisher": ORG},
          migalhas_ld((NOME, DOMINIO + "/"), ("Ativos", f"{DOMINIO}/ativos.html"), (tipo_pl, f"{DOMINIO}/{tipo_pg}.html"), (c, url))]
    return (cabeca(titulo, desc, url, og_url, base, ld, extra=fundo_preload("bovespa-arcos", base)) + topo(base, "ativos")
            + corpo + rodape(base, ultimo) + consentimento(base)
            + f'<script src="{base}assets/ativo.js?v={ATIVO_JS_VER}" defer></script>\n' + fim(selo_js()))


def destaques(ativos, ultimo):
    hoje = [a for a in ativos if a["negociou_ultimo"] and a["ult"]["var"] is not None]
    altas = sorted([a for a in hoje if a["ult"]["var"] > 0], key=lambda a: -a["ult"]["var"])[:3]
    baixas = sorted([a for a in hoje if a["ult"]["var"] < 0], key=lambda a: a["ult"]["var"])[:3]
    vol = sorted([a for a in ativos if a["negociou_ultimo"]], key=lambda a: -a["ult"]["volume"])[:3]

    def lista(xs, valor):
        if not xs:
            return '<p class="data-regra">Nenhum ativo da lista nesta condição no pregão.</p>'
        return '<ul class="lista-dest">' + "".join(
            f'<li>{selo(a, "p")}<a href="ativos/{a["slug"]}.html">{a["codigo"]}</a><span class="nome">{e(nome_curto(a))}</span>{valor(a)}</li>'
            for a in xs) + "</ul>"
    return f"""<div class="grade grade-3 destaques">
  <section class="cartao"><h3>{ICONE_ALTA}Maiores altas</h3>{lista(altas, lambda a: var_html(a['ult']['var']))}</section>
  <section class="cartao"><h3>{ICONE_BAIXA}Maiores baixas</h3>{lista(baixas, lambda a: var_html(a['ult']['var']))}</section>
  <section class="cartao"><h3>{ICONE_VOLUME}Mais negociados (volume)</h3>{lista(vol, lambda a: '<span class="num">' + compacto(a['ult']['volume'], True) + '</span>')}</section>
</div>"""


def tabela_ativos(ativos, base, caption, filtro=False):
    """Tabela de ativos. Com filtro=True, leva busca por código/nome e ordenação
    (JS em LISTA_JS); sem JavaScript, a tabela continua inteira, em ordem de código."""
    linhas = []
    for a in ativos:
        u = a["ult"]
        v = u["var"]
        busca = (a["codigo"] + " " + nome_curto(a) + " " + ((a["cad"] or {}).get("razao_social") or (a["info"].get("emissor") or ""))).lower()
        attrs = (f' data-b="{e(busca)}" data-c="{a["codigo"]}" data-f="{u["fechamento"]}" data-v="{"" if v is None else round(v, 4)}"'
                 f' data-vol="{round(u["volume"])}"') if filtro else ""
        linhas.append(f'<tr{attrs}><td><div class="ativo-cel">{selo(a, "p")}<div><a href="{base}ativos/{a["slug"]}.html">{a["codigo"]}</a><br><span class="nome">{e(nome_curto(a))}</span></div></div></td>'
                      f'<td class="n">{br(u["fechamento"])}</td><td class="n">{var_html(v)}</td>'
                      f'<td class="n">{compacto(u["volume"], True)}</td></tr>')
    if filtro:
        cab = ('<th><button type="button" data-ord="c" aria-label="Ordenar por código">Ativo</button></th>'
               '<th class="n"><button type="button" data-ord="f">Fechamento (R$)</button></th>'
               '<th class="n"><button type="button" data-ord="v">Variação</button></th>'
               '<th class="n"><button type="button" data-ord="vol">Volume</button></th>')
    else:
        cab = '<th>Ativo</th><th class="n">Fechamento (R$)</th><th class="n">Variação</th><th class="n">Volume</th>'
    tabela = (f'<div class="rolagem"><table{" class=\"lista-ativos\"" if filtro else ""}><caption>{caption}</caption><thead><tr>{cab}</tr></thead><tbody>'
              + "".join(linhas) + "</tbody></table></div>")
    if not filtro:
        return tabela
    return (f'<div class="filtro" hidden><label for="filtro">Filtrar por código ou nome</label>'
            f'<input id="filtro" type="search" autocomplete="off" spellcheck="false" placeholder="ex.: {ativos[0]["codigo"]}">'
            f'<p class="filtro-conta" aria-live="polite"></p></div>{tabela}')


LISTA_JS = r"""
(function(){var T=document.querySelector('table.lista-ativos');if(!T)return;var B=T.tBodies[0],rows=[].slice.call(B.rows),
F=document.querySelector('.filtro'),I=document.getElementById('filtro'),C=F.querySelector('.filtro-conta'),ord={k:null,d:1};
F.hidden=false;
function sem(s){return s.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase()}
rows.forEach(function(r){r._b=sem(r.getAttribute('data-b'))});
function filtra(){var q=sem(I.value.trim()),n=0;rows.forEach(function(r){var ok=!q||r._b.indexOf(q)>=0;r.hidden=!ok;if(ok)n++});
 C.textContent=q?(n+' de '+rows.length+' ativos'):(rows.length+' ativos')}
I.addEventListener('input',filtra);
var q=new URLSearchParams(location.search).get('q');if(q){I.value=q;}
T.querySelectorAll('th button').forEach(function(bt){bt.addEventListener('click',function(){var k=bt.getAttribute('data-ord');
 ord.d=ord.k===k?-ord.d:(k==='c'?1:-1);ord.k=k;
 rows.sort(function(a,b){var x=a.getAttribute('data-'+k),y=b.getAttribute('data-'+k);
  if(k==='c')return ord.d*x.localeCompare(y);
  if(x==='')return 1;if(y==='')return -1;return ord.d*(parseFloat(x)-parseFloat(y))});
 rows.forEach(function(r){B.appendChild(r)});
 T.querySelectorAll('th').forEach(function(th){th.removeAttribute('aria-sort')});
 bt.parentNode.setAttribute('aria-sort',ord.d>0?'ascending':'descending');});});
filtra();})();"""


def cartoes(itens, base, pasta, rotulo):
    return '<ul class="cartoes grade grade-3">' + "".join(
        f'<li><a class="cartao" href="{base}{pasta}/{g["slug"]}.html"><span class="cartao-topo"><span class="icone-caixa">{ICONES.get(g["slug"], ICONE_PADRAO)}</span>'
        f'<span class="rotulo">{rotulo}</span></span><h3>{e(g["h1"])}</h3><p>{e(g["resumo"])}</p>{SETA}</a></li>'
        for g in itens) + "</ul>"


def sem_recomendacao(txt):
    """Texto de terceiros (manchete, assunto de comunicado) com linguagem que o site não usa fica de fora:
    a trava do build vale para a página inteira e não pode parar a publicação por causa de uma manchete."""
    for m in RECOMENDACAO.finditer(txt):
        if not re.search(r"\bn[ãa]o\b|\bnem\b|\bsem\b", txt[max(0, m.start() - 70):m.start()], re.I):
            return False
    return True


TITULO_HOME = f"{NOME}: cotações da B3, guias e calculadoras"
DESC_HOME = ("Cotações de fechamento da B3 explicadas, com histórico e dados da CVM, comunicados oficiais, guias para "
             "iniciantes e calculadoras. Educativo e com fonte.")


def por_volume(xs, n):
    return sorted(xs, key=lambda a: -a["ult"]["volume"] if a["negociou_ultimo"] else 0)[:n]


def doc_ativos(por_chave, base):
    """Para o comunicado (chave = CNPJ ou cvm:código), os códigos acompanhados daquele emissor, com link."""
    def f(d):
        return " ".join(f'<a href="{base}ativos/{x["slug"]}.html">{x["codigo"]}</a>' for x in por_chave.get(d["k"], []))
    return f


def manchetes(noticias):
    itens = []
    for chave, f in noticias.get("fontes", {}).items():
        for i in f.get("itens", []):
            if sem_recomendacao(i["t"]):
                itens.append({**i, "fonte": f["nome"], "orgao": f["orgao"], "chave": chave})
    itens.sort(key=lambda i: i["d"], reverse=True)
    return itens


def home(ativos, ultimo, guias, calcs, og_url, com, por_chave, noticias, faixa_ind=""):
    base = ""
    busca_dados = json.dumps({a["codigo"]: f"ativos/{a['slug']}.html" for a in ativos}, separators=(",", ":"))
    grupos = {t: [a for a in ativos if a["tipo"] == t] for t in TIPOS}
    chips = por_volume(ativos, 12)
    geral = set(com.get("geral", []))
    docs = sorted([d for d in com["docs"] if d["u"] in geral and d["f"] == "ipe" and sem_recomendacao(d["a"])][:3]
                  + [d for d in com["docs"] if d["u"] in geral and d["f"] == "fii"][:3], key=lambda d: d["d"], reverse=True)
    noti = manchetes(noticias)[:6]
    tabelas = "".join(
        f'<section><h2>{TIPOS[t][1]}</h2>{tabela_ativos(por_volume(grupos[t], 8), base, f"Os 8 de maior volume em {data_br(ultimo)}")}'
        f'<p><a href="{TIPOS[t][2]}.html">Ver {"os" if t == "bdr" else "as" if t == "acao" else "os"} {len(grupos[t])} {TIPOS[t][1] if t == "bdr" else TIPOS[t][1].lower()}</a></p></section>'
        for t in TIPOS)
    corpo = f"""<main id="conteudo" class="com-faixa">
<section class="heroi">{fundo_picture("hero-pregao", base)}{LINHA_FUNDO}
<div class="casca abertura">
  {selo_dados(ultimo)}
  <p class="rotulo">Dados públicos · B3 e CVM</p>
  <h1>O mercado brasileiro, com lupa e com fonte.</h1>
  <p class="lead">Cotação de fechamento, histórico, cadastro oficial e comunicados de {len(ativos)} ações, fundos imobiliários e BDRs, explicados sem palpite. Para quem quer entender antes de decidir qualquer coisa.</p>
  <form class="busca" role="search" id="busca" action="ativos.html">
    <label for="cod" class="sr">Código do ativo</label>
    <input id="cod" name="q" autocomplete="off" spellcheck="false" placeholder="Digite um código, ex.: PETR4" list="codigos" maxlength="8">
    <datalist id="codigos">{''.join(f'<option value="{a["codigo"]}">{e(nome_curto(a))}</option>' for a in ativos)}</datalist>
    <button class="botao" type="submit">Ver</button>
  </form>
  <p class="busca-msg" id="busca-msg" aria-live="polite"></p>
  <ul class="chips" aria-label="Os 12 de maior volume no último pregão">{''.join(f'<li><a href="ativos/{a["slug"]}.html">{a["codigo"]}</a></li>' for a in chips)}</ul>
  {credito_fundo("hero-pregao")}
</div>
</section>
<div class="casca">

<section class="favoritos" id="favoritos" hidden aria-label="Seus favoritos">
<h2>Seus favoritos</h2><p class="data-regra">Guardados só neste navegador. Nada vai para o site.</p><ul class="chips"></ul>
</section>

<section class="painel textura">
<h2 id="pregao">Destaques do pregão de {data_br(ultimo)}</h2>
<p class="data-regra">Entre os {len(ativos)} ativos acompanhados pelo site. É uma fotografia do dia, não um sinal: o que subiu hoje pode cair amanhã.</p>
{destaques(ativos, ultimo)}
</section>

<div class="grade grade-3 tabelas-home" style="margin-top:1.4rem">
{tabelas}
</div>

<div class="grade grade-2">
<section><h2 id="comunicados">Comunicados recentes</h2>{lista_comunicados(docs, doc_ativos(por_chave, base))}<p><a href="comunicados.html">Todos os comunicados recentes</a></p></section>
<section><h2 id="noticias">Notícias de fontes oficiais</h2><ul class="comunicados">{''.join(f'<li><span class="com-meta"><time datetime="{i["d"][:10]}">{data_br(i["d"][:10])}</time> · {e(i["fonte"])}</span><a href="{e(i["u"])}" target="_blank" rel="noopener nofollow">{e(i["t"])}<span class="so-leitor"> (abre em outra aba)</span></a></li>' for i in noti)}</ul><p><a href="noticias.html">Mais notícias</a></p></section>
</div>

{faixa_ind}
{divisor()}
<h2 id="guias">Guias para começar</h2>
{cartoes(guias, base, "guias", "Guia")}
{divisor()}
<h2 id="calculadoras">Calculadoras</h2>
{cartoes(calcs, base, "calculadoras", "Calculadora")}

<div class="aviso"><strong>{AVISO_FIXO}</strong> O {NOME} reúne e explica dados públicos. Não indica ativos, não monta carteira e não diz o que comprar ou vender.</div>
</div></main>
"""
    js = f"""(function(){{var M={busca_dados},f=document.getElementById('busca'),i=document.getElementById('cod'),m=document.getElementById('busca-msg');
f.addEventListener('submit',function(ev){{ev.preventDefault();var c=i.value.trim().toUpperCase().replace(/[^A-Z0-9]/g,'');
if(!c){{m.textContent='Digite um código de negociação, como PETR4, MXRF11 ou AAPL34.';return}}
if(M[c]){{location.href=M[c];return}}
var p=Object.keys(M).filter(function(k){{return k.indexOf(c)===0}});
if(p.length===1){{location.href=M[p[0]];return}}
if(p.length>1){{m.textContent='Mais de um código começa com '+c+': '+p.slice(0,8).join(', ')+'.';return}}
m.textContent=c+' não está na lista acompanhada pelo site. Veja as listas de ações, fundos imobiliários e BDRs.';}});
var F=[];try{{F=JSON.parse(localStorage.getItem('ml-favoritos')||'[]')}}catch(e){{}}
var S=document.getElementById('favoritos');if(S&&F.length){{var u=S.querySelector('ul');F.forEach(function(c){{if(M[c]){{var li=document.createElement('li'),a=document.createElement('a');a.href=M[c];a.textContent=c;li.appendChild(a);u.appendChild(li)}}}});if(u.children.length)S.hidden=false}}}})();"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": NOME, "url": DOMINIO + "/", "inLanguage": "pt-BR",
           "description": DESC_HOME, "publisher": ORG}, {"@context": "https://schema.org", **ORG}]
    return cabeca(TITULO_HOME, DESC_HOME, DOMINIO + "/", og_url, base, ld, extra=fundo_preload("hero-pregao", base)) + topo(base) + corpo + rodape(base, ultimo) + consentimento(base) + fim(js + selo_js())


TITULO_ATIVOS = f"Ativos acompanhados: ações, FIIs e BDRs · {NOME}"
DESC_ATIVOS = ("As ações do Ibovespa, os fundos imobiliários do IFIX e os BDRs mais negociados na B3, com fechamento, "
               "variação e histórico de cada um. Critérios públicos.")
LISTAS = {
    "acao": (f"Ações do Ibovespa e mais negociadas · {NOME}",
             "Cotação de fechamento das ações da carteira do Ibovespa e das mais negociadas da B3, com variação, volume, "
             "busca por código e histórico de cada papel."),
    "fii": (f"Fundos imobiliários do IFIX: cotações · {NOME}",
            "Cotação de fechamento dos fundos imobiliários da carteira do IFIX na B3, com variação, volume, busca por "
            "código e o cadastro de cada fundo na CVM."),
    "bdr": (f"BDRs mais negociados na B3: cotações · {NOME}",
            "Cotação em reais dos 50 BDRs mais negociados na B3 no ano, com variação, volume, busca e o que é um BDR. O preço é o do BDR, não o da ação lá fora."),
}


def criterio(t):
    c = CARTEIRAS
    if t == "acao":
        return (f'Todas as {len(c["IBOV"]["codigos"])} ações da <a href="{e(c["IBOV"]["fonte"])}" rel="noopener">carteira do Ibovespa</a> '
                f'vigente em {data_br(c["IBOV"]["data"])}, segundo a B3, mais {len(c["acoes_extras"]["codigos"])} ações e units fora do índice: '
                f'{e(c["acoes_extras"]["criterio"])}.')
    if t == "fii":
        return (f'Os {len(c["IFIX"]["codigos"])} fundos da <a href="{e(c["IFIX"]["fonte"])}" rel="noopener">carteira do IFIX</a> '
                f'vigente em {data_br(c["IFIX"]["data"])}, segundo a B3.')
    return f'{e(c["BDR"]["criterio"][:1].upper() + c["BDR"]["criterio"][1:])}.'


def pagina_ativos(ativos, ultimo, og_url):
    base = ""
    grupos = {t: [a for a in ativos if a["tipo"] == t] for t in TIPOS}
    cab = f"""{migalhas_html(base, ("Ativos", ""))}
<h1>Ativos acompanhados</h1>
<p class="lead">{len(ativos)} papéis negociados na B3, escolhidos por critério público e mecânico — carteira dos índices da própria B3 e volume negociado —, nunca por juízo sobre eles. A lista não é seleção nem recomendação.</p>
"""
    blocos = "".join(f"""<section class="cartao bloco-tipo"><h2>{TIPOS[t][1]} <small class="num">{len(grupos[t])}</small></h2>
<p>{criterio(t)}</p>
<p><a class="botao" href="{TIPOS[t][2]}.html">Ver {TIPOS[t][1] if t == "bdr" else TIPOS[t][1].lower()}</a></p></section>""" for t in TIPOS)
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("bovespa-arcos", base, cab)}<div class="casca">
<div class="grade grade-3">{blocos}</div>
<h2>Mais negociados no último pregão</h2>
{tabela_ativos(por_volume(ativos, 15), base, f"Os 15 de maior volume em {data_br(ultimo)}, entre todos os tipos")}
<p class="data-regra">A carteira dos índices muda a cada quatro meses (janeiro, maio e setembro), e a lista do site é revista quando isso acontece.</p>
<div class="aviso"><strong>{AVISO_FIXO}</strong></div>
</div></main>
"""
    u = f"{DOMINIO}/ativos.html"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": TITULO_ATIVOS, "description": DESC_ATIVOS,
           "url": u, "inLanguage": "pt-BR"}, migalhas_ld((NOME, DOMINIO + "/"), ("Ativos", u))]
    return cabeca(TITULO_ATIVOS, DESC_ATIVOS, u, og_url, base, ld, extra=fundo_preload("bovespa-arcos", base)) + topo(base, "ativos") + corpo + rodape(base, ultimo) + consentimento(base) + fim(selo_js())


def pagina_lista(t, ativos, ultimo, og_url):
    base = ""
    nome, plural, pg = TIPOS[t]
    titulo, desc = LISTAS[t]
    xs = sorted([a for a in ativos if a["tipo"] == t], key=lambda a: a["codigo"])
    intro = {"acao": "Ações e units negociadas no mercado à vista da B3, com o fechamento do último pregão.",
             "fii": "Cotas de fundos de investimento imobiliário negociadas na B3, com o fechamento do último pregão.",
             "bdr": ("Certificados negociados na B3, em reais, que representam ações de empresas estrangeiras. "
                     "O preço é o do BDR aqui, não o da ação na bolsa de origem.")}[t]
    cab = f"""{migalhas_html(base, ("Ativos", "ativos.html"), (plural, ""))}
<h1>{plural}</h1>
<p class="lead">{intro}</p>
{selo_dados(ultimo)}
"""
    extra_bdr = (f"<h2 id='o-que-e-bdr'>O que é um BDR</h2>{TEXTO_BDR}<p>Os BDRs desta lista são <strong>não patrocinados</strong> "
                 "(abertos por uma instituição depositária, sem participação da empresa) ou <strong>patrocinados</strong> "
                 "(contratados pela própria empresa, que então se registra na CVM). A página de cada um diz qual é o caso, "
                 "conforme o cadastro da B3. BDRs de ETF ficam fora desta lista.</p>") if t == "bdr" else ""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("bovespa-arcos", base, cab)}<div class="casca">
<p class="data-regra"><strong>Quais estão aqui:</strong> {criterio(t)}</p>
{tabela_ativos(xs, base, f"{len(xs)} {plural if t == 'bdr' else plural.lower()} · fechamento em {data_br(ultimo)}", filtro=True)}
<p class="data-regra">Toque no título de uma coluna para ordenar. Variação sem número (—) é dia de evento como desdobramento ou grupamento, em que a comparação não vale.</p>
{extra_bdr}
<div class="aviso"><strong>{AVISO_FIXO}</strong> Estar nesta lista não é indicação de compra ou venda.</div>
</div></main>
"""
    u = f"{DOMINIO}/{pg}.html"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "description": desc, "url": u,
           "inLanguage": "pt-BR", "numberOfItems": len(xs)},
          migalhas_ld((NOME, DOMINIO + "/"), ("Ativos", f"{DOMINIO}/ativos.html"), (plural, u))]
    return (cabeca(titulo, desc, u, og_url, base, ld, extra=fundo_preload("bovespa-arcos", base)) + topo(base, "ativos")
            + corpo + rodape(base, ultimo) + consentimento(base) + fim(LISTA_JS + selo_js()))


TITULO_COM = f"Comunicados de empresas e fundos na CVM · {NOME}"
DESC_COM = ("Fatos relevantes, comunicados ao mercado e avisos das empresas e fundos imobiliários acompanhados, com data "
            "e link para o documento oficial na CVM.")


def fonte_ok_txt(f):
    if not f:
        return "ainda não coletada"
    if f.get("ok"):
        return f"coletada em {data_hora_br(f['coletado_em'])}"
    return f"última coleta falhou em {data_hora_br(f['falhou_em'])}; mostrando a coleta anterior"


def data_hora_br(s):
    if not s:
        return "—"
    d = dt.datetime.fromisoformat(s).astimezone(BRASILIA)
    return d.strftime("%d/%m/%Y %H:%M")


def pagina_comunicados(com, por_chave, og_url, ultimo):
    base = ""
    geral = set(com.get("geral", []))
    docs = [d for d in com["docs"] if d["u"] in geral and sem_recomendacao(d["a"])]
    d_emp = [d for d in docs if d["f"] == "ipe"]
    d_fii = [d for d in docs if d["f"] == "fii"]
    fi, fp = com["fontes"].get("ipe"), com["fontes"].get("fii")
    cab = f"""{migalhas_html(base, ("Comunicados", ""))}
<h1>Comunicados recentes</h1>
<p class="lead">Os documentos oficiais mais recentes das empresas e fundos acompanhados: fatos relevantes, comunicados ao mercado, avisos aos acionistas e, dos fundos imobiliários, avisos e relatórios gerenciais.</p>
"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("paulista-dia", base, cab)}<div class="casca texto">
<h2 id="empresas">Empresas</h2>
{lista_comunicados(d_emp, doc_ativos(por_chave, base))}
<h2 id="fundos">Fundos imobiliários</h2>
{lista_comunicados(d_fii, doc_ativos(por_chave, base))}
<h2 id="de-onde">De onde vem esta lista</h2>
<ul>
 <li><strong>Companhias abertas:</strong> documentos IPE dos <a href="https://dados.cvm.gov.br/dataset/cia_aberta-doc-ipe" rel="noopener">dados abertos da CVM</a>. O link leva ao documento no sistema da CVM. {e(fonte_ok_txt(fi))}{f"; arquivo da CVM atualizado em {data_hora_br(fi['arquivo_cvm_em'])}, com documentos até {data_br(fi['ultimo_documento'])}" if fi and fi.get('arquivo_cvm_em') else ""}. A CVM atualiza esse arquivo em lotes, então um comunicado pode levar alguns dias para aparecer aqui.</li>
 <li><strong>Fundos imobiliários:</strong> documentos eventuais de fundos dos <a href="https://dados.cvm.gov.br/dataset/fi-doc-eventual" rel="noopener">dados abertos da CVM</a>, com link para o arquivo no Fundos.NET, da B3. Esse conjunto não traz o assunto do documento, só o tipo. {e(fonte_ok_txt(fp))}.</li>
</ul>
<p class="data-regra">O resumo de cada comunicado é o assunto informado pela própria empresa à CVM, sem edição. O site não comenta nem interpreta os documentos.</p>
<div class="aviso"><strong>{AVISO_FIXO}</strong></div>
</div></main>
"""
    u = f"{DOMINIO}/comunicados.html"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": TITULO_COM, "description": DESC_COM, "url": u,
           "inLanguage": "pt-BR"}, migalhas_ld((NOME, DOMINIO + "/"), ("Comunicados", u))]
    return (cabeca(TITULO_COM, DESC_COM, u, og_url, base, ld, extra=fundo_preload("paulista-dia", base)) + topo(base, "comunicados")
            + corpo + rodape(base, ultimo) + consentimento(base) + fim())


TITULO_NOT = f"Notícias de economia de fontes oficiais · {NOME}"
DESC_NOT = ("Manchetes recentes do Banco Central, do Tesouro Nacional, da B3 e da Agência Brasil, com link para o texto "
            "original na fonte. Sem veículos privados.")


def pagina_noticias(noticias, og_url, ultimo):
    base = ""
    secoes = []
    for chave, f in noticias.get("fontes", {}).items():
        itens = [i for i in f.get("itens", []) if sem_recomendacao(i["t"])]
        estado = "" if f.get("ok") else f'<p class="aviso">A última coleta desta fonte falhou; abaixo, a anterior ({e(data_hora_br(f.get("coletado_em")))}).</p>'
        lista = "".join(f'<li><span class="com-meta"><time datetime="{i["d"][:10]}">{data_br(i["d"][:10])}</time></span>'
                        f'<a href="{e(i["u"])}" target="_blank" rel="noopener nofollow">{e(i["t"])}<span class="so-leitor"> (abre em outra aba)</span></a></li>' for i in itens)
        secoes.append(f'<section><h2 id="{chave}">{e(f["nome"])}</h2>{estado}<ul class="comunicados">{lista or "<li>Nenhum item.</li>"}</ul>'
                      f'<p class="data-regra">Crédito: {e(f["orgao"])} — <a href="{e(f["site"])}" rel="noopener">{e(f["site"].split("//")[1].rstrip("/"))}</a>. '
                      f'Título e link, como publicados pela fonte; o texto está lá.</p></section>')
    cab = f"""{migalhas_html(base, ("Notícias", ""))}
<h1>Notícias de fontes oficiais</h1>
<p class="lead">Manchetes do Banco Central, do Tesouro Nacional, da B3 e da Agência Brasil, a agência pública de notícias. Cada título leva ao texto na fonte original.</p>
"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("paulista-noite", base, cab)}<div class="casca">
<div class="grade grade-2">{''.join(secoes)}</div>
<h2 id="criterio">Por que só estas fontes</h2>
<p>O site reúne manchetes de órgãos públicos e da própria bolsa, que publicam a informação na origem — decisão do Copom, nota do Tesouro, comunicado da B3 —, e da Agência Brasil, da empresa pública de comunicação. Veículos privados ficam de fora. Só o título, a data e o link são reproduzidos: o texto é de cada fonte, e ler a notícia é no site dela.</p>
<div class="aviso"><strong>{AVISO_FIXO}</strong> Notícia não é recomendação, nem a seleção destas manchetes é.</div>
</div></main>
"""
    u = f"{DOMINIO}/noticias.html"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": TITULO_NOT, "description": DESC_NOT, "url": u,
           "inLanguage": "pt-BR"}, migalhas_ld((NOME, DOMINIO + "/"), ("Notícias", u))]
    return (cabeca(TITULO_NOT, DESC_NOT, u, og_url, base, ld, extra=fundo_preload("paulista-noite", base)) + topo(base, "noticias")
            + corpo + rodape(base, ultimo) + consentimento(base) + fim())


def pagina_conteudo(g, pasta, rotulo_pasta, og_url, artigo):
    base = "../"
    url = f"{DOMINIO}/{pasta}/{g['slug']}.html"
    fontes = ""
    if g["fontes"]:
        fontes = ('<h2 id="fontes">Fontes</h2><ul class="fontes">'
                  + "".join(f'<li><a href="{e(f["url"])}" rel="noopener">{e(f["nome"])}</a></li>' for f in g["fontes"]) + "</ul>")
    datas = f'Publicado em {data_longa(g["publicado"])}' + (f' · atualizado em {data_longa(g["atualizado"])}' if g["atualizado"] != g["publicado"] else "")
    largura = "texto" if artigo else ""
    foto = "viva-voz" if artigo else "paulista-noite"
    cab = f"""{migalhas_html(base, (rotulo_pasta, base + pasta + ".html"), (g['h1'], ""))}
<div class="cab-conteudo"><span class="icone-caixa">{ICONES.get(g["slug"], ICONE_PADRAO)}</span><div>
<p class="rotulo">{'Guia' if artigo else 'Calculadora'} · {datas}</p>
<h1>{e(g['h1'])}</h1>
</div></div>"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa(foto, base, cab)}<div class="casca">
<article class="{largura}">
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
    return cabeca(g["titulo"], g["descricao"], url, og_url, base, ld, tipo="article" if artigo else "website",
                  extra=fundo_preload(foto, base)) \
        + topo(base, pasta) + corpo + rodape(base) + consentimento(base) + fim(js)


def pagina_hub(itens, pasta, titulo, desc, h1, lead, rotulo, og_url):
    base = ""
    u = f"{DOMINIO}/{pasta}.html"
    foto = "viva-voz" if pasta == "guias" else "paulista-noite"
    cab = f"""{migalhas_html(base, (h1, ""))}
<h1>{e(h1)}</h1>
<p class="lead">{lead}</p>
"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa(foto, base, cab)}<div class="casca">
<div>{cartoes(itens, base, pasta, rotulo)}</div>
<div class="aviso"><strong>{AVISO_FIXO}</strong></div>
</div></main>
"""
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "description": desc, "url": u, "inLanguage": "pt-BR"},
          migalhas_ld((NOME, DOMINIO + "/"), (h1, u))]
    return cabeca(titulo, desc, u, og_url, base, ld, extra=fundo_preload(foto, base)) + topo(base, pasta) + corpo + rodape(base) + consentimento(base) + fim()


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
DESC_GUIAS = ("Guias com fonte para entender a bolsa e declarar investimentos no IR: ações, FIIs, BDRs, ETFs, renda fixa, "
              "DARF e prejuízo, com as regras de 2026.")
TITULO_CALCS = f"Calculadoras financeiras · {NOME}"
DESC_CALCS = ("Simulador de renda fixa com IR e IOF, calculadora de DARF de ações, juros compostos, reserva de emergência "
              "e primeiro milhão. Fórmulas explicadas.")


def pagina_sobre(og_url):
    base = ""
    cab = f"""{migalhas_html(base, ("Sobre", ""))}
<h1>Sobre o {NOME}</h1>
<p class="lead">Um site de dados públicos sobre o mercado brasileiro, feito para quem está começando e quer entender o que os números querem dizer.</p>
"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("paulista-dia", base, cab)}<div class="casca texto">

<h2>O que é</h2>
<p>O <strong>{NOME}</strong> é um projeto editorial independente, feito no Brasil. Reúne a cotação de fechamento de ações, fundos imobiliários e BDRs negociados na B3, o histórico de preços, o cadastro oficial e os comunicados de cada empresa ou fundo na CVM, e explica conceitos básicos em guias curtos e calculadoras.</p>

<h2>De onde vêm os dados</h2>
<ul>
 <li><strong>Cotações:</strong> série histórica de cotações da B3 (arquivo COTAHIST), publicada pela própria bolsa depois de cada pregão, lida segundo o layout oficial do arquivo. O site é atualizado uma vez por dia útil, à noite. Os dados têm atraso e não servem para negociar.</li>
 <li><strong>Cadastro:</strong> dados abertos da CVM — o cadastro de companhias abertas e o informe mensal dos fundos imobiliários. Para os BDRs, o nome da empresa estrangeira e o tipo do programa vêm do cadastro de BDRs da B3.</li>
 <li><strong>Lista de ativos:</strong> as carteiras do Ibovespa e do IFIX publicadas pela B3, as ações e units mais negociadas fora do índice e os 50 BDRs mais negociados no ano, pelo próprio arquivo da B3. Os critérios estão na página <a href="ativos.html">Ativos</a>.</li>
 <li><strong>Comunicados:</strong> fatos relevantes, comunicados e avisos entregues à CVM, dos dados abertos da CVM, sempre com link para o documento oficial.</li>
 <li><strong>Notícias:</strong> só título, data e link de manchetes do Banco Central, do Tesouro Nacional, da B3 e da Agência Brasil. O texto fica na fonte.</li>
 <li><strong>Indicadores:</strong> dados abertos do Banco Central — Selic, CDI, IPCA (calculado pelo IBGE), poupança, TR (SGS) e PTAX (API Olinda) —, com a data de referência de cada número. A conta da poupança é refeita pela regra da lei a cada atualização, e o IPCA em 12 meses é conferido contra os doze índices mensais.</li>
 <li><strong>Tesouro Direto:</strong> taxas e preços dos títulos do conjunto de dados abertos “Taxas dos Títulos Ofertados pelo Tesouro Direto”, do Tesouro Transparente (licença ODbL).</li>
 <li><strong>Regras de imposto e conceitos:</strong> o texto das leis no portal do Planalto, publicações da Receita Federal, da CVM, do Banco Central e da B3, sempre listados ao fim de cada guia.</li>
</ul>

<h2>Como os números são conferidos</h2>
<p>O programa que lê o arquivo da B3 confere o arquivo inteiro antes de gravar qualquer número: tamanho de cada registro, cabeçalho, contagem do rodapé, moeda, faixa de preço do dia e coerência entre quantidade, preço médio e volume. Se algo não bater — inclusive uma mudança de layout pela B3 —, a atualização para e nada é publicado. Uma variação diária acima de 25% também trava a publicação até que alguém confira se houve desdobramento, grupamento ou erro. Página desatualizada é melhor que número errado.</p>

<h2>O que este site não faz</h2>
<p>Não recomenda ativos, não monta carteira, não dá preço-alvo nem nota, e não diz o que comprar ou vender. O site não é casa de análise, consultoria ou intermediário, e seu conteúdo não é relatório de análise de valores mobiliários nos termos da regulamentação da CVM. A lista de ativos acompanhados segue critérios mecânicos — a carteira dos índices da B3 e o volume negociado —, e não qualquer juízo sobre os papéis.</p>

<h2>Correções</h2>
<p>Viu um número ou uma regra errada? Escreva pela página de <a href="contato.html">contato</a>, de preferência com a fonte. O erro confirmado é corrigido, e a data de atualização da página muda.</p>

<h2>Quem faz</h2>
<p>O {NOME} é mantido de forma independente, sem vínculo com corretora, banco, gestora, empresa listada ou órgão público. É da mesma casa do <a href="https://guiaprodutonalupa.com.br" rel="noopener">Guia Produto na Lupa</a> e do <a href="https://viagemnalupa.com.br" rel="noopener">Viagem na Lupa</a>. O site se mantém com anúncios do Google AdSense, descritos na <a href="privacidade.html">política de privacidade</a>; nenhum anunciante interfere no conteúdo.</p>
</div></main>
"""
    u = DOMINIO + "/sobre.html"
    return (cabeca(TITULO_SOBRE, DESC_SOBRE, u, og_url, base, extra=fundo_preload("paulista-dia", base), jsonld=
                   [{"@context": "https://schema.org", "@type": "AboutPage", "name": TITULO_SOBRE, "description": DESC_SOBRE, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Sobre", u))])
            + topo(base, "sobre") + corpo + rodape(base) + consentimento(base) + fim())


def pagina_contato(og_url):
    base = ""
    cab = f"""{migalhas_html(base, ("Contato", ""))}
<h1>Fale com o {NOME}</h1>
<p class="lead">Correção, sugestão ou pedido sobre seus dados: o caminho é um só.</p>
"""
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("paulista-dia", base, cab)}<div class="casca texto">
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
    return (cabeca(TITULO_CONTATO, DESC_CONTATO, u, og_url, base, extra=fundo_preload("paulista-dia", base), jsonld=
                   [{"@context": "https://schema.org", "@type": "ContactPage", "name": TITULO_CONTATO, "description": DESC_CONTATO, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Contato", u))])
            + topo(base, "contato") + corpo + rodape(base) + consentimento(base) + fim())


PRIVACIDADE_CAB = """{{MIGALHAS}}
<p class="rotulo">Documento · atualizado em {{DATA}}</p>
<h1>Política de privacidade</h1>
<p class="lead">O que o {{NOME}} coleta, o que não coleta, quem mais está envolvido e o que você pode exigir.</p>
"""

PRIVACIDADE = """<main id="conteudo" class="com-faixa">
{{FAIXA}}<div class="casca texto">

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
<p>Um único serviço externo participa da exibição destas páginas: o Google AdSense. Se você recusar na faixa, o script de anúncios é retirado e deixa de ser carregado. Fontes tipográficas, gráficos e imagens vêm deste mesmo domínio, com uma exceção: a página técnica <a href="status.html">Status dos dados</a> mostra uma pequena imagem do GitHub com a situação da rotina de atualização, e ao abri-la seu navegador pede essa imagem ao GitHub, sem informar de qual página veio. Os links para a B3, a CVM, o Planalto e a Receita Federal só levam você a esses sites se você clicar.</p>

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
    cab = (PRIVACIDADE_CAB.replace("{{NOME}}", NOME).replace("{{DATA}}", "3 de outubro de 2026")
           .replace("{{MIGALHAS}}", migalhas_html(base, ("Privacidade", ""))))
    corpo = (PRIVACIDADE.replace("{{FAIXA}}", faixa("paulista-dia", base, cab)).replace("{{NOME}}", NOME).replace("{{EMAIL}}", EMAIL).replace("{{CHAVE}}", CHAVE_CONSENTIMENTO)
             .replace("{{DATA}}", "3 de outubro de 2026").replace("{{MIGALHAS}}", migalhas_html(base, ("Privacidade", ""))))
    u = DOMINIO + "/privacidade.html"
    return (cabeca(TITULO_PRIV, DESC_PRIV, u, og_url, base, extra=fundo_preload("paulista-dia", base), jsonld=
                   [{"@context": "https://schema.org", "@type": "WebPage", "name": TITULO_PRIV, "description": DESC_PRIV, "url": u, "inLanguage": "pt-BR"},
                    migalhas_ld((NOME, DOMINIO + "/"), ("Política de privacidade", u))])
            + topo(base) + corpo + rodape(base) + consentimento(base) + fim())


TITULO_STATUS = f"Status dos dados · {NOME}"
DESC_STATUS = (f"Quando o {NOME} foi gerado, qual o último pregão da B3 lido, a situação de cada ativo e a rotina "
               "diária que atualiza as cotações.")
ACTIONS_URL = "https://github.com/allangipa/Mercado-na-Lupa/actions/workflows/atualiza.yml"
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def pagina_status(ativos, pregoes, ultimo, gerado, og_url, com, noticias, extra_html=""):
    """Página técnica para o dono conferir se as cotações estão em dia. noindex, fora do sitemap."""
    base = ""
    br_t = gerado.astimezone(BRASILIA)
    cab = f"""{migalhas_html(base, ("Status dos dados", ""))}
<h1>Status dos dados</h1>
<p class="lead">Se as cotações estão em dia, quando o site foi gerado pela última vez e como anda a rotina que busca os pregões na B3.</p>
{selo_dados(ultimo, "selo-g")}
"""
    linhas = []
    for a in ativos:
        d = a["ult"]["data"]
        atras = d != ultimo
        cl_tr = ' class="atrasado"' if atras else ""
        marca = (f' <span class="marca-atraso">atrás do último pregão lido ({data_br(ultimo)})</span>' if atras else "")
        linhas.append(f'<tr{cl_tr}><td><a href="{base}ativos/{a["slug"]}.html">{a["codigo"]}</a></td>'
                      f'<td class="n">{data_br(d)}</td><td class="n">{br(a["ult"]["fechamento"])}</td>'
                      f'<td>{selo_dados(d, "selo-mini")}{marca}</td></tr>')
    n_atras = sum(1 for a in ativos if a["ult"]["data"] != ultimo)
    resumo_atras = ("Todos os ativos tiveram negócio no último pregão lido." if not n_atras else
                    f"{n_atras} ativo(s) sem negócio no último pregão lido — destacado(s) na tabela.")
    linhas_fontes = []
    for chave, f in list(com.get("fontes", {}).items()) + list(noticias.get("fontes", {}).items()):
        ok = f.get("ok")
        estado = ('<span class="selo-dados selo-mini" data-estado="ok"><span class="selo-ponto" aria-hidden="true">✓</span><span class="selo-txt">OK</span></span>'
                  if ok else '<span class="selo-dados selo-mini" data-estado="atraso"><span class="selo-ponto" aria-hidden="true">×</span><span class="selo-txt">Falhou</span></span>')
        if "itens" in f:
            recente = data_br(f["itens"][0]["d"][:10]) if f.get("itens") else "—"
            tipo_f = "Notícias"
        else:
            recente = data_br(f["ultimo_documento"]) if f.get("ultimo_documento") else "—"
            tipo_f = "Comunicados"
        erro = f'<br><span class="nome">{e(f.get("erro", ""))} (em {e(data_hora_br(f.get("falhou_em")))})</span>' if not ok else ""
        extra = f'<br><span class="nome">arquivo da CVM de {e(data_hora_br(f["arquivo_cvm_em"]))}</span>' if f.get("arquivo_cvm_em") else ""
        linhas_fontes.append(f'<tr{"" if ok else " class=\"atrasado\""}><td>{tipo_f}</td><td style="white-space:normal">{e(f["nome"])}{erro}</td>'
                             f'<td class="n">{e(data_hora_br(f.get("coletado_em")))}{extra}</td><td class="n">{recente}</td><td>{estado}</td></tr>')
    fb = FUND.get("fontes", {})
    bal = fb.get("cvm_balancos", {})
    datas_bal = ", ".join(f"{data_br(d)} ({n} companhias)" for d, n in bal.get("datas_base", {}).items()) or "—"
    fii_mes = fb.get("cvm_fii", {}).get("ultimo_mes")
    fund_html = (f'<h2 id="balancos">Balanços e informes (indicadores)</h2><dl class="ficha">'
                 f'<dt>Data-base dos balanços (ITR/DFP)</dt><dd class="num">{datas_bal}</dd>'
                 f'<dt>Exercícios anuais lidos (DFP)</dt><dd class="num">{", ".join(str(x) for x in bal.get("anos_dfp", [])) or "—"}</dd>'
                 f'<dt>Último informe mensal de FII</dt><dd class="num">{mes_curto(fii_mes) if fii_mes else "—"}</dd>'
                 f'<dt>Coleta dos balanços</dt><dd class="num">{e(data_hora_br(FUND.get("gerado_em")))}</dd></dl>'
                 '<p class="data-regra">P/L, P/VP, DY, ROE, margem e payout usam esses dados abertos da CVM; a rotina relê os balanços uma vez por semana.</p>')
    prox = proximos_uteis(ultimo, 5)
    prox_html = "".join(f'<li data-dia="{d.isoformat()}"><span class="num">{DIAS_SEMANA[d.weekday()]} {data_br(d)}</span>'
                        f'<span class="prox-estado"></span></li>' for d in prox)
    fer_prox = [(d, n) for d, n in sorted(FERIADOS.items()) if d > ultimo][:4]
    fer_html = "".join(f'<li><span class="num">{DIAS_SEMANA[dt.date.fromisoformat(d).weekday()]} {data_br(d)}</span> — {e(n)}'
                       + (" <em>(provisório)</em>" if FERIADOS_INFO[d[:4]].get("provisorio") else "") + "</li>" for d, n in fer_prox)
    fontes_fer = "".join(f'<li>{ano}: <a href="{e(i["fonte_url"])}" rel="noopener">{e(i["fonte"])}</a></li>'
                         for ano, i in FERIADOS_INFO.items())
    corpo = f"""<main id="conteudo" class="com-faixa">
{faixa("paulista-dia", base, cab)}<div class="casca">

<h2 id="cores">O que cada cor quer dizer</h2>
<ul class="legenda-selo">
 <li><span class="selo-dados selo-mini" data-estado="ok"><span class="selo-ponto" aria-hidden="true">✓</span><span class="selo-txt">Atualizado</span></span> o último pregão lido é o último dia útil já encerrado na B3 (depois das 19h de Brasília, o pregão do dia conta).</li>
 <li><span class="selo-dados selo-mini" data-estado="aviso"><span class="selo-ponto" aria-hidden="true">!</span><span class="selo-txt">Pode estar desatualizado</span></span> falta 1 pregão — normal à noite, enquanto a B3 não publica o arquivo do dia.</li>
 <li><span class="selo-dados selo-mini" data-estado="atraso"><span class="selo-ponto" aria-hidden="true">×</span><span class="selo-txt">Desatualizado</span></span> faltam 2 pregões ou mais: a rotina falhou ou parou numa trava. Veja o selo do GitHub abaixo.</li>
</ul>
<p class="data-regra" id="calculo">A conta é feita no seu navegador, com a data e a hora de Brasília, pulando fins de semana e feriados da B3.</p>

<div class="grade grade-2">
<section>
<h2 id="geracao">Última geração do site</h2>
<dl class="ficha">
 <dt>Gerado em (Brasília)</dt><dd class="num">{br_t.strftime("%d/%m/%Y %H:%M")}</dd>
 <dt>Gerado em (UTC)</dt><dd class="num">{gerado.strftime("%d/%m/%Y %H:%M")} UTC</dd>
 <dt>Último pregão lido</dt><dd class="num">{data_br(ultimo)} ({DIAS_SEMANA[dt.date.fromisoformat(ultimo).weekday()]})</dd>
 <dt>Pregões gravados</dt><dd class="num">{len(pregoes)}, de {data_br(pregoes[0])} a {data_br(ultimo)}</dd>
</dl>
</section>
<section>
<h2 id="rotina">Rotina diária</h2>
<p><a class="selo-actions" href="{ACTIONS_URL}" rel="noopener"><img src="{ACTIONS_URL}/badge.svg" alt="Situação da rotina Atualiza cotações no GitHub Actions" height="20" loading="lazy" referrerpolicy="no-referrer"></a></p>
<p class="data-regra">A rotina roda no GitHub Actions às 19h30 e à 1h30 (Brasília), de segunda a sexta: baixa o arquivo da B3, gera o site e publica. “passing” é a última execução sem erro; “failing” quer dizer que ela parou — nada errado é publicado, e o site fica como estava. <a href="{ACTIONS_URL}" rel="noopener">Ver as execuções</a>.</p>
</section>
</div>

<h2 id="fontes-extras">Comunicados e notícias</h2>
<p class="data-regra">Coletados pela mesma rotina, depois das cotações. Uma fonte que falha não para o resto: o site mantém a última coleta boa dela e a marca aqui.</p>
<div class="rolagem"><table class="tabela-status"><caption>Última coleta de cada fonte (horário de Brasília)</caption><thead><tr><th>Tipo</th><th>Fonte</th><th class="n">Última coleta boa</th><th class="n">Item mais recente</th><th>Situação</th></tr></thead><tbody>
{"".join(linhas_fontes)}
</tbody></table></div>

{fund_html}

{extra_html}
<h2 id="ativos">Ativos</h2>
<p class="data-regra">{resumo_atras}</p>
<div class="rolagem"><table class="tabela-status"><caption>Último pregão com negócio de cada ativo</caption><thead><tr><th>Código</th><th class="n">Último pregão</th><th class="n">Fechamento (R$)</th><th>Situação</th></tr></thead><tbody>
{"".join(linhas)}
</tbody></table></div>

<div class="grade grade-2" style="margin-top:.6rem">
<section>
<h2 id="proximos">Próximos pregões esperados</h2>
<p class="data-regra">Dias úteis depois de {data_br(ultimo)}. O arquivo de cada pregão costuma sair no começo da noite.</p>
<ul class="lista-prox">{prox_html}</ul>
</section>
<section>
<h2 id="feriados">Próximos feriados sem pregão</h2>
<ul class="lista-prox">{fer_html}</ul>
<p class="data-regra">Fontes da lista de feriados:</p>
<ul class="fontes">{fontes_fer}</ul>
</section>
</div>
</div></main>
"""
    js = selo_js(teste=True) + r"""
(function(){var S=window.MLselo;if(!S)return;
function br(s){return s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(0,4)}
var a=S.agora,h=('0'+a.getUTCHours()).slice(-2)+':'+('0'+a.getUTCMinutes()).slice(-2),p=document.querySelector('.selo-g').getAttribute('data-pregao'),r=S.estado(p);
document.getElementById('calculo').textContent='Agora em Brasília: '+br(a.toISOString())+' '+h+' · último pregão que já devia estar aqui: '+br(S.esperado)+' · pregões faltando: '+r.f+'. A conta pula fins de semana e feriados da B3.'+(/[?&]hoje=/.test(location.search)?' (data simulada pelo parâmetro hoje)':'');
document.querySelectorAll('.lista-prox li[data-dia]').forEach(function(li){if(li.getAttribute('data-dia')<=S.esperado){li.className='devido';li.querySelector('.prox-estado').textContent=' — já devia ter chegado'}});
})();"""
    u = DOMINIO + "/status.html"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": TITULO_STATUS, "description": DESC_STATUS, "url": u,
           "inLanguage": "pt-BR"}, migalhas_ld((NOME, DOMINIO + "/"), ("Status dos dados", u))]
    return (cabeca(TITULO_STATUS, DESC_STATUS, u, og_url, base, ld, indexar=False, extra=fundo_preload("paulista-dia", base))
            + topo(base) + corpo + rodape(base, ultimo) + consentimento(base) + fim(js))


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
            alvo = alvo.split("?")[0]
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
    sys.path.insert(0, str(SRC))
    import paginas_dados as PD
    PD.B = sys.modules[__name__]
    ativos, pregoes, ultimo, cad, com = carregar()
    noticias = ler_json(DADOS / "noticias.json") if (DADOS / "noticias.json").exists() else {"fontes": {}}
    if not CARTEIRAS:
        falha("_src/carteiras.json não existe — rode python _src/carteiras.py --gravar")
    # comunicado -> ativos do mesmo emissor (CNPJ, ou código CVM do BDR patrocinado)
    por_chave = {}
    for a in ativos:
        k = a["info"].get("cnpj") if a["tipo"] != "bdr" else ("cvm:" + a["info"]["codigo_cvm"].lstrip("0") if a["info"].get("codigo_cvm") else None)
        if k:
            por_chave.setdefault(k, []).append(a)
    D = PD.carregar()
    D["modificado"] = dt.date.today().isoformat()
    vals = PD.valores_calc(D)
    guias = sorted((ler_pagina(f) for f in (SRC / "paginas" / "guias").glob("*.html")), key=lambda g: g["slug"])
    calcs = sorted((ler_pagina(f) for f in (SRC / "paginas" / "calculadoras").glob("*.html")), key=lambda g: g["slug"])
    for g in calcs:
        g["corpo"], g["script"] = PD.injetar(g["corpo"], vals), PD.injetar(g["script"], vals)
    ordem_guias = ["o-que-e-dividend-yield", "o-que-e-p-l", "como-funciona-o-imposto-de-renda-na-bolsa",
                   "darf-de-acoes", "prejuizo-na-bolsa-como-compensar", "como-declarar-acoes-no-imposto-de-renda",
                   "como-declarar-fundos-imobiliarios-no-imposto-de-renda", "como-declarar-bdrs-e-etfs-no-imposto-de-renda",
                   "como-declarar-renda-fixa-e-tesouro-direto-no-imposto-de-renda"]
    ordem_calcs = ["simulador-renda-fixa", "calculadora-darf-acoes", "juros-compostos", "reserva-de-emergencia", "primeiro-milhao"]
    calcs.sort(key=lambda g: ordem_calcs.index(g["slug"]) if g["slug"] in ordem_calcs else 99)
    guias.sort(key=lambda g: ordem_guias.index(g["slug"]) if g["slug"] in ordem_guias else 99)
    for g in guias:
        if not g["fontes"]:
            falha(f"guia {g['slug']}: sem fontes")

    seo = {"home": (TITULO_HOME, DESC_HOME), "ativos": (TITULO_ATIVOS, DESC_ATIVOS), "sobre": (TITULO_SOBRE, DESC_SOBRE),
           "contato": (TITULO_CONTATO, DESC_CONTATO), "privacidade": (TITULO_PRIV, DESC_PRIV),
           "guias": (TITULO_GUIAS, DESC_GUIAS), "calculadoras": (TITULO_CALCS, DESC_CALCS),
           "status": (TITULO_STATUS, DESC_STATUS), "comunicados": (TITULO_COM, DESC_COM), "noticias": (TITULO_NOT, DESC_NOT)}
    seo.update({TIPOS[t][2]: LISTAS[t] for t in TIPOS})
    seo.update({f"ativos/{a['slug']}": (titulo_ativo(a), descricao_ativo(a)) for a in ativos})
    seo.update({f"guias/{g['slug']}": (g["titulo"], g["descricao"]) for g in guias})
    seo.update({f"calculadoras/{g['slug']}": (g["titulo"], g["descricao"]) for g in calcs})
    og_ind = og("og-indicadores.jpg", "Dados abertos · Banco Central e Tesouro", "Indicadores de hoje, com fonte e data.", "mercadonalupa.com.br")
    paginas_d = {
        "indicadores.html": PD.p_hub(D, og_ind),
        "indicadores/selic-hoje.html": PD.p_selic(D, og_ind),
        "indicadores/cdi-hoje.html": PD.p_cdi(D, og_ind),
        "indicadores/ipca-acumulado-12-meses.html": PD.p_ipca(D, og_ind),
        "indicadores/rendimento-da-poupanca.html": PD.p_poupanca(D, og_ind),
        "indicadores/dolar-ptax-hoje.html": PD.p_moeda(D, og_ind, "dolar"),
        "indicadores/euro-ptax-hoje.html": PD.p_moeda(D, og_ind, "euro"),
        "tesouro-direto.html": PD.p_tesouro(D, og_ind),
    }
    glo = PD.p_glossario(D, og("og-glossario.jpg", "Glossário", "Termos do mercado, explicados.", "mercadonalupa.com.br"))
    if glo:
        paginas_d["glossario.html"] = glo
    seo.update({k[:-5]: (t, d) for k, (t, d, _) in paginas_d.items()})
    conferir_seo(seo)
    RODAPE_LINKS["guias"] = [(g["slug"], g["h1"]) for g in guias]
    RODAPE_LINKS["calculadoras"] = [(g["slug"], g["h1"]) for g in calcs]

    gerar_marca()
    og_home = og("og-home.jpg", "Dados públicos · B3 e CVM", "O mercado brasileiro, com lupa e com fonte.", "mercadonalupa.com.br")
    og_a = {a["codigo"]: og(f"og-{a['slug']}.jpg", TIPOS[a["tipo"]][0] + " · B3", f"{a['codigo']} — {nome_curto(a)}",
                            "Cotação em reais, histórico e o que é um BDR" if a["tipo"] == "bdr" else "Cotação de fechamento, histórico e cadastro")
            for a in ativos}
    og_g = {g["slug"]: og(f"og-guia-{g['slug']}.jpg", "Guia", g["h1"], "mercadonalupa.com.br") for g in guias}
    og_c = {g["slug"]: og(f"og-calc-{g['slug']}.jpg", "Calculadora", g["h1"], "Simulação educativa") for g in calcs}

    saidas = {}
    I = D["I"]
    faixa_ind = f"""{divisor()}
<h2 id="indicadores">Indicadores de hoje</h2>
<p class="data-regra">Dados abertos do Banco Central e do Tesouro Nacional, cada número com a sua data de referência.</p>
<ul class="ind-grade">
<li><a class="ind-cartao" href="indicadores/selic-hoje.html"><span class="rotulo">Meta Selic</span><span class="ind-valor num">{br(I['meta']['valor'])}%</span><span class="ind-ref">ao ano · desde {data_br(I['meta']['desde'])}</span></a></li>
<li><a class="ind-cartao" href="indicadores/cdi-hoje.html"><span class="rotulo">CDI em 12 meses</span><span class="ind-valor num">{br(I['cdi']['acum12'])}%</span><span class="ind-ref">até {data_br(I['cdi']['data'])}</span></a></li>
<li><a class="ind-cartao" href="indicadores/ipca-acumulado-12-meses.html"><span class="rotulo">IPCA em 12 meses</span><span class="ind-valor num">{br(I['ipca']['doze'])}%</span><span class="ind-ref">até {mes_ano(I['ipca']['ref'])}</span></a></li>
<li><a class="ind-cartao" href="indicadores/dolar-ptax-hoje.html"><span class="rotulo">Dólar PTAX</span><span class="ind-valor num">R$ {br(I['dolar']['venda'], 4)}</span><span class="ind-ref">venda · {data_br(I['dolar']['data'])}</span></a></li>
</ul>
<p><a href="indicadores.html">Todos os indicadores</a> · <a href="tesouro-direto.html">Tesouro Direto hoje</a> · <a href="calculadoras/simulador-renda-fixa.html">Simulador de renda fixa</a> · <a href="glossario.html">Glossário</a></p>"""
    saidas["index.html"] = home(ativos, ultimo, guias, calcs, og_home, com, por_chave, noticias, faixa_ind)
    for k, (_, _, h) in paginas_d.items():
        saidas[k] = h
    saidas["ativos.html"] = pagina_ativos(ativos, ultimo, og_home)
    for t in TIPOS:
        saidas[f"{TIPOS[t][2]}.html"] = pagina_lista(t, ativos, ultimo, og_home)
    saidas["comunicados.html"] = pagina_comunicados(com, por_chave, og_home, ultimo)
    saidas["noticias.html"] = pagina_noticias(noticias, og_home, ultimo)
    for a in ativos:
        a["serie"], a["corte"] = serie_longa(a)
    escreve_series(ativos, RAIZ / "assets" / "serie")
    js = ATIVO_JS_SRC.read_text(encoding="utf-8")
    alvo_js = RAIZ / "assets" / "ativo.js"
    if not alvo_js.exists() or alvo_js.read_text(encoding="utf-8") != js:
        alvo_js.write_text(js, encoding="utf-8")
    for a in ativos:
        saidas[f"ativos/{a['slug']}.html"] = pagina_ativo(a, ativos, ultimo, og_a[a["codigo"]], cad["gerado_em"], pregoes)
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
    # status.html: noindex e fora do sitemap. Leva a hora da geração, então muda a cada build.
    gerado = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    saidas["status.html"] = pagina_status(ativos, pregoes, ultimo, gerado, og_home, com, noticias, PD.status_html(D))
    conferir_feriados(pregoes)

    for nome, txt in saidas.items():
        conferir_texto(nome, txt)

    # grava, e apaga páginas geradas que não existem mais
    for pasta in ("ativos", "guias", "calculadoras", "indicadores"):
        (RAIZ / pasta).mkdir(exist_ok=True)
        for velho in (RAIZ / pasta).glob("*.html"):
            if f"{pasta}/{velho.name}" not in saidas:
                velho.unlink()
                print("removido:", f"{pasta}/{velho.name}")
    escritos = []
    for nome, txt in saidas.items():
        p = RAIZ / nome
        # só reescreve o que mudou (o OneDrive e o git agradecem)
        if not p.exists() or p.read_text(encoding="utf-8") != txt:
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
    datas.update({f"{DOMINIO}/{TIPOS[t][2]}.html": ultimo for t in TIPOS})
    if com["docs"]:
        datas[f"{DOMINIO}/comunicados.html"] = max(d["d"] for d in com["docs"])
    itens_not = [i["d"][:10] for f in noticias.get("fontes", {}).values() for i in f.get("itens", [])]
    if itens_not:
        datas[f"{DOMINIO}/noticias.html"] = max(itens_not)
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
    # dados abertos: a data de referência mais recente dos números da página
    I = D["I"]
    ref_ind = {"indicadores/selic-hoje.html": max(I["meta"]["data"], I["selic"]["data"]),
               "indicadores/cdi-hoje.html": I["cdi"]["data"], "indicadores/ipca-acumulado-12-meses.html": I["ipca"]["ref"],
               "indicadores/rendimento-da-poupanca.html": I["poup"]["ini"], "indicadores/dolar-ptax-hoje.html": I["dolar"]["data"],
               "indicadores/euro-ptax-hoje.html": I["euro"]["data"], "tesouro-direto.html": D["td"]["data_base"]}
    ref_ind["indicadores.html"] = max(ref_ind.values())
    for k, d in ref_ind.items():
        datas[f"{DOMINIO}/{k}"] = min(d, dt.date.today().isoformat())
    if "glossario.html" in paginas_d:
        datas[f"{DOMINIO}/glossario.html"] = data_git(SRC / "glossario.json")
    (RAIZ / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in datas.items()) + "</urlset>\n", encoding="utf-8")
    (RAIZ / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /_src/\nDisallow: /dados/\n\nSitemap: {DOMINIO}/sitemap.xml\n", encoding="utf-8")

    (RAIZ / "CREDITOS-IMAGENS.md").write_text(creditos_md() + "\n", encoding="utf-8")
    conferir_links(escritos)
    atraso = (dt.date.today() - dt.date.fromisoformat(ultimo)).days
    print(f"ok: {len(saidas)} páginas · {len(ativos)} ativos · {len(guias)} guias · {len(calcs)} calculadoras · "
          f"último pregão {data_br(ultimo)}" + (f" · ATENÇÃO: {atraso} dias sem pregão novo" if atraso > 5 else ""))


if __name__ == "__main__":
    main()
