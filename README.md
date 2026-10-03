# Mercado na Lupa

Site estático de dados públicos sobre o mercado brasileiro — mercadonalupa.com.br.
Gerado em Python, publicado na Hostinger por push no GitHub, como os outros
sites da casa.

**Educativo, nunca recomendação.** Nada de "compre/venda", carteira, preço-alvo
ou nota. O build tem uma trava de linguagem (`RECOMENDACAO` em `_src/build.py`)
que para a publicação se aparecer texto desse tipo.

## Estrutura

```
_src/
  build.py          gera o site inteiro (nunca edite os .html da raiz)
  b3.py             leitor do arquivo COTAHIST da B3, porteiro do layout
  atualiza.py       baixa os arquivos da B3 e grava dados/
  cvm.py            baixa o cadastro da CVM e grava dados/cadastro.json
  ativos.json       A LISTA de ativos acompanhados (código, tipo, nome curto, CNPJ)
  eventos.json      desdobramentos/grupamentos declarados (ver "Variação anormal")
  site.css          estilos (vão inline no <head> de cada página)
  paginas/guias/         um .html por guia, com front matter JSON no 1º comentário
  paginas/calculadoras/  idem, com o <script> da calculadora no fim
  fontes-ttf/       fontes para desenhar as imagens og (Archivo, Fraunces, Plex Mono; OFL)
dados/
  cotacoes/<CODIGO>.csv  um pregão por linha, desde 02/01/2025
  pregoes.csv            todos os pregões processados
  papeis.json            nome de pregão, especificação e ISIN (da B3)
  cadastro.json          cadastro da CVM
.github/workflows/atualiza.yml   rotina diária (A ATIVAR, ver abaixo)
_tmp/               downloads (fora do git)
```

## Rodar localmente

```
python _src/build.py
python -m http.server 8765        # e abra http://localhost:8765/
```

Precisa de Python 3.12+ e Pillow. O Python da Microsoft Store não enxerga
`AppData\Local`: por isso todo temporário fica em `_tmp/`, dentro da pasta.

## Dados

### Cotações — B3

Fonte: série histórica de cotações, arquivo COTAHIST, em
`https://bvmf.bmfbovespa.com.br/InstDados/SerHist/`:

- `COTAHIST_DddmmAAAA.ZIP` — um pregão (404 em fim de semana e feriado)
- `COTAHIST_AAAAA.ZIP` — o ano inteiro (~90 MB)

Layout oficial (revisão 02, 05/10/2020):
https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf

```
python _src/atualiza.py diario               # pregões que faltam até hoje
python _src/atualiza.py historico 2025 2026  # carga inicial pelos anuais
python _src/atualiza.py arquivo X.ZIP        # importa um arquivo baixado à mão
```

O leitor (`b3.py`) **para e não grava nada** se: linha com tamanho diferente de
245; header/trailer fora do formato; contagem do trailer não bate; campo
numérico com letra; moeda diferente de R$; fator de cotação diferente de 1;
ISIN fora do padrão; abertura/média/fechamento fora da faixa mínima–máxima; ou
volume incoerente com quantidade × preço médio (sinal de layout deslocado). E
`atualiza.py` para se um pregão já gravado vier com número diferente.

Uma diferença entre o PDF e os arquivos reais, conferida em 03/10/2026: o PDF
diz que o total do trailer inclui header e trailer; os arquivos reais contam só
os registros 01. O leitor aceita as duas leituras.

Filtro: mercado à vista (TPMERC 010), lote padrão (CODBDI 02) ou fundo
imobiliário (CODBDI 12). "Fechamento" é o PREULT (último negócio).

### Cadastro — CVM

```
python _src/cvm.py            # baixa e grava dados/cadastro.json
python _src/cvm.py --se-velho # só se ainda não rodou neste mês, a partir do dia 16
```

Companhias: `cad_cia_aberta.csv`. Fundos imobiliários: informe mensal
(`inf_mensal_fii_AAAA.zip`, arquivos geral e complemento). Casa pelo CNPJ de
`ativos.json` e para se não achar, ou se o ISIN da CVM divergir do da B3.

### Variação anormal

O build para se um ativo variar mais de 25% num pregão. Se for desdobramento,
grupamento ou outro evento real, declare em `_src/eventos.json`:

```json
{"PETR4": {"2027-04-15": "desdobramento de 1 para 2"}}
```

A página passa a mostrar o aviso do evento e não exibe a variação daquele dia.

## Adicionar um ativo

1. Acrescente em `_src/ativos.json` (código, `acao` ou `fii`, nome curto, CNPJ).
2. `python _src/atualiza.py historico 2025 2026` (os anuais ficam em `_tmp/`).
3. `python _src/cvm.py`
4. `python _src/build.py`

## Travas do build

- título ≤ 60 caracteres e único; descrição entre 120 e 155 e única;
- JSON-LD em toda página (WebSite/Organization, WebPage, Article,
  CollectionPage, BreadcrumbList); canonical; `max-image-preview:large`;
  404 com `noindex`;
- sitemap com `lastmod` (ativos: data do pregão; guias: commit do arquivo;
  fixas: commit do build.py); robots com o sitemap;
- links internos e âncoras conferidos depois de gerar;
- guia sem fontes não sai;
- trava de linguagem de recomendação no texto visível;
- CSS inline; fontes no próprio domínio; imagens og em JPEG 1200×630.

## Publicação

Mesmo fluxo dos outros sites: o repositório no GitHub é ligado à Hostinger, e
cada push na branch principal publica a raiz.

### Rotina diária (A ATIVAR)

`.github/workflows/atualiza.yml` está pronto, mas **só passa a valer quando o
repositório existir no GitHub**. Ao criar:

1. Faça o push do repositório.
2. Settings › Actions › General › Workflow permissions: **Read and write**.
3. Rode uma vez à mão (aba Actions › Atualiza cotações › Run workflow).

Ele roda às 19h30 e à 1h30 (Brasília) em dia útil, baixa o que faltar, roda o
build e faz commit e push só se algo mudou. Falha = nada é commitado, e o
GitHub avisa por e-mail.

## AdSense

`ADSENSE_LIGADO` em `_src/build.py`. Publisher `ca-pub-4401770243539507`, o
mesmo dos outros sites; `ads.txt` gerado pelo build. A faixa de consentimento
injeta o script e sai da frente quando a mensagem do Google (`__tcfapi`) diz
que o GDPR se aplica. O site ainda precisa ser **adicionado e aprovado** no
painel do AdSense.
