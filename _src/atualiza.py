#!/usr/bin/env python3
"""Baixa a série histórica da B3 e atualiza dados/.

    python _src/atualiza.py diario               pregões que faltam, até hoje
    python _src/atualiza.py historico 2025 2026  carga inicial pelos arquivos anuais
    python _src/atualiza.py arquivo CAMINHO.ZIP  importa um arquivo já baixado

Grava:
    dados/cotacoes/<CODIGO>.csv  um pregão por linha, só os ativos de _src/ativos.json
    dados/pregoes.csv            todo pregão processado (data, registros no arquivo)
    dados/papeis.json            nome de pregão, especificação e ISIN, da última linha da B3

Downloads ficam em _tmp/ (fora do git). O Python da Microsoft Store não
enxerga AppData\\Local, então nada vai para a pasta temporária do sistema.

Para com erro (código 1) e não grava nada se o layout não bater, se um
pregão já gravado vier com número diferente, ou se a B3 responder algo que
não é ZIP. Dia sem arquivo (fim de semana, feriado, arquivo do dia ainda não
publicado) não é erro: é registrado na saída e pulado.
"""
import csv
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b3  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
DADOS = RAIZ / "dados"
COT = DADOS / "cotacoes"
URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/"
COLUNAS = ["data", "abertura", "maxima", "minima", "media", "fechamento", "negocios", "quantidade", "volume"]
INICIO_HISTORICO = dt.date(2025, 1, 1)
MAX_DIAS_ATRAS = 15


def falha(msg):
    print("PARADO: " + msg)
    sys.exit(1)


def ativos():
    return [a["codigo"] for a in json.loads((RAIZ / "_src" / "ativos.json").read_text(encoding="utf-8"))]


def baixar(nome):
    """Baixa para _tmp/. Devolve o caminho, ou None se a B3 respondeu 404."""
    TMP.mkdir(exist_ok=True)
    destino = TMP / nome
    req = urllib.request.Request(URL + nome, headers={"User-Agent": "mercadonalupa.com.br (atualizacao diaria)"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            corpo = r.read()
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            return None
        falha(f"B3 respondeu HTTP {ex.code} para {nome}")
    except urllib.error.URLError as ex:
        falha(f"sem conexão com a B3 ({ex.reason}) ao baixar {nome}")
    if corpo[:2] != b"PK":
        falha(f"{nome}: a B3 devolveu algo que não é ZIP ({corpo[:60]!r})")
    destino.write_bytes(corpo)
    return destino


def ler_csv(cod):
    arq = COT / f"{cod}.csv"
    if not arq.exists():
        return {}
    with arq.open(encoding="utf-8", newline="") as f:
        return {linha["data"]: linha for linha in csv.DictReader(f)}


def linha_csv(r):
    return {"data": r["data"].isoformat(), "abertura": f"{r['preabe']:.2f}", "maxima": f"{r['premax']:.2f}",
            "minima": f"{r['premin']:.2f}", "media": f"{r['premed']:.2f}", "fechamento": f"{r['preult']:.2f}",
            "negocios": str(r["totneg"]), "quantidade": str(r["quatot"]), "volume": f"{r['voltot']:.2f}"}


def ler_pregoes():
    arq = DADOS / "pregoes.csv"
    if not arq.exists():
        return {}
    with arq.open(encoding="utf-8", newline="") as f:
        return {l["data"]: l["registros"] for l in csv.DictReader(f)}


def importar(caminhos):
    """Lê todos os arquivos ANTES de gravar qualquer coisa: se um falhar, nada muda."""
    cods = ativos()
    novos = {c: {} for c in cods}
    pregoes = {}
    papeis = {}
    for cam in caminhos:
        try:
            meta, por_cod = b3.cotacoes(cam, cods)
            _, regs = b3.abrir(cam)
        except b3.LayoutInvalido as ex:
            falha(f"layout da B3 não bate — nada foi gravado.\n  {ex}\n"
                  "  Confira o PDF do layout e o arquivo antes de mexer no leitor.")
        contagem = {}
        for _, l in regs:
            d = dt.datetime.strptime(l[2:10], "%Y%m%d").date().isoformat()
            contagem[d] = contagem.get(d, 0) + 1
        pregoes.update({d: str(n) for d, n in contagem.items() if d >= INICIO_HISTORICO.isoformat()})
        for c, rs in por_cod.items():
            for r in rs:
                if r["data"] >= INICIO_HISTORICO:
                    novos[c][r["data"].isoformat()] = linha_csv(r)
            if rs:
                u = rs[-1]
                if c not in papeis or papeis[c]["data"] < u["data"].isoformat():
                    papeis[c] = {"data": u["data"].isoformat(), "nome_pregao": u["nomres"],
                                 "especificacao": u["especi"], "isin": u["codisi"],
                                 "fii": u["codbdi"] == "12", "bdi": u["codbdi"]}
        print(f"  lido {Path(cam).name}: {sum(contagem.values())} linhas, {len(contagem)} pregão(ões)")

    # conferência contra o que já está gravado
    for c in cods:
        velhos = ler_csv(c)
        for d, l in novos[c].items():
            if d in velhos and velhos[d] != l:
                falha(f"{c} {d}: a B3 trouxe número diferente do já gravado.\n  antes: {velhos[d]}\n  agora: {l}")
    # grava
    COT.mkdir(parents=True, exist_ok=True)
    total = 0
    for c in cods:
        tudo = ler_csv(c)
        antes = len(tudo)
        tudo.update(novos[c])
        total += len(tudo) - antes
        with (COT / f"{c}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS, lineterminator="\n")
            w.writeheader()
            for d in sorted(tudo):
                w.writerow(tudo[d])
    todos_pregoes = ler_pregoes()
    todos_pregoes.update(pregoes)
    with (DADOS / "pregoes.csv").open("w", encoding="utf-8", newline="") as f:
        f.write("data,registros\n")
        for d in sorted(todos_pregoes):
            f.write(f"{d},{todos_pregoes[d]}\n")
    arq_pap = DADOS / "papeis.json"
    pap = json.loads(arq_pap.read_text(encoding="utf-8")) if arq_pap.exists() else {}
    for c, v in papeis.items():
        if c not in pap or pap[c]["data"] <= v["data"]:
            pap[c] = v
    arq_pap.write_text(json.dumps(pap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sem = [c for c in cods if not ler_csv(c)]
    if sem:
        falha(f"sem nenhuma cotação gravada para {sem}: código errado em _src/ativos.json?")
    print(f"ok: {total} linhas novas; último pregão gravado {max(todos_pregoes)}")
    return total


def diario(hoje=None):
    hoje = hoje or dt.date.today()
    pregoes = ler_pregoes()
    if not pregoes:
        falha("dados/pregoes.csv vazio: rode primeiro `historico` para a carga inicial")
    ultimo = dt.date.fromisoformat(max(pregoes))
    d = ultimo + dt.timedelta(days=1)
    if (hoje - d).days > MAX_DIAS_ATRAS:
        falha(f"o último pregão gravado é {ultimo}, há mais de {MAX_DIAS_ATRAS} dias: "
              "rode `historico` com o ano para não deixar buraco")
    baixados = []
    while d <= hoje:
        if d.weekday() < 5:
            nome = f"COTAHIST_D{d:%d%m%Y}.ZIP"
            cam = baixar(nome)
            if cam is None:
                print(f"  {d}: a B3 não tem {nome} (feriado, ou arquivo ainda não publicado)")
            else:
                baixados.append(cam)
        d += dt.timedelta(days=1)
    if not baixados:
        print("nada novo: nenhum pregão a acrescentar")
        return 0
    return importar(baixados)


def historico(anos):
    cams = []
    for a in anos:
        nome = f"COTAHIST_A{a}.ZIP"
        cam = TMP / nome
        if not cam.exists():
            print(f"  baixando {nome} (~90 MB)…")
            cam = baixar(nome)
            if cam is None:
                falha(f"a B3 não tem {nome}")
        cams.append(cam)
    return importar(cams)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "diario":
        diario()
    elif cmd == "historico" and len(sys.argv) > 2:
        historico([int(a) for a in sys.argv[2:]])
    elif cmd == "arquivo" and len(sys.argv) > 2:
        importar([Path(p) for p in sys.argv[2:]])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
