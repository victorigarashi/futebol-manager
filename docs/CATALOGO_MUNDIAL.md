# Catálogo Mundial do Draft: procedência e licenciamento

Data: 17/11/2026. Arquivo: `data/catalogs/world_players.json`, com 2.386 atletas de 30 ligas. Construtor: `data/importers/world_catalog_builder.py`. Testes: `data/importers/test_world_catalog.py` e `backend/app/tests/test_draft.py`.

## 1. Fontes pesquisadas para o EA SPORTS FC 26

| Fonte | O que oferece | Uso | Motivo |
|---|---|---|---|
| Site oficial de ratings da EA SPORTS FC | Overall e atributos oficiais | **Não usada** | Não há licença de redistribuição. Os ratings são trabalho editorial da EA. Extração em massa contrariaria os termos. |
| EAFC26-DataHub / dataset Kaggle "FC 26 player data" (declara CC BY 4.0) | 18.405 linhas, 110 colunas com ratings e atributos do FC 26 | **Não usada** | Quem publicou não detém os direitos sobre os ratings da EA. Uma licença CC BY declarada por terceiros não autoriza a redistribuir conteúdo da EA. O importador antigo (`eafc26_importer.py`) segue só como registro da auditoria anterior. |
| FC Mania (patch FCM) | Base com ratings | **Não usada no Mundial** | Os termos dizem uso pessoal e intransferível (ver `data/catalogs/CATALOG_SOURCES.md`). |
| dcaribou/transfermarkt-datasets | Identidade, clube, posição, nascimento, valor de mercado | **Usada só para a identidade** | Licença **CC0-1.0**. Checksums conferidos com `data/catalogs/staging/SOURCE_MANIFEST.json` (snapshot de 06/07/2026). |

**Conclusão:** não foi encontrada fonte de ratings do FC 26 que pudesse ser redistribuída legalmente. Por isso, como previsto no prompt, os ratings do catálogo Mundial são **estimativas editoriais próprias**, avisadas expressamente em cada registro (`provenance.ratings.notice`) e na interface. **Não são ratings oficiais da EA SPORTS FC.**

## 2. O que cada registro contém

| Campo | Origem | Observação |
|---|---|---|
| `name`, `nationality`, `age`, `position`, `club_name` | Transfermarkt-datasets (CC0) | `age` é calculada em 17/11/2026 a partir da data de nascimento. O clube é o do snapshot de julho de 2026 e pode ter mudado. |
| `secondary_positions` | Derivado da subposição do mesmo registro | Exemplo: volante → também DF; ponta → também MF. |
| `overall`, `potential` | **Modelo editorial `BRASILEIRAO_MANAGER_WORLD_RATING_V1`** | Fórmula na seção 3. |
| `attributes` | **Vazio** | Nada é inventado. O jogo deriva em tempo de execução um perfil transparente por posição e marca como "estimado". |
| `market_value_cents` | Valor do snapshot × 6 (conversão editorial fixa EUR→BRL) | Não é cotação de câmbio. |
| `photo_url` | **Ausente** | A licença dos dados não cobre imagem nem direito de imagem. |
| `verification_status` | `IDENTITY_SOURCE_SNAPSHOT_2026-07-06` | — |
| `source_ids.transfermarkt` | Id de origem | Para auditoria. |

O bloco `provenance` do arquivo separa:

- identidade e fonte (licença, snapshot, checksum, campos usados);
- modelo de ratings;
- itens excluídos;
- autorização de distribuição;
- status de revisão: `AUTOMATED_IMPORT_PENDING_EDITORIAL_REVIEW`.

## 3. Modelo editorial de avaliação

```
base     = 68 + 9.5 × log10(valor de mercado / €1 mi)        (€1 mi ≈ 68 · €20 mi ≈ 80 · €100 mi ≈ 87)
idade    = −1,2 por ano abaixo de 23 · +1,0 por ano acima de 30 (máx. +5)
overall  = limitar(base + idade, 55, 93)
potencial = overall + 1,5 por ano abaixo de 24 (máx. 95); sem idade conhecida, potencial = overall
```

Corte de entrada: atletas ativos em 2025/26 com valor a partir de €5 mi.

Resultado por posição:

| Posição | Atletas |
|---|---|
| GK | 123 |
| DF | 724 |
| MF | 768 |
| ST | 771 |

No Draft, o overall mínimo de 80 é viável tanto no 11×11 quanto no 5×5.

## 4. Pipeline

1. Baixar os arquivos da fonte, sob a licença dela, numa pasta própria. Exemplo: `players.csv.gz` e `clubs.csv.gz`, nas URLs do manifesto.
2. `python -m data.importers.world_catalog_builder <pasta> data/catalogs/world_players.json`. O construtor **recusa** arquivos cujo checksum não confere com o manifesto.
3. Validar: `pytest data/importers/test_world_catalog.py`. Os testes verificam:
   - ids únicos;
   - ausência de fotos e de atributos;
   - procedência CC0;
   - aviso de estimativa;
   - limites de overall e potencial.
4. O jogo carrega o arquivo localmente (`WORLD_CATALOG_PATH`, ou ao lado de `players.json`). Nenhuma partida depende de download externo.

Os snapshots brutos não fazem parte do pacote.

*Este documento registra a avaliação técnica das fontes e não constitui parecer jurídico.*
