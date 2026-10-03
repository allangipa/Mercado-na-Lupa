#!/usr/bin/env python3
"""Prepara as fotos de fundo listadas em _src/fundos.json.

    python _src/fundos.py            (a partir da raiz do site)

Baixa o original do Wikimedia Commons para _tmp/fundos/ (só se faltar; uma
requisição por vez, com User-Agent identificado), recorta, dessatura,
escurece e grava em assets/img/fundo/ nas larguras de LARGURAS, em WebP e
JPEG de reserva. Roda à mão quando uma foto entra ou muda: o build só confere
se os arquivos existem e escreve os créditos.

Toda foto daqui é de terceiro sob licença aberta (domínio público, CC0, CC BY
ou CC BY-SA). NC (não comercial) não entra: o site exibe anúncios.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageEnhance

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
FUNDOS = json.loads((RAIZ / "_src" / "fundos.json").read_text(encoding="utf-8"))
TMP = RAIZ / "_tmp" / "fundos"
SAIDA = RAIZ / "assets" / "img" / "fundo"
UA = "MercadoNaLupa-site/1.0 (allangipa@gmail.com)"
LARGURAS = (640, 1280, 1920)
LICENCAS_OK = ("Domínio público", "CC0", "CC BY ", "CC BY-SA ")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def original(chave, f):
    TMP.mkdir(parents=True, exist_ok=True)
    arq = TMP / f"{chave}.jpg"
    if arq.exists():
        return arq
    api = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "titles": f["commons"], "prop": "imageinfo", "iiprop": "url|size",
         "iiurlwidth": 2560, "format": "json"})
    ii = next(iter(json.loads(get(api))["query"]["pages"].values()))["imageinfo"][0]
    time.sleep(1.5)
    arq.write_bytes(get(ii["thumburl"] if ii["width"] > 2560 else ii["url"]))
    time.sleep(1.5)
    return arq


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    for chave, f in FUNDOS.items():
        if chave.startswith("_"):
            continue
        if not any(f["licenca"].startswith(l) or f["licenca"] == l.strip() for l in LICENCAS_OK) or "NC" in f["licenca"]:
            raise SystemExit(f"PARADO: {chave}: licença {f['licenca']!r} não aceita")
        im = Image.open(original(chave, f)).convert("RGB")
        W, H = im.size
        x0, y0, x1, y1 = f["recorte"]
        im = im.crop((round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H)))
        im = ImageEnhance.Color(im).enhance(f["saturacao"])
        im = ImageEnhance.Brightness(im).enhance(f["brilho"])
        for w in LARGURAS:
            # foto menor que a largura pedida: sai uma vez no tamanho natural e para
            # (o build lê a largura real do arquivo para o srcset)
            ww = min(w, im.width)
            r = im.resize((ww, round(im.height * ww / im.width)), Image.LANCZOS)
            r.save(SAIDA / f"{chave}-{w}.webp", "WEBP", quality=62, method=6)
            r.save(SAIDA / f"{chave}-{w}.jpg", "JPEG", quality=72, optimize=True, progressive=True)
            print(f"{chave}-{w}: {r.size[0]}x{r.size[1]}  webp {(SAIDA / f'{chave}-{w}.webp').stat().st_size // 1024} KB  "
                  f"jpg {(SAIDA / f'{chave}-{w}.jpg').stat().st_size // 1024} KB")
            if ww < w:
                break


if __name__ == "__main__":
    main()
