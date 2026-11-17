# Instruções para finalizar: novos modos, 2D e redesign dos menus

Branch: `feature/modos-2d-redesign`, a partir de `main` `0216532`, que está em produção. **Não** foi feito merge na `main` nem deploy desta branch.

Leia antes:

- `docs/DIAGNOSTICO_2D.md`: o que foi corrigido no motor e na transmissão, com medições;
- `docs/AUDITORIA_V2.md` e `docs/CARREIRA_COMPLETA.md`: contexto do jogo.

## 1. O que já está pronto e testado

| Parte | Estado | Onde |
|---|---|---|
| Fases A/B: diagnóstico e correção do 2D | ✅ commit `1240452` | `match_engine.py`, `broadcast.py`, `bot_coach.py`, `frameBuffer.ts`, `PitchCanvas.tsx` |
| Backend: Draft Eliminatório, Último Sobrevivente e Pack & Play | ✅ commit `adb5014` | `domain/tournaments.py`, `domain/packs.py`, `services/pack_service.py`, `season_service.py`, `rooms.py`, `routes.py` |
| Testes do backend dos modos | ✅ 14/14 | `app/tests/test_new_modes.py` |
| Suíte completa do backend (depois do 2D) | ✅ 215 passaram | `pytest -n 6` |
| Frontend: tipos e API dos modos | ✅ | `lib/api.ts` |
| Frontend: metadados dos modos e caminho da sobrevivência (idêntico ao servidor, com arredondamento bancário) | ✅ e testado | `lib/gameModes.ts`, `lib/gameModes.test.ts` |
| Menu principal cinematográfico e seleção de modos | ✅ escrito e integrado, **ainda não validado no navegador** | `features/home/MainMenu.tsx`, `home.css` |
| Assistente de criação de sala por etapas e por modo (substitui `LeagueSettingsDialog`) | ✅ escrito e integrado, **ainda não validado no navegador** | `components/RoomWizard.tsx`; uso em `LobbyPage.tsx` |
| Tela do Pack & Play (abertura com revelação, montagem, comparação, espera) | ✅ escrita, com CSS básico, **ainda não validada no navegador** | `features/pack/PackPage.tsx`, `pack.css` |

Estado verificado no último commit:

- frontend: `tsc -b`, `eslint` sem avisos, `vitest` 45/45 e `npm run build` OK;
- backend: `ruff` OK e `test_new_modes.py` 14/14.

**Decisão do usuário: a câmera fica como está.** As opções "Campo inteiro" e "Dinâmica" permanecem; não mude o padrão.

## 2. O que falta (em ordem)

### 2.1 Remover o diálogo antigo

`frontend/src/components/LeagueSettingsDialog.tsx` não é mais usado, porque o `RoomWizard` o substituiu. Confirme com `grep -rn LeagueSettingsDialog frontend/src` e remova o arquivo.

### 2.2 Carreira em 5 áreas

Arquivo: `features/career/CareerShell.tsx`. Hoje são 11 abas planas.

Reorganizar para:

1. **Central**: `ClubHub` e notícias relevantes.
2. **Elenco**: subabas Escalação (`LineupBoard`), Táticas (`TacticsBoard` + `CohesionPanel`).
3. **Mercado**: `TransferHub` e `CareerPanel`.
4. **Competições**: subabas Calendário (`SeasonCalendar`), Classificação, Copa (se `knockout.cup_enabled`) e Playoffs.
5. **Clube**: subabas Estatísticas (`StatsCenter`), Notícias (`NewsCenter`), Troféus (`TrophyRoom`).

Regras:

- "Próxima partida" (`PreMatch`) vira o **botão de destaque** no cabeçalho da carreira, não uma aba.
- Mapear o valor antigo salvo em `localStorage` `bm_tab_<room>` para a área nova.
- Use o componente `.segmented`, que já existe em `career.css`, para as subabas.

### 2.3 Telas das competições curtas, dentro do `CareerShell`

- `season.game_mode` vem na view da temporada; use `isShortMode()` de `lib/gameModes.ts`.
- Em modo curto: **sem Mercado** e **sem calendário de liga**.
- Áreas: Central, Elenco, Competição e Clube.
- **Torneio** (`DRAFT_KNOCKOUT` ou `PACK`): `<Bracket knockout={season.knockout} kind="TOURNAMENT" champion={season.champion} …/>`. O `competitionOf` já aceita `TOURNAMENT` e só mostra as fases a partir da primeira sorteada.
- **Último Sobrevivente**: `season.survivor`, tipo `SurvivorView`. Mostrar:
  - o caminho `path` (8 → 6 → 4 → 2 → Final), destacando a posição atual (`remaining`);
  - a tabela da rodada (`rounds[-1].table`), com os eliminados (`rounds[-1].eliminated`) em vermelho e os seguros em verde;
  - a revelação dos eliminados ao fim de cada rodada: animação curta e opcional, com botão de pular, guardando em `localStorage` que aquela rodada já foi revelada;
  - a lista `eliminated` com a rodada de cada um;
  - o campeão, quando houver.
- `PreMatch` já trata o mata-mata: `waiting` quando o clube não joga a rodada; `next_round` traz a fase. Ajuste os textos para "Torneio" e "Sobrevivência" usando `next_round.kind` (`TOURNAMENT` ou `SURVIVOR`).
- No modo espectador, o eliminado vê a tabela e a chave sem botões de ação. O backend já não exige a prontidão dele (`required_ready`).
- Em modo curto o botão "Começar próxima temporada" não deve aparecer: o backend responde 409 com a mensagem "uma edição só".

### 2.4 Barra da sala

Arquivo: `components/RoomToolbar.tsx`. Hoje as etapas estão fixas. Fazer por modo:

| Modo | Etapas |
|---|---|
| Carreira | Clube → Contratações → Elenco → Campeonato |
| Draft e Draft Eliminatório | Clube → Draft → Elenco → Competição |
| Pack & Play | Clube → Pacotes → Elenco → Torneio |
| Último Sobrevivente | Clube → Elenco → Sobrevivência |

Acrescente as fases que faltam no mapa `phases`: `PACK` = "Pacotes".

### 2.5 Draft

`features/draft/DraftPage.tsx` deve mostrar só Formação, Cartas, Elenco, Entrosamento e Competição. Revise e tire o que sobrar.

### 2.6 Partida ao vivo

`features/career/live/LiveMatchCenter.tsx`. Prioridade de tela:

1. campo 2D;
2. placar e relógio;
3. eventos essenciais;
4. comandos táticos e substituições.

Estatísticas detalhadas em painel recolhível (`<details>`).

### 2.7 Lobby da sala (fase `WAITING`)

Mostrar o card do modo (`modeInfo(room.game_mode)`: nome e cor de destaque) e o resumo das regras específicas do modo:

- `LeagueSettingsSummary.tsx` hoje fala só de liga;
- para Sobrevivência: caminho e eliminações;
- para Pack & Play: distribuição;
- para torneio: fases.

### 2.8 Documentação

Criar `docs/MODOS_NOVOS.md` com as regras. Fonte: docstrings de `domain/tournaments.py` e `domain/packs.py`. Conteúdo:

- **Torneio:** chave por força, metade forte contra metade fraca, sorteio único `crc32(room:tournament:fase)`, jogo único, pênaltis, sem prêmios, uma edição só.
- **Sobrevivência:**
  - critérios: pontos, saldo, gols, campanha (pontos, saldo, gols) e sorteio fixo `crc32(seed:club)`;
  - eliminações sempre pares: automático ≈ 25%, ou 2 ou 4;
  - final com pênaltis;
  - elencos reais (16 atletas, 2 goleiros por clube).
- **Pack & Play:**
  - faixas Ouro, Prata e Bronze: 15/35/50% do catálogo por overall;
  - Equilibrada: mesma mistura para todos, 4/8/12 cartas no 11×11;
  - Sorte: sorteio independente com essas probabilidades;
  - composição garantida: 11×11 com 3 GK, 8 DF, 7 MF, 5 ST e 1 livre (4 pacotes de 6); 5×5 com 2 GK, 4 DF, 3 MF, 2 ST e 1 livre (3 pacotes de 4);
  - sem repetição dentro da coleção; repetição entre técnicos com instâncias `PCK-…`;
  - sem compra e sem moeda;
  - nada passa para a Carreira.

## 3. Testes obrigatórios antes do merge

```bash
cd backend && PLAYER_CATALOG_PATH=../data/catalogs/players.json ../.venv/bin/python -m pytest -q -n 6
cd backend && ../.venv/bin/ruff check app
cd frontend && npx tsc -b && npx eslint src --max-warnings=0 && npx vitest run && npm run build
```

Navegador:

- `frontend/scripts/verify-career.cjs` precisa continuar em **27/27**. O padrão de duração é 1:00. Ver `docs/MODO_CARREIRA.md` §4 para subir o servidor de aceitação.
- `frontend/scripts/verify-draft.cjs` precisa continuar em 15/15.
- **Criar `frontend/scripts/verify-modes.cjs`**, com dois técnicos (desktop e celular de 390 px), cobrindo:
  - menu → Nova partida → card do modo → assistente → sala;
  - Pack & Play: abrir os pacotes (animação e pular), montar o time, confirmar, chegar ao torneio e jogar uma rodada ao vivo;
  - Último Sobrevivente: 8 clubes, jogar a rodada 1, ver a tabela, ver 2 eliminados e confirmar que restam 6;
  - recarregar a página no meio e verificar que o estado é o mesmo;
  - nenhum erro de console.

Os seletores úteis estão em `MainMenu.tsx` (`.menu-list button`, `.mode-card`) e em `PackPage.tsx` (`.pack-stack__open`, `.pack-pitch__slot`).

Validar o 2D visualmente: gravar ou capturar uma partida de 1:00 e uma de 3:00 e conferir:

- a bola voa no chute;
- o goleiro mergulha;
- os lances começam na recuperação da bola.

## 4. Entrega

1. Commit na branch.
2. Rodar tudo da seção 3.
3. Merge (fast-forward) na `main` e push. O Render faz deploy automático:
   - API: `srv-dbsb9guk1f9s738q7rog`;
   - Web: `srv-dbsb9l2fngtc73c8j2r0`.
4. Conferir na produção:
   - `GET https://brasileirao-manager-api.onrender.com/api/v1/health` responde `ok`;
   - o `openapi.json` tem `/rooms/{room_id}/pack`;
   - o bundle do site contém "Escolha o modo".
5. ZIP final só depois dos testes (`git archive`), em `~/Downloads/`. Não apagar ZIPs nem cópias anteriores.

## 5. Restrições do projeto (não violar)

- Sem banco de dados, um único worker no Render Free, simulação determinística e o servidor como autoridade.
- Não recriar o motor de partida nem reimplementar o que já funciona.
- Sem compra de pacotes, sem moeda e sem loot box paga.
- Não copiar a identidade visual do Ultimate Team.
- Não alterar a câmera (decisão do usuário).
- Não afirmar que testes passaram sem executá-los.
