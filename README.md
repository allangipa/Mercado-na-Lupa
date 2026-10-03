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
  feriados-b3.json  dias de semana sem pregão (2026 oficial da B3; 2027 PROVISÓRIO até a B3 publicar),
                    usados pelo selo de atualização e pela status.html; o build avisa se faltar o ano
  site.css          estilos (vão inline no <head> de cada página)
  fundos.json       fotos de fundo (topo e faixas): obra, autor, licença, recorte
  fundos.py         baixa do Commons, recorta, escurece e grava assets/img/fundo/ (WebP + JPEG);
                    rode à mão quando uma foto entrar ou mudar. Só PD, CC0, CC BY, CC BY-SA (nunca NC).
                    O build escreve CREDITOS-IMAGENS.md e o crédito visível de cada página.
  paginas/guias/         um .html por guia, com front matter JSON no 1º comentário
  paginas/calculadoras/  idem, com o <script> da calculadora no fim
  fontes-ttf/       fontes para desenhar as imagens og (Archivo, Fraunces, Plex Mono; OFL)
  bcb.py            indicadores do Banco Central (SGS e PTAX) -> dados/bcb.json
  tesouro.py        taxas e preços do Tesouro Direto (Tesouro Transparente) -> dados/tesouro.json
  paginas_dados.py  páginas de indicadores, Tesouro Direto e glossário (chamado pelo build.py)
  glossario.json    os termos do glossário, com fonte quando há regra legal
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

## Selo de atualização e status.html

Topo da home e faixa de cada ativo: "Atualizado · pregão de DD/MM/AAAA". Um script no
navegador compara o `data-pregao` com a hora de Brasília (depois das 19h o dia conta), pulando
fim de semana e `_src/feriados-b3.json`: verde = nenhum pregão faltando, âmbar = falta 1,
vermelho = 2 ou mais. `status.html` (noindex, fora do sitemap, link no rodapé) traz hora da
geração, selo do GitHub Actions, situação de cada ativo e próximos pregões. Para testar:
`status.html?hoje=2026-10-07` ou `?hoje=2026-10-05T20` (só vale nessa página).

## Dados abertos: indicadores, Tesouro Direto, glossário (03/10/2026)

Sem B3: só Banco Central, IBGE (via SGS) e Tesouro Nacional.

```
python _src/bcb.py       # dados/bcb.json  (falha isolada por série)
python _src/tesouro.py   # dados/tesouro.json (falha isolada)
```

| fonte | séries | licença / uso |
|---|---|---|
| BC, SGS (SOAP oficial; a API JSON api.bcb.gov.br não resolve no DNS) | 432 meta Selic, 11/1178 Selic over, 12/4389 CDI, 433/13522 IPCA, 195 poupança, 226 TR | 432, 11, 1178 e 195 estão no portal de dados abertos do BC com licença ODbL; as demais vêm do SGS público (o BC permite reprodução citando a fonte). CDI é calculado pela B3 e republicado pelo BC; o site lê só o SGS. IPCA é do IBGE. |
| BC, PTAX (API Olinda) | dólar e euro, boletim de fechamento, 2 anos | ODbL (portal de dados abertos do BC) |
| Tesouro Transparente (CKAN) | "Taxas dos Títulos Ofertados pelo Tesouro Direto", CSV desde 2002 | ODbL (conferido na API CKAN) |

**IGP-M fica de fora**: é da FGV e não está nos dados abertos do BC com licença aberta.

Páginas: `indicadores.html` (hub) e `indicadores/` (selic-hoje, cdi-hoje, ipca-acumulado-12-meses,
rendimento-da-poupanca, dolar-ptax-hoje, euro-ptax-hoje), `tesouro-direto.html` (histórico semanal de 3 anos
em `assets/tesouro/historico.json`, carregado sob demanda), `glossario.html` (uma página com âncoras: termo curto
não vira página rala). Simuladores em `_src/paginas/calculadoras/` (simulador-renda-fixa, calculadora-darf-acoes):
os valores do dia entram por placeholders `{{CDI_ANO}}`, `{{TD_TITULOS}}`… (`valores_calc` em paginas_dados.py;
placeholder desconhecido PARA o build).

Conferências por série (número inconsistente não sai, mas também não segura o resto do site):
- CDI/Selic diário × anualizado do mesmo dia ((1+d)^252);
- IPCA 12M do SGS × produto dos 12 meses;
- poupança publicada × regra da lei (0,5% + TR com meta > 8,5%; senão 70% da meta mensalizada + TR);
- meta Selic, PTAX (faixa, compra ≤ venda, salto > 15% no dia) e Tesouro (faixas de taxa e preço, ≥ 10 títulos).

**Falha isolada:** a série que falhar volta ao último dado bom, guardado em `dados/bcb-bom.json` e
`dados/tesouro-bom.json` (o build regrava esses arquivos quando a coleta passa); a página mostra o aviso
"Dado novo com problema" e a status.html marca a série como "Com problema". O build só PARA se não houver dado
bom anterior. Testado em 03/10/2026 com CDI, IPCA 12M, poupança e Tesouro adulterados.

Conferências feitas em 03/10/2026: CDI e Selic acumulados de 01/10/2025 a 01/10/2026 = 1,14474060, igual à
Calculadora do Cidadão do BC; poupança de 05/09/2025 a 05/09/2026 = 1,0827863, igual à calculadora (1,08278630);
preço do Tesouro Prefixado = 1000/(1+taxa)^(du/252), com du a partir do dia útil seguinte à data-base e feriados
nacionais, reproduz o PU de compra do arquivo (4 títulos, diferença ≤ R$ 0,01).

Regras com data (conferidas em 03/10/2026; revisar quando mudarem): tabela regressiva de IR (Lei 11.033, art. 1º);
IOF regressivo (Decreto 6.306, art. 32 e anexo; LCA alíquota zero); custódia B3 0,20% a.a., Tesouro Selic isento até
R$ 10 mil (página de tarifas da B3); LCI/LCA prazo mínimo de 6 meses (Res. CMN 5.215/2025); MP 1.303/2025 perdeu a
vigência em 08/10/2025 (ADC nº 67/2025); JCP 17,5% (LC 224/2025); dividendos > R$ 50 mil/mês (Lei 15.270/2025).
Os guias de IR são para a declaração de 2027 e precisam ser revistos quando a Receita publicar o programa e o
Perguntas e Respostas IRPF 2027 (março de 2027): códigos de Bens e Direitos estão marcados como "do programa de 2026".

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
