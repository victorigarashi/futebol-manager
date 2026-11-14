# Estado de recuperação e continuação

Este arquivo foi reconstruído depois da exclusão da documentação original. O backend foi recuperado do ZIP local; o frontend foi recuperado de uma imagem Docker local construída anteriormente. A configuração Docker Compose e o acesso à prancheta durante a temporada foram reconstruídos com base no histórico da sessão. O histórico Git e os documentos originais docs/01 a docs/08 não foram recuperados.

## Situação do projeto

- Backend FastAPI, frontend React/Vite, WebSocket, mercado inicial com seleção e multas, elencos, calendário, simulador, replay, transferências, playoffs e carreiras estão presentes.
- O modo demonstração é opcional, identificado e usa dados sintéticos; ative com `APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build`.
- O catálogo de jogadores reais autorizados está ausente. Não inventar dados reais. Não adicionar banco de dados.
- Continuam pendentes o prazo e avanço automático das rodadas, um E2E único com dois humanos cobrindo toda a carreira e a revisão visual completa. A beta ainda não foi validada de ponta a ponta.
- Na cópia recuperada, 53 testes backend passaram em Python 3.14 fora do sandbox; lint, teste e build do frontend passaram na imagem Docker usando o código recuperado.
- O TestClient travava dentro do sandbox neste ambiente, mas funcionou fora do sandbox e no Docker.

Leia `README.md`, examine o código e execute os testes antes de alterar. Preserve as alterações locais e não faça push remoto sem instrução.

## Beta polida — revisão atual

As pendências e contagens acima descrevem a recuperação anterior e não são a aprovação atual. A revisão completa está em `FINAL_UI_AUDIT.md` e `BETA_DELIVERY_REPORT.md`.

- Design system esportivo, revisão de home/lobby/mercado/seleção/review/elenco/transmissão/pós-jogo/transferências/playoffs/carreira.
- Recuperação de sessão tolerante a localStorage bloqueado, ligas próprias no servidor, WebSocket com retomada e erros explícitos.
- Correções de integridade financeira/permissões/recuperação e configuração segura de produção.
- 77 testes backend e 6 frontend reexecutados; fluxo HTTP de carreira completa com dois humanos nos dois modos.
- Navegador com sete viewports, axe e ações reais; transmissão reexecutada com 60 segundos reais.
- Ferramentas de teste atualizadas; audit de dependências final sem alertas na consulta executada.
- Ainda não houve deploy, catálogo real autorizado, fotos licenciadas ou teste público de carga. Arquitetura permanece em memória, JSON, um worker.

## Catálogo real — staging parcial (13/11/2026)

- Projeto usado nesta continuação: ZIP `brasileirao-manager-beta-polida.zip`, extraído em diretório de trabalho novo. O ZIP não contém `.git`; não foi possível verificar branch/status ou criar checkpoint Git sem inventar histórico. A pasta recuperada anterior não foi sobrescrita.
- Importados localmente os CSVs publicados `players`, `player_valuations`, `clubs` e `appearances` de `dcaribou/transfermarkt-datasets`, licença CC0-1.0 do repositório. Nenhum scraping do Transfermarkt foi feito. Raw CSVs permaneceram fora do pacote final.
- Gerados 1.192 registros em `data/catalogs/staging/transfermarkt_players.json`; 706 possuem valor histórico até 12/06/2026. Snapshot do dataset: 06/07/2026. O projeto upstream declara que não cobre squads 2026/27; esses valores não são cotação atual em novembro.
- Ratings, potencial, atributos FC Mania/EAFC, fotos licenciadas e afiliação CBF 2026 no catálogo brasileiro: zero confirmados. O staging EAFC tem 18.405 ratings/potenciais, mas nenhum dos 280 registros Série A cruza com alta confiança. O arquivo operacional `data/catalogs/players.json` não foi criado/alterado.
- Dataset de aparições não contém a competição brasileira BRA1; portanto não fornece evidência de minutos/titularidade no Brasileirão. O importador registra evidência indisponível, sem tratar ausência como zero jogos.
- EAFC26-DataHub/Kaggle foi importado para staging sob CC BY 4.0, com atribuição; FC Mania, CBF e PlayersDB permanecem fora por falta de export/autorização adequada. O CSV PlayersDB não está no workspace/Downloads.
- Importadores separados, matcher conservador, validação, staging, manifestos, relatórios de cobertura/lacunas/licenças/duplicidade e testes adicionados. Testes do pipeline: 7 aprovados; Ruff e compileall passaram. Suíte backend: 77 aprovados em Python 3.14.4 com as dependências de `requirements-lock.txt` alinhadas, fora do sandbox. O `TestClient` mínimo reproduz o travamento dentro do sandbox em `BlockingPortal.start_task_soon` (callback entre threads não acorda o event loop); o mesmo teste passou fora do sandbox, portanto não é falha de aplicação/Python identificada nesta tarefa. Docker daemon local não está em execução, então Docker Compose não foi validado. Frontend não foi reexecutado porque não houve alteração frontend.
- Bloqueio de produção: requer autorização/licença para ratings e imagens e export de elenco/inscritos atual (ou fonte licenciada equivalente), além de identidade/evidência esportiva de 2026. Ver `docs/CATALOG_DATA_DELIVERY.md` e `data/catalogs/CATALOG_SOURCES.md`.

## Prioridade overall/potencial — EAFC26 DataHub (13/11/2026)

- O CSV público do DataHub foi processado por importador dedicado. O Kaggle declara CC BY 4.0 para `rovnez/fc-26-fifa-26-player-data`, versão 3, atualizada em 22/09/2025.
- Resultado: 18.405 registros; 18.405 com overall; 18.405 com potencial; 18.405 com ambos; 18.405 com `value_eur` interno do EAFC.
- O arquivo contém 280 linhas na competição Série A, distribuídas por 14 clubes. Cruzamento conservador com os 1.192 perfis históricos: 6 correspondências por nome ou melhor, 5 `HIGH_CONFIDENCE`, 1 `NEEDS_REVIEW`, 18.399 `UNMATCHED`. Entre as 280 linhas Série A: 0 `HIGH_CONFIDENCE` e 0 elegíveis para produção.
- Há datas sentinela e nomes inconsistentes no subset brasileiro. Por isso `data/catalogs/staging/eafc26_players.json` preserva ratings/atributos com origem e flags, mas o mercado não foi alterado.
- Relatórios: `EAFC_TOTAL_REPORT.md`, `EAFC_COVERAGE.json`, `EAFC_COVERAGE_BY_CLUB.csv` e `EAFC_CROSS_MATCH.csv`.

## Desbloqueio do catálogo brasileiro — classificação independente (13/11/2026)

- O match com os 1.192 históricos agora é apenas enriquecimento financeiro; ele não decide a elegibilidade do registro EAFC.
- Datas `1996-02-29` são preservadas apenas em `source_birth_date_raw` e não são usadas como data de nascimento real.
- Os 280 candidatos Série A foram classificados em `EAFC_BRAZIL_CANDIDATES.csv`:
  - `INVALID_IDENTITY`: 184 (data sentinela no registro EAFC).
  - `STALE_CLUB`: 96 (identidade/rating estruturalmente utilizáveis, mas clube 2025 não confirmado por exportação oficial atual autorizada).
  - `NEEDS_REVIEW`: 0.
  - `VERIFIED`: 0.
  - `LICENSE_BLOCKED`: 0 (a fonte declara CC BY 4.0; os direitos subjacentes continuam documentados como risco).
- Nenhum registro foi promovido ao catálogo operacional. Cobertura validada: 0 clubes completos em 5x5 e 0 em 11x11.
- O builder aceita `--official-club-reference` somente para um JSON exportado de forma autorizada; sem esse arquivo, não promove candidatos automaticamente. A página CBF lista atletas e clubes da Série A 2026, mas os termos de uso vedam copiar/reproduzir dados sem autorização.
- Novos relatórios: `EAFC_BRAZIL_CANDIDATES.csv`, `EAFC_BRAZIL_TOTAL_REPORT.md`, `EAFC_BRAZIL_COVERAGE_BY_CLUB.csv` e `EAFC_BRAZIL_COVERAGE_BY_POSITION.csv`.
- Testes do pipeline: 9 aprovados; Ruff aprovado. Nenhuma alteração foi feita no catálogo operacional, mercado ou frontend.

## Investigação FC Mania e fontes brasileiras (13/11/2026)

- A Database pública do FC Mania anuncia FCM 26 V5, 25.045 jogadores, 943 clubes e 44 ligas, com overall, potencial, posições e resumos de atributos.
- Não foi localizado download, exportação CSV/JSON ou API pública com autorização de reutilização. Os termos do patch restringem o produto a uso pessoal, individual e intransferível; portanto nenhum dado foi copiado ou redistribuído.
- O importador `fcmania_importer.py` foi mantido como caminho seguro para uma exportação fornecida diretamente pelo responsável, mediante `permission_reference` obrigatório.
- Adicionados `SOURCE_EVALUATION.md`, `FCMANIA_AUTHORIZATION_REQUEST.md` e `FCMANIA_EXPORT_TEMPLATE.csv`.
- Fontes alternativas abertas consultadas não oferecem, com licença verificável, cobertura atual dos 20 clubes da Série A 2026 contendo overall, potencial e atributos simultaneamente.
- O catálogo brasileiro operacional continua bloqueado: não há registros reais autorizados com ratings completos suficientes para 320 atletas.

## Entrega integrada parcial — rating próprio e pacote completo (13/11/2026)

- Implementado `data/importers/brasileirao_rating_model.py` como `BRASILEIRAO_MANAGER_RATING_V1`, com pesos posicionais separados para GK/DF/MF/ST, normalização 1–99, potencial interno limitado por idade e confiança explícita.
- O modelo não preenche lacunas: exige indicadores esportivos posicionais e retorna pendente quando eles não existem. Na base disponível, 0/1.192 perfis possuem minutos, aparições e estatísticas suficientes; ratings próprios gerados: 0.
- Adicionados `data/catalogs/catalog_manifest.json` e `data/catalogs/sources.json`. O manifest marca `PARTIAL_NOT_OPERATIONAL`, preserva o modo demo e não cria `players.json` falso.
- Testes do pipeline: 10 aprovados. Testes backend de mercado, elenco e playoffs: 24 aprovados. Ruff e compileall aprovados.
- O ZIP final contém jogo, importadores, staging, relatórios, manifestos e testes, sem node_modules, venv, cache, credenciais ou banco de dados.
- Não há catálogo brasileiro operacional porque isso exigiria ratings/estatísticas autorizados ou dados próprios verificáveis que ainda não foram fornecidos. A entrega é tecnicamente executável em modo demo, mas não cumpre a meta de 320 atletas reais.
- Implementado `data/importers/game_pricing.py` para preços internos em centavos com Decimal/ROUND_HALF_UP, distinguindo valor externo histórico de preço do jogo.
- Pacote gerado: `/home/ti06/Downloads/brasileirao-manager-completo.zip` e validado com `unzip -t`; o SHA-256 é informado na entrega da sessão.

## Beta online e replay 2D — estabilização final (13/11/2026)

- O replay 2D passou a derivar posições de jogadores de formação, bola e participantes dos eventos; não movimenta todos os atletas aleatoriamente.
- Campo Canvas recebeu marcações de grande/pequena área, pontos de pênalti, círculo central, gols, faixas de gramado, destaque da bola e anel do jogador com a bola.
- O fluxo ao vivo agora filtra eventos pelo relógio autoritativo antes de mostrar linha do tempo ou evento atual; resultados futuros não são revelados.
- Adicionados testes de posição tática, limites do modo 5x5 e interpolação de eventos. Frontend: 7 testes, ESLint, typecheck e build aprovados.
- Criados `docker-compose.production.yml`, `frontend/Dockerfile.production`, `frontend/nginx.conf` e `docs/BETA_ONLINE.md` para VPS com uma instância, um worker, snapshots em volume e proxy HTTPS/WSS.
- Docker daemon não estava acessível neste ambiente; Compose não foi executado. Não houve deploy público nem URL online.
- ZIP consolidado final: `/home/ti06/Downloads/brasileirao-manager-BETA-ONLINE-FINAL.zip`. Extração limpa validou frontend, backend, Docker Compose de produção, replay e manifestos; node_modules, dist, caches e segredos não foram incluídos. O SHA-256 é informado na entrega da sessão.
