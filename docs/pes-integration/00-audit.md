# Integração PES 2013 Web — Fase 0: auditoria

**Data:** 24/11/2026.
**Branch:** `feature/pes-match-adapter`, criado a partir de `origin/main` (`a454f14`).
**Escopo:** o que o repositório realmente contém, para decidir a menor integração segura. Nenhum deploy.

## 1. Artefatos externos

Nenhum foi encontrado no workspace:

- `manifest.json` do PES Web;
- o worker JavaScript/WebAssembly;
- o MVP de relay FastAPI e o bridge Python;
- documentação do port.

A busca foi feita no repositório e em `~/Downloads`. O pacote recebido (`PROMPT_CLAUDE_RESENHA_PES2013_COMPLETO.zip`) só traz a especificação.

Por isso, **tudo o que se refere ao runtime do PES é hipótese não verificada** neste repositório, incluindo:

- worker que executa um PE32;
- entradas de teclado;
- `wsaRelayUrl` restrito a localhost;
- funções `host_net_*`;
- `EDIT.bin`.

Nenhuma dessas informações foi lida aqui. Elas vêm apenas da descrição do pacote.

**Licença.** O PES 2013 é software comercial de terceiros. Este trabalho não inclui, baixa nem redistribui:

- executáveis;
- patches;
- assets;
- arquivos de elenco.

Antes da Fase 2, é preciso confirmar que o port Web e os arquivos que você fornecer podem ser usados legitimamente. Ver também a regra de assets em `AGENTS.md`.

## 2. Arquitetura real (não a presumida pelo pacote)

| Camada | Onde | Observação |
|---|---|---|
| HTTP / WebSocket | `backend/app/api/routes.py` (WebSocket em `/ws/rooms/{room_id}`, linha 1564) | Rotas finas: autenticação, lock da sala e chamada de serviço. |
| Serviços | `backend/app/services/*.py` | Um serviço por agregado (`season_service`, `market_service`, `squad_service`, ...). |
| Domínio | `backend/app/domain/*.py` | Regras puras e motores determinísticos. |
| Persistência | memória + snapshots JSON (`services/snapshot_store.py`, `services/snapshots.py`) | **Não existe camada repository nem banco.** |

**Consequência.** O padrão "controller → service → repository" do pacote foi adaptado para "route → service → domain". Um serviço lê outro agregado pelo serviço dono dele: o novo serviço lê a temporada por `SeasonService.frozen_match`. Não foi criada uma camada de repositório que o projeto não tem.

## 3. Elencos, jogadores e atributos

**`CatalogPlayer`** (`domain/catalog.py:26`) tem:

- `id`, `name`, `club_code`;
- `position`: só GK, DF, MF ou ST;
- `secondary_positions`;
- `overall` e `potential`;
- `attributes: dict[str, int]` (linha 38);
- a origem dos dados (`source`, `source_version`, `rating_source`, `attribute_source`).

**Catálogo real** (`data/catalogs/players.json`, versão `brasileirao-fcm27-2026-11-15`):

- 320 jogadores, todos da fonte `FC_MANIA_FCM27`;
- 114 têm os seis atributos `pace`, `shooting`, `passing`, `dribbling`, `defending` e `physical`, e 16 goleiros têm os quatro `gk_diving`, `gk_handling`, `gk_reflexes` e `gk_positioning`;
- **206 jogadores não têm atributo nenhum**, só o overall. O motor atual usa um perfil derivado do overall (`match_engine.derived_attributes`). O contrato novo **não** deriva nem inventa nada: marca esses jogadores como `OVERALL_ONLY`.

**Jogadores criados pelo usuário: não existem no projeto.** Não há criação, entidade nem importação de "atleta personalizado". O requisito "jogadores reais e personalizados convivem" está **bloqueado pelo produto**, não pela integração. O contrato aceita só `origin = "CATALOG"`. Quando essa funcionalidade existir, basta acrescentar uma origem nova.

## 4. Partida oficial: de onde vêm os dados

1. **Início da rodada.** `SeasonService.advance` (`services/season_service.py:371`) monta, para cada confronto, um `TeamInput` por clube com `SeasonService._team_input` (linha 1365). Ele usa:
   - o elenco **atual** do clube no mercado;
   - a escalação salva (`squad_service.lineup_for`), ou uma automática se a salva não servir;
   - os atributos do catálogo, ajustados pela progressão de carreira e pela condição física;
   - a tática e as instruções individuais.
2. **Snapshot congelado.** As duas escalações são gravadas em `season.matches[id]["inputs"]` (linha 421), no formato de `team_input_view` (linha 1810). Esse snapshot já é imutável durante a partida: é dele que os motores (V6/V7/V8) e a recuperação após reinício leem.
3. **Mandante e visitante** vêm do calendário (`Fixture.home` / `Fixture.away`).
4. **Formações por modo** vêm de `domain/squad.py:37` (`formation_slots`): 5 titulares no 5×5 e 11 no 11×11, sempre um goleiro.
5. **Resultado.** `SeasonService.finish_due` (linha 686) grava o registro oficial e atualiza a tabela **uma vez por rodada**, sob o lock da sala. A sessão interativa sai da rodada quando o registro é escrito.
6. **Ações duplicadas.** No Modo Jogável, as ações têm `action_id` idempotente (`domain/highlights.py:1636`–`1675`, status `DUPLICATE`).
7. **Multiplayer atual.** O servidor é autoritativo: os clientes só desenham a `view`. Já foi verificado entre dois navegadores (2D/3D) em `frontend/scripts/verify-match-full.cjs` e em `app/tests/test_football_v8_sync.py`.

## 5. Lacunas em relação ao pacote

| Requisito do pacote | Situação no código |
|---|---|
| Snapshot imutável por partida | **Já existe** (`inputs`). Faltava um contrato neutro, versionado e com checksum: feito na Fase 1. |
| Lock do elenco no início | Existe na prática: o snapshot é feito ao abrir a rodada, e a janela de transferências fica fechada durante a rodada. |
| Jogadores personalizados | **Não existem** (lacuna de produto). |
| Atributos completos | Só 114 de 320 jogadores têm atributos. Qualquer motor externo vai precisar de uma regra explícita para os 206 restantes, a definir com você, e nunca de um valor inventado. |
| Posições detalhadas (CF, CMF, ...) | O projeto só tem GK/DF/MF/ST e a coluna da formação. O mapeamento para as posições do PES depende do formato real (Fase 2). |
| Repository / banco | Não existem. Não foram criados. |
| Artefatos do PES | Ausentes. As Fases 2 a 4 estão bloqueadas. |

## 6. Menor integração segura possível agora

A Fase 1 foi implementada **sem tocar em como as partidas são jogadas**:

- `backend/app/domain/match_contract.py`: `MatchPayload` v1 (Pydantic v2, imutável), construído a partir do snapshot congelado, com validação por modo e checksum SHA-256;
- `backend/app/domain/engine_adapters.py`:
  - `MatchEngineAdapter`;
  - `CurrentEngineAdapter`, com as capacidades comprovadas;
  - `Pes2013Adapter`, com todas as capacidades `False`, que recusa toda operação;
- `backend/app/services/match_payload_service.py`: serviço somente leitura;
- `SeasonService.frozen_match`: acessor somente leitura, que devolve cópias;
- flag `PES2013_ADAPTER_ENABLED` (padrão `False`) em `core/config.py`;
- três rotas novas:
  - `GET /api/v1/match-engines`: matriz de capacidades;
  - `GET /api/v1/rooms/{room}/season/matches/{id}/payload`: só membros da sala, partida já iniciada;
  - `POST /api/v1/rooms/{room}/season/matches/{id}/prepare/{engine}`: `RESENHA` aceita; `PES2013_WEB` recusa;
- testes: `backend/app/tests/test_match_contract.py`.

Detalhes e estado de cada requisito: `docs/pes-integration/STATUS.md`.
