# Importação editorial do catálogo 2026

## Origem e classificação

O pacote recebeu `brasileirao_players_2026.csv`, `brasileirao_players_2026_review.csv` e sua documentação em 14/11/2026. Os ratings, potencial, atributos e valores são editoriais do projeto: `EDITORIAL_ESTIMATE`. Eles não são ratings oficiais de EA, FC Mania, SofaScore, FBref, Transfermarkt, CBF ou FootyStats.

O importador `data/importers/editorial_2026_importer.py` importa esse formato sem buscar dados na rede. Ele conserva as entradas com pendências em `data/catalogs/review/editorial_2026_needs_review.csv` e só escreve no catálogo operacional atletas com identidade, clube e posição corroborados. Idade e nacionalidade são opcionais: quando ausentes ou marcadas como assumidas, ficam `null`, sem inferência.

## Resultado da execução

- Linhas recebidas: 362.
- Atletas reais editoriais aprovados: 176.
- Registros em revisão: 186.
- Jogadores sintéticos identificados para completar elencos: 144.
- Catálogo operacional total: 320 jogadores, 16 por clube.

As 176 entradas aprovadas têm `source: EDITORIAL_ESTIMATE`; os suplementos têm `source: synthetic-career` e nome iniciado por `Genérico`. O jogo e a interface podem distingui-los por esse campo. O arquivo `editorial_2026_approved_attributes.json` mantém atributos e metadados verificáveis dos aprovados. O runtime usa overall, potencial, posição e valor interno em centavos; atributos editoriais aplicam um ajuste posicional limitado de até quatro pontos somente na simulação, sem substituir o overall de mercado ou a progressão.

## Evidência de identidade

Cada jogador aprovado exigiu nome normalizado único, clube atual coincidente no arquivo 2026 do wiUl e no `players.json` do BRASIM26 e posição macro compatível. A evidência mínima, incluindo o `player_id` do wiUl, está em `data/catalogs/review/editorial_2026_validation_evidence.json`. Ela corrobora identidade e vínculo para uso no jogo, mas não licencia nem transfere ratings de terceiros: os ratings publicados continuam editoriais do CSV fornecido. Isso não equivale a confirmação oficial de registro pela CBF.

O restante não foi descartado. A causa é evidência insuficiente de identidade, clube ou posição entre as fontes cruzadas; idade ausente isoladamente não bloqueia a promoção. Nenhuma idade ou nacionalidade foi inferida. Nacionalidades marcadas como assumidas permanecem `null`.

## Modos e elencos

`EDITORIAL_2026_COVERAGE.csv` confirma para os 20 clubes pelo menos 2 GK, 4 DF, 3 MF e 3 ST, com 16 atletas por clube. Isso oferece o mínimo de 8 atletas no 5x5 e 16 no 11x11, preservando as vagas posicionais. O preenchimento ocorre antes do mercado, por isso a validação de viabilidade e os bots conseguem concluir elenco; nenhum sintético é apresentado como jogador real.

## Reprodução

```sh
python3 -m data.importers.editorial_2026_importer \
  --players /caminho/brasileirao_players_2026.csv \
  --review /caminho/brasileirao_players_2026_review.csv \
  --evidence data/catalogs/review/editorial_2026_validation_evidence.json \
  --output-dir data/catalogs
```

O `market_value_eur` recebido é explicitamente valor interno editorial, não cotação externa. O importador o converte para centavos internos usando fator fixo 5,50; não consulta preço de mercado.
