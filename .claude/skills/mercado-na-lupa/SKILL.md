---
name: mercado-na-lupa
description: Como trabalhar no site Mercado na Lupa (mercadonalupa.com.br), site estático em Python de dados públicos do mercado brasileiro. Use ao criar ou editar qualquer página (guia, calculadora, ativo, indicador, Tesouro Direto, glossário), mexer no CSS, adicionar ativo, atualizar dados da B3/CVM/BC/Tesouro, rodar o build ou publicar.
---

# Mercado na Lupa

Site estático de dados públicos sobre o mercado brasileiro. Gerado por `_src/build.py`,
publicado na Hostinger por push no GitHub (branch principal = produção). Detalhes completos
no `README.md` da raiz; esta skill é o resumo operacional.

## Regras que mandam em tudo

1. **Educativo, nunca recomendação.** Nada de "compre/venda", carteira sugerida, preço-alvo,
   nota ou "vale a pena investir". O build tem a trava `RECOMENDACAO` (regex em
   `_src/build.py`) que PARA a publicação se esse tipo de texto aparecer. Não contorne a
   trava: reescreva o texto.
2. **Nunca edite os `.html` da raiz** (`index.html`, `ativos/`, `guias/`, `calculadoras/`,
   `indicadores/` etc.). Eles são gerados. Edite em `_src/` e rode o build.
3. **Número só de fonte aberta e conferida.** Dado inconsistente não sai. Não invente número,
   código de declaração, alíquota ou data; cite a lei/norma e a data em que foi conferida.
4. **Só fontes com licença que permite reuso.** IGP-M (FGV) fica de fora. Fotos: só PD, CC0,
   CC BY, CC BY-SA (nunca NC).
5. Commit e push só quando o Allan pedir. Push na principal publica o site.

## Onde fica cada coisa

| Quero mexer em… | Arquivo |
|---|---|
| Geração do site, travas, AdSense (`ADSENSE_LIGADO`) | `_src/build.py` |
| Páginas de indicadores, Tesouro Direto, glossário, placeholders das calculadoras | `_src/paginas_dados.py` |
| Estilos (vão inline no `<head>`) | `_src/site.css` |
| Um guia | `_src/paginas/guias/<slug>.html` |
| Uma calculadora/simulador | `_src/paginas/calculadoras/<slug>.html` (com `<script>` no fim) |
| Lista de ativos acompanhados | `_src/ativos.json` (código, `acao`/`fii`, nome curto, CNPJ) |
| Desdobramento/grupamento | `_src/eventos.json` |
| Feriados sem pregão | `_src/feriados-b3.json` (2027 provisório até a B3 publicar) |
| Termos do glossário | `_src/glossario.json` |
| Fotos de fundo e créditos | `_src/fundos.json` + `python _src/fundos.py` |
| Dados gerados | `dados/` (cotações, `bcb.json`, `tesouro.json`, `*-bom.json`, cadastro) |

## Guias e calculadoras: front matter

Cada arquivo começa com um comentário JSON:

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
- `<h2>` com `id` para as âncoras; os links internos e âncoras são conferidos pelo build.
- Valores do dia nas calculadoras entram por placeholders (`{{CDI_ANO}}`, `{{TD_TITULOS}}`…)
  definidos em `valores_calc` em `paginas_dados.py`. Placeholder desconhecido PARA o build.
- Siga o tom dos guias existentes: frases diretas, português correto, sem jargão sem explicar.

## Travas do build (se parar, corrija a causa)

- título ≤ 60 caracteres e único; descrição entre 120 e 155 e única;
- JSON-LD, canonical, `max-image-preview:large` em toda página; 404 com `noindex`;
- links internos e âncoras válidos; guia sem fontes; trava de linguagem de recomendação;
- variação de ativo > 25% num pregão sem evento declarado em `eventos.json`;
- layout da B3 fora do padrão (o `b3.py` para e não grava nada);
- placeholder desconhecido em calculadora;
- série do BC/Tesouro com problema e **sem** dado bom anterior (com dado bom, a série volta
  ao último dado bom e a página mostra "Dado novo com problema").

## Comandos

Python 3.12+ e Pillow. Temporários sempre em `_tmp/` (o Python da Microsoft Store não
enxerga `AppData\Local`).

```
python _src/build.py                          # gera o site
python -m http.server 8765                    # ver em http://localhost:8765/
python _src/atualiza.py diario                # pregões da B3 que faltam
python _src/atualiza.py historico 2025 2026   # carga pelos arquivos anuais
python _src/cvm.py                            # cadastro da CVM
python _src/bcb.py                            # indicadores do BC (falha isolada por série)
python _src/tesouro.py                        # taxas do Tesouro Direto
```

Para testar o selo de atualização: `status.html?hoje=2026-10-07` ou `?hoje=2026-10-05T20`.

## Receitas

**Adicionar um ativo:** acrescentar em `_src/ativos.json` → `python _src/atualiza.py historico 2025 2026`
→ `python _src/cvm.py` → `python _src/build.py`.

**Novo guia ou calculadora:** criar o arquivo em `_src/paginas/...` com o front matter →
`python _src/build.py` → abrir no servidor local e conferir a página e o link no hub
(`guias.html` / `calculadoras.html`).

**Mudança visual:** editar `_src/site.css` (ou o HTML gerado em `build.py`) → build → conferir
no navegador em largura de celular e de desktop.

**Sempre, ao terminar:** rodar `python _src/build.py` e só dar como pronto se ele passar sem
erro; abrir a página afetada no servidor local.

## Datas que pedem revisão

- Guias de IR são da declaração de 2027 e usam códigos do programa de 2026: revisar quando a
  Receita publicar o programa e o Perguntas e Respostas IRPF 2027 (≈ março de 2027).
- `feriados-b3.json`: trocar 2027 provisório pelo calendário oficial quando a B3 publicar.
- Regras com data no README (tabela de IR, IOF, custódia B3, LCI/LCA, JCP 17,5%, dividendos
  > R$ 50 mil/mês) foram conferidas em 03/10/2026.

## Pendências conhecidas

- Rotina diária `.github/workflows/atualiza.yml` só vale depois que o repositório existir no
  GitHub e as permissões de Actions estiverem em "Read and write".
- O site ainda precisa ser adicionado e aprovado no painel do AdSense
  (publisher `ca-pub-4401770243539507`).
