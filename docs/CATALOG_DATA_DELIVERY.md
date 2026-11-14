# Entrega parcial: catálogo de jogadores

Data da revisão: 13/11/2026. Esta entrega não declara o catálogo real de produção concluído.

## Resultado mensurável

O dataset publicado pelo projeto [dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets), sob CC0-1.0, foi processado localmente. O repositório upstream informa snapshot até 06/07/2026, valores até 12/06/2026 e cobertura de plantéis até 2025, sem squads 2026/27.

- 1.192 perfis associados pelo dataset à competição brasileira BRA1.
- 706 perfis têm alguma avaliação financeira histórica até 12/06/2026; valores e datas originais foram mantidos em EUR.
- 0 têm overall confirmado nesta fonte.
- 0 têm potencial confirmado nesta fonte.
- 0 têm conjunto completo dos atributos exigidos.
- 0 têm licença de redistribuição de foto ou escudo.
- 0 tiveram vínculo atual aos clubes da Série A 2026 verificado pela CBF.
- O CSV de aparições disponível não contém BRA1; logo não permite afirmar participação/minutos dos atletas no Brasileirão.
- 0 registros satisfazem o contrato de catálogo operacional do backend.

Os registros ficam em `data/catalogs/staging/transfermarkt_players.json`. O catálogo operacional `data/catalogs/players.json` não foi gerado nem alterado. Os nomes e ratings não são chamados de FC Mania nem EA FC. A avaliação Transfermarkt de junho é histórica, não atual em novembro.

## EAFC26 DataHub

O CSV versionado no [EAFC26 DataHub](https://github.com/ismailoksuz/EAFC26-DataHub) foi processado; a fonte original [Kaggle](https://www.kaggle.com/datasets/rovnez/fc-26-fifa-26-player-data) declara CC BY 4.0. O importador preserva 18.405 ratings, potenciais, posições, atributos e valores internos em `data/catalogs/staging/eafc26_players.json`, com atribuição e sem fotos.

Os números são: 18.405 overall, 18.405 potenciais, 18.405 com ambos; 280 registros Série A; 5 matches históricos de alta confiança no universo completo e 0 dentro da Série A. Logo, os ratings são reais da fonte EAFC/Kaggle, mas não há base suficiente para afirmar que os 280 registros representam corretamente os atletas dos vinte clubes da Série A 2026. Nenhum foi integrado ao catálogo operacional.

Os valores `value_eur` do EAFC são mantidos como valor interno do jogo e não são apresentados como cotação Transfermarkt. O relatório completo está em `data/catalogs/reports/EAFC_TOTAL_REPORT.md`.

## Arquivos e execução

- `data/importers/`: importadores separados, entity matcher, builder, validação e testes.
- `data/catalogs/staging/SOURCE_MANIFEST.json`: corte, fonte, URLs e SHA-256 dos quatro arquivos usados.
- `data/catalogs/staging/transfermarkt_bra1_clubs.csv`: clubes da competição presentes no snapshot, com última temporada do arquivo.
- `data/catalogs/reports/`: cobertura por clube/posição, campos ausentes, ambiguidades, conflitos, licenças, assets e liberação por temporada.
- `data/catalogs/CATALOG_SOURCES.md`: avaliação das fontes consultadas.

Para regerar, consulte `data/importers/README.md`. Testes do pipeline: `python3 -m unittest data.importers.test_catalog_pipeline -v`.

## Lacunas para completar catálogo real

1. Autorização/export oficial do FC Mania ou licença explícita de uma base que permita uso/redistribuição de ratings e atributos.
2. Export autorizado/licenciado de escalações/inscritos e dados esportivos da Série A 2026 para validar clube, uso, titulares e reservas.
3. CSV PlayersDB fornecido para cruzamento de IDs; seus termos não transferem direitos sobre os dados de terceiros.
4. Para o EAFC26, a licença CC BY 4.0 já foi identificada e a atribuição foi incluída; ainda faltam identidade e vínculo atual confiáveis para promover jogadores brasileiros ao catálogo operacional.
5. Licenças de fotos/escudos; nenhuma imagem foi baixada ou empacotada.
6. Fontes autorizadas para dados completos de temporadas 2 e 3, sem duplicidade nem confusão de temporada de liberação.

O código do jogo não foi mudado além de documentação e pipeline de dados. Nenhum banco de dados, scraping, jogador sintético ou rating inventado foi adicionado ao catálogo real.

## Classificação brasileira independente (13/11/2026)

O relatório operacional não rejeita um atleta EAFC por ausência nos históricos. Para os 280 registros com `league_name=Série A`, a classificação atual é:

| Status | Quantidade | Regra |
|---|---:|---|
| VERIFIED | 0 | identidade e clube atual confirmados por exportação oficial autorizada |
| NEEDS_REVIEW | 0 | evidência parcial ou divergência a revisar |
| STALE_CLUB | 96 | rating/identidade estruturalmente válidos, porém clube da fonte é histórico |
| INVALID_IDENTITY | 184 | data sentinela ou identidade estrutural inválida |
| LICENSE_BLOCKED | 0 | licença insuficiente para redistribuição |

O arquivo completo por atleta é `data/catalogs/reports/EAFC_BRAZIL_CANDIDATES.csv`. A referência oficial CBF consultada lista atletas e clubes de 2026, mas seus termos de uso restringem cópia e reprodução sem autorização; por isso não foi transformada em catálogo local nem usada para promover jogadores automaticamente. Sem um export autorizado com `source_player_id` e `current_club_name`, `VERIFIED` permanece zero.
