# Entrega do Prompt Master V2

Data: 17/11/2026. Branch de trabalho: `feature/carreira-fase1`. A carreira, a narrativa e o frontend da carreira foram feitos em paralelo por outra sessão, em `feature/carreira-integrada` (`4e3e7a5`, documentado em `docs/CARREIRA_COMPLETA.md`), e esta branch foi rebaseada sobre esse commit.

## 1. Estado inicial

Ver [AUDITORIA_V2.md](AUDITORIA_V2.md), com a matriz completa do que existia e funcionava, do que estava incompleto e do que faltava, e [AUDITORIA_CARREIRA.md](AUDITORIA_CARREIRA.md), da Fase 0.

## 2. Bugs corrigidos

| Bug | Correção |
|---|---|
| Progressão (gols não contavam, valor não acumulava, ±1 por temporada) | Fase 1 anterior (`68c040a`), mantida e testada. |
| Propostas a clubes de bots da sala ficavam pendentes para sempre: a rota tratava os bots como humanos | `routes.create_transfer_offer` filtra `role != "BOT"`. |
| Playoffs simulados instantaneamente, com chave fixa, só em jogo único e prêmios errados | Mata-mata ao vivo, com sorteio, ida e volta e prêmios novos (seção 3). |
| A duração de 60 s não existia | Virou o padrão. 1:30, 2:00 e 3:00 continuam disponíveis, e snapshots antigos mantêm 1:30. |
| Gols contra "na maioria dos gols" | **Não reproduzido.** O motor não gera gol contra, e em 100 partidas (506 gols) houve 0 autorias invertidas. Há teste de regressão (`test_goal_integrity.py`). Sem um print ou id de partida, não houve mudança cega. |
| Placar ao vivo | Já corrigido antes (fonte única de eventos) e coberto por testes. |

## 3. Funcionalidades implementadas

| Área | O que foi feito | Onde |
|---|---|---|
| Regras da sala | Modo Tradicional/Draft, Realista/Emocionante, dificuldade dos bots, moral, Copa do Brasil, playoffs em jogo único ou ida e volta, troca de técnico, catálogo e overall mínimo do Draft. Validadas no backend e congeladas após o início. | `domain/rooms.py` (`RULES`) |
| Orçamentos | De R$ 50 mi a R$ 1 bi, em centavos inteiros. | `rooms.BUDGETS` |
| Entrosamento tático | Compatibilidade (atributos, posição, estilo, instruções, equilíbrio) e familiaridade por estilo, viram um fator moderado no motor. Calibrado e documentado. | `domain/cohesion.py`, [ENTROSAMENTO.md](ENTROSAMENTO.md) |
| Instruções individuais | Por função (GK, lateral, zagueiro, meio, atacante). Mexem na posição, nas corridas e nas escolhas de passe. Os bots também usam. | `cohesion.INSTRUCTIONS`, motor |
| Controle ao vivo | Mudança de formação durante a partida, registrada e reproduzida no replay. | `MatchEngine.queue_formation` |
| Estilo de simulação | O Emocionante dá +24% de gols no 11×11, sem placares absurdos (máximo de 7 em 160 jogos). | `match_engine.SIM_STYLES` |
| Bots | Casual, Competitivo e Lendário, diferentes só na qualidade das decisões: plano pré-jogo por entrosamento, leitura do adversário, formação no fim do jogo, substituições, mercado e Draft. | `domain/bot_coach.py`, `transfer_service` |
| Mercado | Compra só em dinheiro, troca com dinheiro, contraproposta (bots respondem), prazos, negociação que fracassa, valor dinâmico, bots propondo, janela entre temporadas. | `services/transfer_service.py` |
| Empréstimos | Uma temporada, taxa negociável, só no Tradicional; dono e clube de atuação separados; retorno automático. | `transfer_service` (`_loans`, `end_loans`) |
| Playoffs | Potes (1–4 contra 5–8), sorteio único e reproduzível, jogo único ou ida e volta com agregado e pênaltis, ao vivo. Prêmios de 50 / +100 / +150 / +200 mi, idempotentes. | `domain/knockout.py`, `season_service._settle_knockout` |
| Copa do Brasil | Preliminar com os 8 piores cabeças de chave, oitavas por potes, quartas, semi e final. Intercalada com a liga, ao vivo, com campeão separado e sem prêmio inventado. | `knockout.schedule_cup` |
| Modo Draft | Três cartas, sorteio equilibrado, reservas livres, atletas repetíveis como instâncias, overall mínimo, bots, conclusão automática, telas. | [MODO_DRAFT.md](MODO_DRAFT.md) |
| Catálogo Mundial | 2.386 atletas com identidade CC0 e overall editorial próprio. Nada da EA. | [CATALOGO_MUNDIAL.md](CATALOGO_MUNDIAL.md) |
| Carreira e narrativa (outra sessão) | Clássicos, eventos especiais, notícias, estatísticas, Sala de Troféus, moral e condicionamento, troca de técnico, câmera híbrida, telas da carreira e da Copa, cerimônia de sorteio. | `docs/CARREIRA_COMPLETA.md` |

## 4. Parcialmente concluído ou fora do escopo

- **Reformulação completa do 2D (§12).** Feito:
  - novos comportamentos por instrução (laterais que passam, falso 9, pivô, corridas em profundidade, goleiro-líbero);
  - estilo Emocionante;
  - formação ao vivo;
  - câmera híbrida (outra sessão).

  **Não feito:** reescrever passes, cruzamentos e o deslocamento do goleiro no motor. O motor atual já evita teletransporte e trajetórias impossíveis (`docs/PARTIDAS_CONDENSADAS.md`), e mexer nisso sem uma medição visual dedicada arriscaria regressão.
- **Redesign visual (§3).** Feito: telas do Draft, painel de entrosamento e telas da carreira (outra sessão). **Não feito:** reformular tela inicial, lobby e mercado inicial; eles continuam com o visual atual, que já segue os tokens grafite e lima.
- **Atributos individuais na progressão.** Seguem o overall em bloco: o catálogo só tem 6 atributos, e só para 116 dos 320 atletas.
- **Não implementado, por decisão do prompt (§25 e §26):** pênaltis interativos, olheiros e química por liga ou nacionalidade.

## 5. Evidência dos testes

| Suíte | Resultado |
|---|---|
| Backend (pytest, 14 processos) | 211 testes passando após o rebase, mais os 13 de Draft e catálogo adicionados depois |
| Pipeline de catálogo | `data/importers/test_world_catalog.py`: 3 passando |
| Frontend | tsc sem erros, ESLint sem avisos, vitest 41 passando, build de produção ok |
| Navegador: Draft | `frontend/scripts/verify-draft.cjs`: **15/15** (desktop 1440 px e celular 390 px, sem rolagem horizontal, sem erros no console). Prints em `docs/evidencias/draft/`. |
| Navegador: entrosamento | Aba Táticas com 11 instruções, salvamento confirmado, 0 erros (`docs/evidencias/draft/05-entrosamento.png`) |
| Navegador: carreira (outra sessão) | `frontend/scripts/verify-career.cjs`: 27/27 |

Os testes novos cobrem os itens §31 (Draft) e §32 (ciclo de carreira):

- `test_draft.py`
- `test_cohesion.py`
- `test_knockout.py`
- `test_market_v2.py`
- `test_end_to_end.py` (38 rodadas, playoffs ao vivo e nova temporada em 5×5 e 11×11)

## 6. Desempenho

CPU de uma rodada completa de 10 partidas com bots, mesma máquina, mediana de 3 execuções:

| Modo | Antes (`68c040a`) | Agora | Variação |
|---|---|---|---|
| 11×11 | 3,46 s | 3,51 s | +1,4% |
| 5×5 | 1,72 s | 1,77 s | +2,9% |

As regras novas (entrosamento, instruções, dificuldade dos bots) não mudam o custo de forma relevante. Os playoffs e a Copa ao vivo acrescentam rodadas, não carga simultânea. O limite medido antes, de cerca de 3 salas jogando juntas no Render Free (`docs/DESEMPENHO_TEMPO_REAL.md`), continua valendo.

## 7. Executar no Ubuntu

Ver [RUNNING.md](RUNNING.md). Resumo:

```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt && npm ci --prefix frontend
cd backend && APP_ENVIRONMENT=development CORS_ORIGINS=http://localhost:5174 \
  PLAYER_CATALOG_PATH=../data/catalogs/players.json WORLD_CATALOG_PATH=../data/catalogs/world_players.json \
  ../.venv/bin/python -m uvicorn app.main:app --port 8000
cd frontend && VITE_API_BASE_URL=http://localhost:8000/api/v1 npm run dev -- --port 5174
```

Testes:

```sh
cd backend && PLAYER_CATALOG_PATH=$PWD/../data/catalogs/players.json ../.venv/bin/python -m pytest
```

O teste de lobby precisa do catálogo nesse caminho.

## 8. Render (gratuito)

`render.yaml` (blueprint) define:

- `brasileirao-manager-api` (Python, `--workers 1`, um processo autoritativo);
- `brasileirao-manager-web` (estático).

Variáveis novas: `WORLD_CATALOG_PATH=../data/catalogs/world_players.json`. Se ela faltar, o servidor procura o arquivo ao lado de `players.json`. O deploy é automático a partir da `main`. As salas ficam em memória: um deploy ou a hibernação do plano gratuito encerra as salas em andamento.
