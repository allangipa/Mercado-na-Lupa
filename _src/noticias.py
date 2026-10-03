#!/usr/bin/env python3
"""Manchetes de fontes oficiais e públicas, para a página Notícias.

    python _src/noticias.py

Só TÍTULO, DATA e LINK de cada item, com o crédito da fonte. Nenhum texto é
republicado: das quatro fontes, nenhuma declara hoje uma licença aberta que
cubra reprodução comercial (conferido em 03/10/2026 — ver README, "Notícias").

Fontes (uma falha não derruba as outras nem as cotações: o erro fica anotado
em dados/noticias.json, a status.html mostra, e o script sai com código 0):
  agencia-brasil  Agência Brasil (EBC), RSS da editoria de Economia
  bcb-notas       Banco Central, feed "Notas à imprensa"
  bcb-copom       Banco Central, feed "Comunicados do Copom"
  b3              B3, página de notícias (b3.com.br/pt_br/noticias/)
  tesouro         Tesouro Nacional, notícias do gov.br (API do portal)
Nenhum veículo privado.
"""
import datetime as dt
import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "noticias.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; mercadonalupa.com.br; manchetes com link)"}
POR_FONTE = 12
BRT = dt.timezone(dt.timedelta(hours=-3))

FONTES = {
    "agencia-brasil": {"nome": "Agência Brasil", "orgao": "EBC", "site": "https://agenciabrasil.ebc.com.br/economia",
                       "url": "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml", "dominio": "agenciabrasil.ebc.com.br",
                       "uso": "Reprodução autorizada a veículos jornalísticos com citação; uso comercial pede licença à EBC. Aqui: só título e link."},
    "bcb-notas": {"nome": "Banco Central — notas à imprensa", "orgao": "BCB", "site": "https://www.bcb.gov.br/",
                  "url": "https://www.bcb.gov.br/api/feed/sitebcb/sitefeeds/notasImprensa", "dominio": "www.bcb.gov.br",
                  "uso": "Sem licença aberta declarada no site. Aqui: só título e link."},
    "bcb-copom": {"nome": "Banco Central — comunicados do Copom", "orgao": "BCB", "site": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom",
                  "url": "https://www.bcb.gov.br/api/feed/sitebcb/sitefeeds/comunicadoscopom", "dominio": "www.bcb.gov.br",
                  "uso": "Sem licença aberta declarada no site. Aqui: só título e link."},
    "b3": {"nome": "B3 — notícias", "orgao": "B3", "site": "https://www.b3.com.br/pt_br/noticias/",
           "url": "https://www.b3.com.br/pt_br/noticias/", "dominio": "www.b3.com.br",
           "uso": "Conteúdo da B3 com direitos reservados. Aqui: só título e link."},
    "tesouro": {"nome": "Tesouro Nacional — notícias", "orgao": "Tesouro Nacional", "site": "https://www.gov.br/tesouronacional/pt-br/noticias",
                "url": "https://www.gov.br/tesouronacional/++api++/pt-br/noticias/@search?portal_type=News%20Item&sort_on=effective&sort_order=reverse&b_size=20&metadata_fields=effective",
                "dominio": "www.gov.br",
                "uso": "Sem licença aberta conferida para o conteúdo. Aqui: só título e link."},
}


def baixar(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def limpa(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def iso(d):
    return d.astimezone(BRT).isoformat(timespec="minutes")


def rss(corpo):
    raiz = ET.fromstring(corpo)
    for it in raiz.iter("item"):
        yield limpa(it.findtext("title")), (it.findtext("link") or "").strip(), iso(parsedate_to_datetime(it.findtext("pubDate")))


def atom(corpo):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    raiz = ET.fromstring(corpo.lstrip(b"\xef\xbb\xbf"))
    for en in raiz.findall("a:entry", ns):
        lk = en.find("a:link", ns)
        yield (limpa(en.findtext("a:title", namespaces=ns)), lk.get("href") if lk is not None else "",
               iso(dt.datetime.fromisoformat(en.findtext("a:updated", namespaces=ns))))


def b3(corpo):
    t = corpo.decode("utf-8", "replace")
    for m in re.finditer(r'<a id="link-noticia" href="([^"]+)">.*?<p>(\d{2}/\d{2}/\d{4})</p>.*?<h4[^>]*>.*?</h4>\s*<p>(.*?)</p>', t, re.S):
        link = urllib.parse.urljoin("https://www.b3.com.br/pt_br/noticias/", html.unescape(m.group(1)))
        d = dt.datetime.strptime(m.group(2), "%d/%m/%Y").date().isoformat()
        yield limpa(m.group(3)), link, d


def tesouro(corpo):
    for it in json.loads(corpo)["items"]:
        yield limpa(it["title"]), it["@id"], iso(dt.datetime.fromisoformat(it["effective"]))


LEITOR = {"agencia-brasil": rss, "bcb-notas": atom, "bcb-copom": atom, "b3": b3, "tesouro": tesouro}


def coleta(chave, f):
    itens = []
    for titulo, link, data in LEITOR[chave](baixar(f["url"])):
        u = urllib.parse.urlparse(link)
        if not titulo or u.scheme != "https" or u.netloc != f["dominio"]:
            continue  # só link para o próprio site da fonte
        itens.append({"t": titulo[:200], "u": link, "d": data})
    itens.sort(key=lambda i: i["d"], reverse=True)
    if not itens:
        raise ValueError("nenhum item lido — o formato da fonte mudou?")
    return itens[:POR_FONTE]


def main():
    velho = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {"fontes": {}}
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    saida = {"_leia": "Gerado por _src/noticias.py. Só título, data e link; o texto fica na fonte.",
             "coletado_em": agora, "fontes": {}}
    for chave, f in FONTES.items():
        ant = velho["fontes"].get(chave, {})
        meta = {k: f[k] for k in ("nome", "orgao", "site", "url", "uso")}
        try:
            itens = coleta(chave, f)
            saida["fontes"][chave] = {**meta, "ok": True, "coletado_em": agora, "itens": itens}
            print(f"  {chave}: {len(itens)} itens, mais recente {itens[0]['d'][:10]}")
        except Exception as ex:  # noqa: BLE001 — falha isolada de propósito
            saida["fontes"][chave] = {**meta, "ok": False, "erro": f"{type(ex).__name__}: {ex}"[:300], "falhou_em": agora,
                                      "coletado_em": ant.get("coletado_em"), "itens": ant.get("itens", [])}
            print(f"  {chave}: FALHOU ({ex}); mantidos {len(ant.get('itens', []))} itens anteriores")
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("ok: dados/noticias.json")


if __name__ == "__main__":
    main()
