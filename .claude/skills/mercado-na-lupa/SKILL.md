---
name: mercado-na-lupa
description: Como trabalhar no site Mercado na Lupa (mercadonalupa.com.br), site estático em Python de dados públicos do mercado brasileiro (245 ativos da B3, comunicados da CVM, notícias oficiais, indicadores do BC, Tesouro Direto). Use ao criar ou editar qualquer página (ativo, guia, calculadora, indicador, comunicados, notícias, glossário), mexer no CSS ou no gráfico, mudar a lista de ativos, atualizar dados da B3/CVM/BC/Tesouro, resolver uma parada do build ou publicar.
---

# Mercado na Lupa

Site estático de dados públicos sobre o mercado brasileiro. Gerado por `_src/build.py`,
publicado na Hostinger por push no GitHub (`allangipa/Mercado-na-Lupa`, branch `main` =
produção). Detalhes completos no `README.md` da raiz; esta skill é o resumo operacional.
Em caso de dúvida sobre fórmula, fonte ou número conferido, o README manda.

## Regras que mandam em tudo

1. **Educativo, nunca recomendação.** Nada de "compre/venda", carteira sugerida, preço-alvo,
   nota ou "vale a pena investir". O build tem a trava `RECOMENDACAO` (regex em
   `_src/build.py`) que PARA a publicação se esse tipo de texto aparecer; manchete ou
   assunto de comunicado com essa linguagem é descartado. Não contorne a trava: reescreva.
2. **Nunca edite os `.html` da raiz** (`index.html`, `ativos/`, `guias/`, `calculadoras/`,
   `indicadores/`, `comunicados.html` etc.) nem `assets/serie/` ou `assets/ativo.js`. São
   gerados. Edite em `_src/` e rode o build.
3. **Número só de fonte aberta e conferida.** Dado inconsistente sai como "—" com a
   explicação, nunca inventado. CNPJ não se adivinha pelo nome. Cite a lei/norma e a data
   em que foi conferida.
4. **Licenças.** IGP-M (FGV) fica de fora. Notícias: só título, data e link, nenhum
   veículo privado, nada de resumo. Proventos por evento não vêm da B3 (só CVM). Fotos: só
   PD, CC0, CC BY, CC BY-SA (nunca NC).
5. **Concordância:** "Outras ações acompanhadas", "Outros fundos imobiliários acompanhados",
   "Outros BDRs acompanhados". Já regrediu uma vez; confira ao mexer em texto gerado.
6. Commit e push só quando o Allan pedir. Push no `main` publica o site.

## O que o site tem

- **245 ativos** (`ativos/<codigo>.html`): 96 ações (Ibovespa + 20 de maior volume), 99 FIIs
  do IFIX, 50 BDRs. Cada página: gráfico (desenhado no navegador por `ativo.js`), série de
  5 anos, dividendos, cartões de indicadores (P/L, P/VP, DY, ROE, margem), comparação com
  índices (ETFs e CDI/IPCA), comparação com o setor, ficha, comunicados, eventos.
- Listas: `ativos.html`, `acoes.html`, `fundos-imobiliarios.html`, `bdrs.html`.
- `comunicados.html` (CVM) e `noticias.html` (BC, Tesouro, B3, Agência Brasil).
- `indicadores.html` + `indicadores/` (Selic, CDI, IPCA 12M, poupança, dólar e euro PTAX),
  `tesouro-direto.html`, `glossario.html`.
- 9 guias, 5 calculadoras, sobre, contato, privacidade, 404, `status.html` (noindex).

## Onde fica cada coisa

| Quero mexer em… | Arquivo |
|---|---|
| Geração do site, travas, páginas de ativo/listas/home/status, AdSense (`ADSENSE_LIGADO`) | `_src/build.py` |
| Páginas de indicadores, Tesouro Direto, glossário, placeholders das calculadoras | `_src/paginas_dados.py` (usa funções do build via `PD.B`) |
| Gráficos, comparação, simulador e tabelas da página do ativo | `_src/ativo.js` (copiado para `assets/`) |
| Estilos (vão inline no `<head>`) | `_src/site.css` |
| Um guia / uma calculadora | `_src/paginas/guias/<slug>.html` / `_src/paginas/calculadoras/<slug>.html` |
| Lista de ativos | `_src/carteiras.py` → grava `_src/ativos.json` e `_src/carteiras.json` (nome curto ruim: `NOMES` no `carteiras.py`) |
| Desdobramento, grupamento, variação > 25% conferida | `_src/eventos.json` (com `fonte`; `"tipo": "mercado"` para variação real) |
| Linha do COTAHIST com preço médio fora da faixa | `_src/excecoes-b3.json` |
| Bandeira no selo do ativo (Brasil para ações e FIIs; BDR pelo país da empresa) | `_src/paises.json` + `pais()`/`selo()` no build; desenho em `site.css` |
| Feriados sem pregão | `_src/feriados-b3.json` (2027 provisório até a B3 publicar) |
| Termos do glossário | `_src/glossario.json` |
| Fotos de fundo e créditos | `_src/fundos.json` + `python _src/fundos.py` |
| Dados gerados | `dados/` (cotações, historico/, cadastro, comunicados, noticias, fundamentos, bcb, tesouro, `*-bom.json`) |

`paginas_dados.py` chama funções do `build.py` (`B.passo_bonito`, `B.topo`, `B.rodape`,
`B.br`…). Ao remover ou renomear uma função do build, procure `B.<nome>` lá antes.

## Coletas e falha isolada

Cada fonte externa tem seu script. Se uma falhar, fica a última coleta boa, o erro vai
para o JSON e a `status.html` mostra; o resto do site segue. O build só PARA quando não
há dado bom anterior.

```
python _src/atualiza.py diario                # pregões da B3 que faltam
python _src/atualiza.py historico 2025 2026   # carga pelos COTAHIST anuais (em _tmp/)
python _src/atualiza.py longo 2021 2022 2023 2024   # série longa -> dados/historico/
python _src/carteiras.py [--gravar]           # lista de ativos pelas carteiras da B3 e volume
python _src/cvm.py [--se-velho]               # cadastro da CVM (mensal, a partir do dia 16)
python _src/comunicados.py                    # comunicados da CVM (IPE e documentos de FII)
python _src/noticias.py                       # manchetes de fontes oficiais
python _src/fundamentos.py [--se-velho]       # balanços DFP/ITR e informes de FII (semanal)
python _src/eventos_b3.py [--gravar]          # procura na B3 o evento de variações > 25%
python _src/bcb.py                            # SGS e PTAX do Banco Central
python _src/tesouro.py                        # taxas do Tesouro Direto
python _src/build.py                          # gera o site
python -m http.server 8765                    # ver em http://localhost:8765/
```

Python 3.12+ e Pillow. Temporários sempre em `_tmp/` (o Python da Microsoft Store não
enxerga `AppData\Local`). A rotina `.github/workflows/atualiza.yml` roda tudo isso em dia
útil às 19h30 e 1h30 (Brasília) e faz commit e push só se algo mudou.

## Guias e calculadoras: front matter

```html
<!--{
 "titulo": "… · Mercado na Lupa",
 "descricao": "120 a 155 caracteres, única no site.",
 "h1": "…",
 "resumo": "…",
 "publicado": "AAAA-MM-DD",
 "atualizado": "AAAA-MM-DD",
 "fontes": [{"nome": "Lei nº …, art. …", "url": "https://…"}]
}-->
<p class="lead">…</p>
```

- Guia **sem fontes não sai** (calculadora pode ter `"fontes": []`).
- Guia com regra legal começa com `<p class="data-regra">` dizendo quando e onde foi conferida.
- `<h2>` com `id` para as âncoras; links internos e âncoras são conferidos pelo build.
- Valores do dia nas calculadoras: placeholders (`{{CDI_ANO}}`, `{{TD_TITULOS}}`…) de
  `valores_calc` em `paginas_dados.py`. Placeholder desconhecido PARA o build.
- Tom dos guias existentes: frases diretas, português correto, jargão sempre explicado.

## Travas do build (se parar, corrija a causa)

- título ≤ 60 caracteres e único; descrição entre 120 e 155 e única;
- JSON-LD, canonical, `max-image-preview:large` em toda página; 404 com `noindex`;
- links internos e âncoras válidos; guia sem fontes; trava de linguagem de recomendação;
- variação > 25% num pregão desde 2025 sem evento em `eventos.json` → rode
  `eventos_b3.py --gravar`; o que a B3 não explicar, confira à mão e declare com fonte
  (na série antiga, 2021–2024, a série só passa a começar depois da variação);
- layout da B3 fora do padrão (o `b3.py` para e não grava nada); `atualiza.py` para se um
  pregão já gravado vier diferente;
- `cvm.py` para se o ISIN da CVM divergir do da B3 ou se um ativo perder o cadastro;
- falta `_src/carteiras.json`; placeholder desconhecido em calculadora;
- série do BC/Tesouro com problema e sem dado bom anterior.

## Receitas

**Carteiras mudaram (janeiro, maio, setembro):** `carteiras.py --gravar` → `atualiza.py
historico 2025 2026` → `cvm.py` → `comunicados.py` → `build.py`.

**Ativo à mão (exceção):** acrescentar em `_src/ativos.json` (código, `acao`/`fii`/`bdr`,
nome curto, CNPJ) → `atualiza.py historico 2025 2026` → `eventos_b3.py --gravar` se parar
→ `cvm.py` e `comunicados.py` → `build.py`.

**Novo guia ou calculadora:** criar o arquivo em `_src/paginas/...` com o front matter →
build → conferir a página e o link no hub (`guias.html` / `calculadoras.html`).

**Mudança visual:** `_src/site.css` (ou o HTML em `build.py`/`paginas_dados.py`, ou
`ativo.js` para o gráfico) → build → conferir em largura de celular (375px: menu rola de
lado, página não pode transbordar) e de desktop.

**Sempre, ao terminar:** `python _src/build.py` precisa terminar com
`ok: N páginas · 245 ativos · …`; abrir as páginas afetadas no servidor local e olhar o
console do navegador.

## Git

Trabalho grande em paralelo já gerou dois caminhos divergentes (junção em 03/10/2026).
Antes de começar: `git fetch` e conferir se o `main` local está igual ao `origin/main`.
Ao juntar, as páginas geradas não se resolvem à mão: resolva só `_src/`, README e workflow,
e rode o build para regenerar o resto.

## Datas que pedem revisão

- Guias de IR (declaração de 2027, códigos do programa de 2026): revisar quando a Receita
  publicar o programa e o Perguntas e Respostas IRPF 2027 (≈ março de 2027).
- `feriados-b3.json`: trocar 2027 provisório pelo calendário oficial da B3.
- Carteiras do Ibovespa/IFIX: janeiro, maio e setembro.
- Regras com data no README (IR, IOF, custódia, LCI/LCA, JCP 17,5%, dividendos > R$ 50
  mil/mês) e licenças das notícias: conferidas em 03/10/2026.

## Pendências conhecidas

- **Termos de uso da B3:** decisão pendente do Allan (ver README). Não amplie o uso de
  dados da B3 sem falar com ele.
- Rotina diária: conferir no GitHub se as Actions estão ativas e com permissão
  "Read and write".
- AdSense: site ainda precisa ser aprovado no painel (publisher `ca-pub-4401770243539507`).
- Dados conhecidos como "—": proventos de alguns bancos (DMPL com colunas trocadas na
  CVM) e 11 FIIs sem ISIN igual no informe da CVM. É o comportamento esperado.
