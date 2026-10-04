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
  carteiras.py      monta ativos.json pelas carteiras do Ibovespa/IFIX e pelo volume (ver "A lista de ativos")
  ativos.json       A LISTA de ativos (código, tipo acao/fii/bdr, nome curto, CNPJ ou dados do BDR, índices)
  carteiras.json    data, fonte e critério de cada grupo da lista (escrito por carteiras.py)
  eventos.json      desdobramentos/grupamentos e variações >25% conferidas, com fonte (ver "Variação anormal")
  eventos_b3.py     procura na B3 o evento de cada variação >25% ainda não declarada
  excecoes-b3.json  linhas do COTAHIST com preço médio fora da faixa do dia, declaradas uma a uma
  paises.json       país da empresa de cada BDR (Wikidata), para a bandeira do selo; ações e FIIs = Brasil
  comunicados.py    comunicados da CVM (IPE e documentos de FIIs) -> dados/comunicados.json
  noticias.py       manchetes de fontes oficiais -> dados/noticias.json
  fundamentos.py    balanços (DFP/ITR) e informes de FII da CVM -> dados/fundamentos.json (semanal)
  ativo.js          JS das páginas de ativo (gráficos, comparação, simulador, tabelas), copiado para assets/
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
  cadastro.json          cadastro da CVM (e "sem_cadastro": ativos sem cadastro achado)
  comunicados.json       10 últimos por empresa/fundo + recentes gerais, e a situação de cada fonte
  noticias.json          até 12 manchetes por fonte, e a situação de cada fonte
  historico/<CODIGO>.csv série longa 2021–2024, só data e fechamento (para o gráfico de 5 anos)
  fundamentos.json       lucro, receita, PL, proventos (DMPL) e ações por companhia; rendimentos mensais de FII
  bcb.json               séries do SGS (Selic, CDI, IPCA, poupança, TR) e PTAX; bcb-bom.json = último dado bom
  tesouro.json           taxas e preços do Tesouro Direto; tesouro-bom.json = último dado bom
assets/serie/<ativo>.json   série de fechamentos que a página carrega sob demanda (+ _ref.json: ETFs, CDI, IPCA, lista)
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

Filtro: mercado à vista (TPMERC 010), lote padrão (CODBDI 02), fundo
imobiliário (CODBDI 12) ou BDR (CODBDI 34 e 35). "Fechamento" é o PREULT (último negócio).

**BDR não está no PDF.** A revisão 02 do layout não lista os BDI de BDR nem as
especificações DRN/DR1/DR2/DR3. Nos arquivos reais (conferido em 03/10/2026):
BDI 34 = BDR não patrocinado (DRN), 35 = patrocinado nível I/II/III (DR1/DR2/DR3),
36 = BDR de ETF (DRE, fora do site). O leitor confere BDI, especificação e ISIN
(`BRxxxxBDRnnn`) juntos e para se uma linha de BDR acompanhada vier diferente.

**Preço médio fora da faixa do dia.** Acontece de verdade no COTAHIST (12 linhas
em 2025–2026 nos 245 ativos, várias em dia de vencimento de opções): o PREMED é
volume ÷ quantidade e às vezes inclui negócio que não entrou na mínima/máxima.
O leitor continua parando; cada caso conferido vai em `_src/excecoes-b3.json`
(papel, dia e a conta). Só a regra do preço médio é dispensada ali — abertura e
fechamento continuam presos à faixa e o volume continua tendo de bater.

### Cadastro — CVM

```
python _src/cvm.py            # baixa e grava dados/cadastro.json
python _src/cvm.py --se-velho # só se ainda não rodou neste mês, a partir do dia 16
```

Companhias: `cad_cia_aberta.csv`. Fundos imobiliários: informe mensal
(`inf_mensal_fii_AAAA.zip`, arquivos geral e complemento). Casa pelo CNPJ de
`ativos.json`; para se o ISIN da CVM divergir do da B3, ou se um ativo que tinha
cadastro deixar de ter. Ativo sem cadastro achado vai para `sem_cadastro` e a
página dele sai com texto mínimo (código, nome de pregão, ISIN), sem inventar.
Em 03/10/2026 são 11 FIIs do IFIX cujo ISIN não aparece igual no informe da CVM
(campo vazio ou truncado lá): FATN11 BTCI11 BTHF11 CPSH11 GZIT11 KNUQ11 MCRE11
PCIP11 PMLL11 PSEC11 TVRI11. O CNPJ não é adivinhado pelo nome.

### A lista de ativos

`python _src/carteiras.py` (mostra) / `--gravar` (grava `ativos.json` e `carteiras.json`).

- Ações: carteira do dia do Ibovespa (B3, `indexProxy/indexCall/GetPortfolioDay`,
  índice IBOV) + ações/units fora do índice entre as 100 de maior volume no ano
  (COTAHIST), ON/PN/UNT, negociadas em todos os pregões do ano. CNPJ pelo código
  no FCA da CVM (valor mobiliário); reserva: cadastro de empresas listadas da B3.
- FIIs: carteira do dia do IFIX (B3). CNPJ pelo ISIN da B3 = ISIN do informe da CVM.
- BDRs: os 50 de maior volume no ano no COTAHIST (BDI 34 e 35). Nome da empresa
  e tipo do programa pela B3 (`GetCompaniesBDR`). A bolsa de origem não vem em
  nenhum desses dados, e o site não a cita.

Em 03/10/2026 (carteiras de 05/10/2026): 96 ações (76 do Ibovespa + 20),
99 FIIs do IFIX, 50 BDRs. As carteiras mudam em janeiro, maio e setembro: rode
`carteiras.py --gravar`, depois `atualiza.py historico 2025 2026`, `cvm.py`,
`comunicados.py` e `build.py`. Nome curto ruim: corrija em `NOMES`, no
`carteiras.py` (o `ativos.json` é regravado).

### Variação anormal

O build para se um ativo variar mais de 25% num pregão. `python _src/eventos_b3.py`
procura na B3 (eventos corporativos do emissor: desdobramento, grupamento,
bonificação, cisão, proventos) um evento cujo fator explique a variação, e com
`--gravar` acrescenta em `_src/eventos.json` só o que bateu, com o link da fonte:

```json
{"PETR4": {"2027-04-15": {"evento": "Desdobramento de 1 para 2, …", "fonte": "https://…", "fonte_nome": "B3, …"}}}
```

A página mostra o aviso e não exibe a variação daquele dia. O que a B3 não
explica fica parado até alguém conferir. Variação real de mercado (resultado,
notícia) também é declarada, com `"tipo": "mercado"` e a fonte que a confirma
(documento da CVM, ou a série da B3 com o preço mantido nos dias seguintes): a
variação continua exibida, e a página lista o caso em "Eventos e variações fora
do comum". Em 03/10/2026: 18 eventos da B3 e 14 variações de mercado conferidas.

## Adicionar um ativo

O caminho normal é o `carteiras.py` (acima). À mão, só como exceção:

1. Acrescente em `_src/ativos.json` (código, `acao`/`fii`/`bdr`, nome curto, CNPJ).
2. `python _src/atualiza.py historico 2025 2026` (os anuais ficam em `_tmp/`).
3. `python _src/eventos_b3.py --gravar` se o build parar numa variação >25%.
4. `python _src/cvm.py` e `python _src/comunicados.py`
5. `python _src/build.py`

## Comunicados

`python _src/comunicados.py`. Fontes (dados abertos da CVM):

- Companhias: documentos IPE (`CIA_ABERTA/DOC/IPE`), categorias Fato Relevante,
  Comunicado ao Mercado e Aviso aos Acionistas, casadas pelo CNPJ (e pelo código
  CVM dos BDRs patrocinados). Link: o documento no RAD da CVM. **A CVM atualiza
  esse arquivo em lotes** (em 03/10/2026, o arquivo era de 27/09, com documentos
  até 25/09): a data aparece na página e na status.html.
- FIIs: documentos eventuais de fundos (`FI/DOC/EVENTUAL`, atualizado todo dia),
  tipos Fato Relevante, Aviso ao Mercado e Relatório Gerencial, pelo CNPJ.
  Link: o arquivo no Fundos.NET (B3). Não há campo de assunto: aparece o tipo.

## Notícias

`python _src/noticias.py`. **Só título, data e link**, com o nome da fonte; nada
de resumo. Licenças conferidas em 03/10/2026:

| fonte | como é lida | o que a fonte diz | uso aqui |
|---|---|---|---|
| Agência Brasil (EBC) | RSS de Economia | "Reprodução autorizada para veículos de comunicação com fins jornalísticos, mediante indicação da fonte"; fins comerciais pedem licença (licenciamento@ebc.com.br); rodapé "© Todos os direitos reservados". **Não declara CC BY 4.0 hoje.** | título + link |
| Banco Central | feeds Atom "notasImprensa" e "comunicadoscopom" | sem licença aberta declarada no site | título + link |
| B3 | página b3.com.br/pt_br/noticias/ (HTML) | direitos reservados | título + link |
| Tesouro Nacional | API do portal gov.br (`++api++ … @search`) | sem licença aberta conferida para as notícias | título + link |

Nenhum veículo privado. Manchete ou assunto de comunicado com linguagem de
recomendação é descartado ao montar a página (a trava do build continua valendo
para a página inteira).

**Falha isolada:** `comunicados.py` e `noticias.py` nunca param a rotina. Se uma
fonte falhar, fica a última coleta boa dela, o erro é gravado no JSON e a
status.html mostra a fonte como "Falhou"; no workflow os dois passos ainda têm
`continue-on-error`.

## Série longa (5 anos)

`python _src/atualiza.py longo 2021 2022 2023 2024` lê os COTAHIST anuais e grava
`dados/historico/` (3,5 MB para 245 ativos + 5 ETFs). Mesmo porteiro do leitor; só
entra a linha cujo ISIN é o de hoje (código reaproveitado por outro papel fica de
fora). Na parte antiga a trava de 25% não para o build: a série passa a começar
depois da última variação >25% sem evento declarado (18 ativos em 03/10/2026, quase
todos BDRs pouco líquidos), e a página diz isso. Em 2025 em diante a trava continua
parando a publicação.

## Indicadores (cartões, dividendos, setor)

Tudo de `dados/fundamentos.json` (CVM) e do COTAHIST; fórmulas no "?" de cada cartão:

- P/L = preço ÷ (lucro líquido 12M atribuído aos controladores ÷ ações); prejuízo → "n/a".
- P/VP = preço ÷ (PL dos controladores ÷ ações). FII: preço ÷ valor patrimonial da cota do informe.
- DY (ação) = proventos declarados em 12M na DMPL ÷ ações ÷ preço. DY (FII) = soma de 12
  meses de (DY do mês × VP da cota) do informe mensal ÷ preço.
- 12 meses = DFP do último exercício + acumulado do ano no último ITR − mesmo acumulado do ano anterior.
- Ações = composição do capital (CVM) − tesouraria, conferida contra o total da B3 (×1 ou ×1000);
  não conferiu → "—". Units: × número de ações da unit pelo FCA (CVM).
- Variação 12M: preço bruto, sem proventos, com desdobramentos/grupamentos descontados
  (`fator_preco` em eventos.json). Liquidez: média do volume dos últimos 30 pregões.
- ROE = lucro 12M ÷ PL; margem = lucro 12M ÷ receita de venda 12M (bancos/seguradoras: "—").
- Setor da comparação: setor de atividade da CVM; "Emp. Adm. Part. - X" junta com X.
  FIIs não têm comparação por segmento (o segmento do informe foi descartado por não ser confiável).

A DMPL de alguns bancos vem com valores em colunas trocadas nos dados abertos: nesses
casos o provento fica "—" (BBAS3, BBDC3, BBDC4, SANB11, BRSR6, COGN3 em 03/10/2026).

## Comparação com índices

ETFs da B3 no lugar dos índices (BOVA11, SMAL11, XFIX11, DIVO11, IVVB11), do COTAHIST
(BDI 14, conferido no leitor); CDI acumulado com a convenção da calculadora do BC
(taxa do dia d rende de d ao dia útil seguinte; conferido: 01/10/2025 a 01/10/2026 =
1,14474060 nos dois). A API JSON do SGS (api.bcb.gov.br) não resolve mais no DNS:
`bcb.py` usa o serviço SOAP oficial do SGS (www3.bcb.gov.br/wssgs).

## Gráfico

Desenhado no navegador a partir da série de fechamentos que vai em cada página
(`<script type="application/json" id="serie">`, desde 02/01/2025, só cresce no
fim). Antes eram três SVGs gerados pelo build, que mudavam por inteiro a cada
pregão: com 245 páginas, o repositório cresceria centenas de MB por ano. Sem
JavaScript, a página mostra o resumo de 12 meses e a tabela.

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
geração, selo do GitHub Actions, última coleta de cada fonte de comunicados e notícias
(com o erro, se houver), balanços da CVM, séries do Banco Central e Tesouro Direto,
situação de cada ativo e próximos pregões. Para testar:
`status.html?hoje=2026-10-07` ou `?hoje=2026-10-05T20` (só vale nessa página).

## Termos de uso da B3 (decisão pendente do dono)

Os termos de uso do site da B3 dizem que o conteúdo é para uso pessoal e que reprodução
ou uso comercial dependem de autorização prévia e por escrito; a política de difusão de
dados de mercado também restringe redistribuição. Não há exceção escrita para o COTAHIST.
O site já usa o COTAHIST desde o início (decisão anterior); o que foi feito agora segue a
mesma linha, mas: proventos por evento (data com, pagamento) **não** vêm da B3 — só de
dados abertos da CVM; a B3 é usada para carteira dos índices, nome dos BDRs, fator de
desdobramento/grupamento e conferência do número de ações. Ver o relatório da etapa.

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

Ele roda às 19h30 e à 1h30 (Brasília) em dia útil, baixa o que faltar, coleta
comunicados, notícias, balanços, Banco Central e Tesouro (falha isolada), roda o build e faz commit e push só se algo mudou. Falha = nada é commitado, e o
GitHub avisa por e-mail.

## AdSense

`ADSENSE_LIGADO` em `_src/build.py`. Publisher `ca-pub-4401770243539507`, o
mesmo dos outros sites; `ads.txt` gerado pelo build. A faixa de consentimento
injeta o script e sai da frente quando a mensagem do Google (`__tcfapi`) diz
que o GDPR se aplica. O site ainda precisa ser **adicionado e aprovado** no
painel do AdSense.
