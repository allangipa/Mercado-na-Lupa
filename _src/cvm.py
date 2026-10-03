#!/usr/bin/env python3
"""Cadastro dos ativos a partir dos dados abertos da CVM (dados.cvm.gov.br).

    python _src/cvm.py

Companhias: cadastro de companhias abertas
    https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
Fundos imobiliários: informe mensal estruturado (geral e complemento)
    https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_AAAA.zip

Grava dados/cadastro.json. Casa pelo CNPJ de _src/ativos.json e PARA se
algum CNPJ não for achado, ou se o ISIN informado à CVM (fundos) não bater
com o ISIN que a B3 traz para o código. O informe mensal muda uma vez por
mês: o workflow roda com --se-velho, que só baixa de novo a partir do dia 16
(prazo de entrega do informe) e uma vez por mês.
"""
import csv
import datetime as dt
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
FII = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"


def falha(msg):
    print("PARADO: " + msg)
    sys.exit(1)


def baixar(url, nome):
    TMP.mkdir(exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "mercadonalupa.com.br"})
    with urllib.request.urlopen(req, timeout=180) as r:
        corpo = r.read()
    (TMP / nome).write_bytes(corpo)
    return corpo


def linhas_csv(texto):
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def titulo(s):
    """RIO DE JANEIRO -> Rio de Janeiro."""
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    ps = s.strip().lower().split()
    return " ".join(p if (i and p in pequenas) else p.capitalize() for i, p in enumerate(ps))


def num(s):
    s = (s or "").strip()
    return float(s) if s else None


def main():
    if "--se-velho" in sys.argv:
        arq = RAIZ / "dados" / "cadastro.json"
        hoje = dt.date.today()
        if arq.exists():
            gerado = dt.date.fromisoformat(json.loads(arq.read_text(encoding="utf-8"))["gerado_em"])
            if hoje.day < 16 or (gerado.year, gerado.month) == (hoje.year, hoje.month) and gerado.day >= 16:
                print(f"cadastro da CVM de {gerado}: mantido")
                return
    ativos = json.loads((RAIZ / "_src" / "ativos.json").read_text(encoding="utf-8"))
    papeis = json.loads((RAIZ / "dados" / "papeis.json").read_text(encoding="utf-8"))
    saida = {"gerado_em": dt.date.today().isoformat(), "ativos": {}}

    cias = {l["CNPJ_CIA"]: l for l in linhas_csv(baixar(CAD, "cad_cia_aberta.csv").decode("latin-1"))}
    ano = dt.date.today().year
    try:
        z = zipfile.ZipFile(io.BytesIO(baixar(FII.format(ano=ano), f"inf_fii_{ano}.zip")))
    except Exception:  # janeiro, antes do primeiro informe do ano
        ano -= 1
        z = zipfile.ZipFile(io.BytesIO(baixar(FII.format(ano=ano), f"inf_fii_{ano}.zip")))
    geral = linhas_csv(z.read(f"inf_mensal_fii_geral_{ano}.csv").decode("latin-1"))
    compl = linhas_csv(z.read(f"inf_mensal_fii_complemento_{ano}.csv").decode("latin-1"))

    def ultimo(linhas, cnpj):
        ls = [l for l in linhas if l["CNPJ_Fundo_Classe"] == cnpj]
        if not ls:
            return None
        return max(ls, key=lambda l: (l["Data_Referencia"], int(l["Versao"])))

    for a in ativos:
        c, cnpj = a["codigo"], a["cnpj"]
        if a["tipo"] == "acao":
            l = cias.get(cnpj)
            if not l:
                falha(f"{c}: CNPJ {cnpj} não está no cadastro de companhias abertas da CVM")
            if not l["SIT"].startswith("ATIVO"):
                falha(f"{c}: situação na CVM é {l['SIT']!r}")
            saida["ativos"][c] = {
                "fonte": "CVM, cadastro de companhias abertas", "fonte_url": CAD,
                "razao_social": l["DENOM_SOCIAL"].strip(), "nome_comercial": l["DENOM_COMERC"].strip(),
                "cnpj": cnpj, "codigo_cvm": l["CD_CVM"].strip(), "setor": l["SETOR_ATIV"].strip(),
                "controle": l["CONTROLE_ACIONARIO"].strip(), "municipio": titulo(l["MUN"]),
                "uf": l["UF"].strip(), "registro_cvm": l["DT_REG"].strip(), "constituicao": l["DT_CONST"].strip(),
            }
        else:
            g, k = ultimo(geral, cnpj), ultimo(compl, cnpj)
            if not g or not k:
                falha(f"{c}: CNPJ {cnpj} sem informe mensal de {ano} na CVM")
            if g["Codigo_ISIN"].strip() != papeis[c]["isin"]:
                falha(f"{c}: ISIN na CVM {g['Codigo_ISIN']!r} difere do ISIN na B3 {papeis[c]['isin']!r}")
            saida["ativos"][c] = {
                "fonte": "CVM, informe mensal de fundos imobiliários", "fonte_url": FII.format(ano=ano),
                "razao_social": g["Nome_Fundo_Classe"].strip(), "cnpj": cnpj,
                "inicio_funcionamento": g["Data_Funcionamento"].strip(), "publico_alvo": g["Publico_Alvo"].strip(),
                "segmento": g["Segmento_Atuacao"].strip(), "mandato": g["Mandato"].strip(),
                "gestao": g["Tipo_Gestao"].strip(), "administrador": g["Nome_Administrador"].strip(),
                "referencia": k["Data_Referencia"], "cotistas": int(k["Total_Numero_Cotistas"]),
                "patrimonio_liquido": num(k["Patrimonio_Liquido"]), "cotas_emitidas": num(k["Cotas_Emitidas"]),
                "vp_cota": num(k["Valor_Patrimonial_Cotas"]), "dy_mes": num(k["Percentual_Dividend_Yield_Mes"]),
            }
        print(f"  {c}: {saida['ativos'][c]['razao_social']}")
    (RAIZ / "dados" / "cadastro.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("ok: dados/cadastro.json")


if __name__ == "__main__":
    main()
