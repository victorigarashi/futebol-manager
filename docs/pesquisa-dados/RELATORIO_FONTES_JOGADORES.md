# Dados de jogadores: fontes, cobertura, direitos de uso e integração possível

Data: 15/11/2026. Fase 6 da refatoração de partidas.

**Escopo:** só pesquisa. Nenhum arquivo do catálogo (`data/catalogs/*`, `data/importers/*`) foi alterado, para não conflitar com a investigação paralela do Codex (pacote `brasileirao-pesquisa-dados-2026`, com coleta via API Ninjas e auditoria CBF). Não houve scraping em massa, nem contorno de autenticação, nem coleta de fotos ou escudos.

Este relatório complementa o que já está no repositório:

- `data/catalogs/CATALOG_SOURCES.md`;
- `data/catalogs/reports/SOURCE_EVALUATION.md`;
- `data/catalogs/reports/FCMANIA_AUTHORIZATION_REQUEST.md`;
- os relatórios EAFC26 em `data/catalogs/reports/`.

## 1. Situação atual do catálogo

- **Composição:** 320 atletas operacionais, sendo 176 reais com rating `EDITORIAL_ESTIMATE` e 144 suplementos `synthetic-career`, necessários para completar os elencos (por exemplo, goleiros genéricos).
- **Campos por atleta:** `id`, `name`, `club_code`, `position`, `secondary_positions`, `age`, `nationality`, `overall`, `potential`, `attributes`, `market_value_cents`, `source`, `source_version` e `verification_status`.
- **O que já existe:** a separação entre dados factuais e atributos de jogo, e IDs estáveis.
- **O que falta:**
  - verificação de vínculo com o clube em novembro de 2026;
  - datas de nascimento confirmadas;
  - nacionalidade confirmada (hoje há casos em que "Brazil" foi assumido por padrão);
  - substituição dos sintéticos por atletas reais.

## 2. Fontes avaliadas

| Fonte | O que oferece | Direito de uso | Decisão |
|---|---|---|---|
| **FC Mania Database** ([patchfcm.fcmania.com.br](https://patchfcm.fcmania.com.br/)) | FCM 26 V5: ~25 mil jogadores, overall, potencial, posições e atributos, com ligas brasileiras. | Os termos do patch preveem uso pessoal, individual e intransferível. Não há exportação nem API autorizada. | **Só referência.** Já existe um pedido formal de autorização e um importador pronto para um arquivo fornecido com autorização escrita. Sem isso, nada é importado. |
| **FIFACM** ([fifacm.com/players](https://www.fifacm.com/players)) | Banco do modo carreira: overall, potencial, atributos, crescimento, valores. | O site devolveu **HTTP 403** ao acesso automatizado (sinal claro de que não aceita coleta automática). Não encontramos termos que autorizem reuso. | **Não usar.** Serve no máximo para consulta manual de referência. Nada copiado. |
| **EA SPORTS FC Ratings** ([ea.com](https://www.ea.com/games/ea-sports-fc/ratings)) | Tabela pública com OVR e os seis atributos principais (PAC, SHO, PAS, DRI, DEF, PHY), além de PlayStyles. | O [Acordo de Usuário da EA](https://www.ea.com/legal/user-agreement) proíbe copiar, distribuir ou extrair dados dos serviços sem autorização e limita o uso ao não comercial. O conteúdo é da EA ou de licenciadores. | **Só como modelo conceitual** (estrutura de 6 atributos + goleiro, que o jogo já segue). Nenhum valor pode ser apresentado como "rating oficial EA". |
| **FC Career Manager** ([fccareermanager.app/fc26](https://fccareermanager.app/fc26)) | Overall, potencial, atributos, PlayStyles, valores, contratos e status de empréstimo, vindos do squad file do FC 26 (build de 26/07/2026). | Os [termos](https://fccareermanager.app/terms) dizem: *"Don't reverse-engineer, scrape, or resell the App's data"*, com licença pessoal e não comercial. Não há afiliação com a EA. | **Não usar** para importação. Mostra quais campos um modo carreira costuma ter (crescimento, contrato, empréstimo). |
| **Kaggle EAFC 26** (via EAFC26-DataHub) | 18.405 jogadores com overall, potencial, posições e atributos. | Licença declarada CC BY 4.0, mas os direitos de fundo (EA/SoFIFA) não são resolvidos pela licença do dataset. | **Já está em staging** com atribuição. Dos 280 registros da Série A, nenhum foi verificado (184 com identidade inválida, 96 com clube desatualizado). Não serve como elenco 2026. |
| **Wikidata** ([wikidata.org](https://www.wikidata.org/)) | Identidade factual: nome, data de nascimento (P569), nacionalidade (P27), posição (P413), clube com data de início e fim (P54 + P580/P582), IDs externos (Transfermarkt, ogol etc.). | **CC0**: livre para armazenar, transformar e redistribuir, inclusive comercialmente. Não fornece ratings. | **Fonte recomendada para identidade.** Ver §3. |
| **Transfermarkt datasets** (dcaribou, CC0) | Perfis, valores históricos e aparições. | CC0, mas o snapshot vai só até 07/2026. | Já em staging, como enriquecimento histórico. |
| **API Ninjas / API-Football / FootyStats / Reep** | Elencos atuais, camisa, data de nascimento e IDs cruzados. | Variável: a API Ninjas não permite uso comercial no plano gratuito. O Reep tem crosswalk em CC0. | **Escopo do Codex.** Não duplicado aqui. |
| **CBF (inscrições Série A 2026)** | Lista oficial de inscritos (876 registros históricos). | Os termos vedam reprodução sem autorização. | Só para conferência manual de vínculo. |

## 3. Wikidata: o que foi medido

- **Ferramenta:** `docs/pesquisa-dados/wikidata_coverage.py`, só de leitura. Conta, por clube, os jogadores com vínculo P54 em aberto (sem data de fim) e quantos deles têm data de nascimento, nacionalidade, posição e data de início a partir de 2018.
- **O que rodou em 15/11/2026:**
  - a busca dos identificadores dos 20 clubes funcionou;
  - a consulta de contagem foi recusada pelo próprio serviço com *"Aggressively rate-limiting to 1 req/min — rule created during active WDQS outage"*. Respeitamos o limite e não houve novas tentativas automáticas.
- **Número de cobertura:** não temos ainda. Fica pendente para uma execução fora da instabilidade.
- **Riscos conhecidos do Wikidata para elencos atuais:**
  - vínculos antigos sem data de fim (jogador "ainda" no clube anterior);
  - transferências da janela de 2026 registradas com atraso;
  - homônimos.

  Por isso ele deve ser usado para **identidade** (data de nascimento, nacionalidade, posição, IDs externos), e não como prova de vínculo atual, que precisa da CBF ou de uma API licenciada.

## 4. Modelo de atributos proposto (editorial, documentado)

Atributos de gameplay continuam sendo um **modelo editorial próprio**, rotulado `EDITORIAL_ESTIMATE` e nunca apresentado como rating oficial. O motor já consome estes campos (`derived_attributes`):

| Campo | Origem permitida |
|---|---|
| Nome, nome esportivo, data de nascimento/idade, nacionalidade, posição principal e secundárias | Wikidata (CC0), conferido com CBF ou API licenciada |
| Clube atual | CBF (conferência manual) ou API com licença de armazenamento |
| Overall, potencial | Modelo editorial (`data/catalogs/reports/BRASILEIRAO_MANAGER_RATING_V1.md`) |
| Velocidade, finalização, passe, drible, defesa, físico, atributos de goleiro | Modelo editorial derivado de posição, idade e overall, com ajustes manuais documentados |
| Valor de mercado do jogo | Função interna (`data/importers/game_pricing.py`), nunca uma "cotação real" |
| Evolução | `app/domain/progression.py` (já aplicada entre temporadas) |

## 5. Plano de integração possível (sem tocar no catálogo agora)

1. **Identidade (CC0).** Quando o serviço do Wikidata normalizar, rodar a medição e gerar `wikidata_candidates.csv` em `data/catalogs/staging/`. Isso deve ser feito pela pessoa que cuida do catálogo (o Codex), com:
   - QID como ID externo estável;
   - campos factuais;
   - `verification_status = NEEDS_REVIEW`.
2. **Conciliação.** Casar primeiro pelo ID externo (QID ↔ Transfermarkt ID ↔ Reep) e só depois por nome e data. Homônimos ficam como `review_required`.
3. **Vínculo atual.** Conferir na CBF ou na API licenciada escolhida pelo Codex. Nunca promover um vínculo sem essa conferência.
4. **Atributos.** Aplicar o modelo editorial aos atletas aprovados. Os IDs do jogo são preservados (um novo atleta recebe um novo ID, sem reaproveitar o de um sintético).
5. **Sintéticos.** Um `synthetic-career` só é removido quando o clube tiver um substituto real verificado na mesma posição. O histórico de transferências da sala é preservado (as salas guardam o elenco no snapshot).
6. **FC Mania.** Se a autorização escrita chegar, o importador existente lê o arquivo, que fica em staging até a revisão.

**O que não pode ser feito:** copiar ratings da EA, do FIFACM, do FC Career Manager ou do FC Mania sem autorização. "Público" não significa "licenciado".

Este documento é uma avaliação técnica, não um parecer jurídico.
