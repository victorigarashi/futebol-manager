# Pipeline de dados de jogadores

O pipeline é offline por padrão: não faz scraping nem chamadas de rede. Os CSVs brutos usados nesta entrega ficam fora do ZIP; checksums, URLs, snapshot e licenças são registrados nos manifestos de staging.

## Regerar o staging Transfermarkt

1. Baixe, a partir das URLs do `SOURCE_MANIFEST.json`, `players.csv.gz`, `player_valuations.csv.gz`, `clubs.csv.gz` e `appearances.csv.gz`.
2. Confirme a licença e o corte do snapshot.
3. Execute na raiz do repositório:

```sh
python3 -m data.importers.catalog_builder --source-dir /caminho/para/csvs
python3 -m unittest data.importers.test_catalog_pipeline -v
```

O script grava somente em `data/catalogs/staging/` e `data/catalogs/reports/`; nunca grava `data/catalogs/players.json`.

## Fontes que exigem dados/permissão

- FC Mania: use `import_authorized_export` somente com exportação fornecida com autorização escrita referenciada. O patch tem condições de uso pessoal e individual; não redistribua seu banco.
- EAFC26: o importador identifica ratings como `EAFC26_DATAHUB_KAGGLE_CC_BY_4_0`, preserva a atribuição CC BY 4.0 e nunca os rotula como `FC_MANIA`.
- CBF: somente exportação local autorizada com referência de permissão; sem scraper.
- PlayersDB: use CSV baixado pelo link oficial se for fornecido localmente. As condições dizem que o download não transfere direitos de terceiros; não há licença para redistribuir seus dados no pacote.

## EAFC26 DataHub

O comando abaixo processa o CSV versionado no DataHub, preservando overall, potential, posições, atributos, valor em EUR e a origem `EAFC26_DATAHUB_KAGGLE_CC_BY_4_0`:

```sh
python3 -m data.importers.catalog_builder \
  --source-dir /caminho/para/transfermarkt-csvs \
  --eafc26-csv /caminho/para/players.csv \
  --historical-staging data/catalogs/staging/transfermarkt_players.json
```

O Kaggle declara CC BY 4.0 para `rovnez/fc-26-fifa-26-player-data`; preserve a atribuição no pacote e não baixe as URLs de fotos. A integração exige cruzamento de identidade. Na execução de 13/11/2026, os 18.405 registros tinham overall e potencial, mas os 280 registros da liga Série A tiveram 0 matches de alta confiança com o staging histórico; o resultado foi mantido fora de `players.json`.

## Entity resolution

O matcher só une automaticamente por ID externo coincidente. Nome completo + nascimento produz `HIGH_CONFIDENCE`; divergências de ID ou nacionalidade produzem `NEEDS_REVIEW`. Igualdade de nome sem corroborar nascimento não funde registros. Casos de nomes repetidos ficam em `DUPLICATES.csv`.

## Promoção para produção

O contrato de `backend/app/domain/catalog.py` exige ID, nome, código de clube, idade, posição, overall, potencial, valor em centavos, fonte e versão. Os dados Transfermarkt aqui não têm overall/potencial nem cobertura do Brasileirão 2026 verificada; por isso zero registros são compatíveis e a produção continua bloqueada. Não inferir ratings ou valor interno do jogo a partir do valor Transfermarkt.

## Rating próprio brasileiro

`brasileirao_rating_model.py` implementa `BRASILEIRAO_MANAGER_RATING_V1`, com fórmulas posicionais para GK/DF/MF/ST. O modelo exige minutos, aparições, regularidade e indicadores específicos; quando eles não existem, retorna pendente em vez de fabricar números. O resultado é uma estimativa interna do jogo, nunca um rating EA, FC Mania ou Transfermarkt.
