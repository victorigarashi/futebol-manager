# Modo Carreira multiplayer — motor 2D, partida ao vivo e nova interface

Branch: `feature/gameplay-2d-sobre-main` (aplicada sobre a `main` remota, preservando o deploy Render e a reconexão).

## 1. Diagnóstico (por gravidade)

| Gravidade | Problema encontrado | Situação |
|---|---|---|
| Crítica | A partida era **inteira gerada antes da transmissão** (`simulate()` com Poisson); nada que o técnico fizesse durante os 60 s mudava o jogo. | Substituída por motor incremental com comandos ao vivo. |
| Crítica | Movimento 2D era **inventado no navegador** a partir de eventos (`replay.ts` interpolava jogadores em direção à bola). | Removido. O canvas desenha apenas posições autoritativas do servidor. |
| Crítica | **Sem substituições**, embora o elenco tenha banco real (16 atletas no 11×11, 8 no 5×5). | Implementado com regras validadas no servidor. |
| Alta | Táticas eram **bônus fixos de xG** por estratégia (o que o pedido proibia). | Mentalidade/pressão/estilo agora alteram parâmetros de comportamento dos agentes. |
| Alta | `round_preparation_duration_seconds` era salvo, mas **nunca aplicado** (configuração sem efeito). | Prazo aplicado: ao expirar, quem não confirmou joga com o plano salvo. |
| Alta | Alterar escalação depois de "Estou pronto" **não cancelava** a prontidão. | Cancelamento automático + aviso ao técnico. |
| Média | Três cópias divergentes do projeto; sidecar soccer-js em repositório separado, sem integração. | Base: cópia com catálogo real; ver §3. |
| Média | Teste de lobby dependia de `/data/catalogs` (só existe no Docker). | Documentado; testes rodam com `PLAYER_CATALOG_PATH`. |
| Info | 144 dos 320 atletas "operacionais" do catálogo são suplementos `synthetic-career` (ex.: todos os goleiros do Flamengo). | **Não alterado** (regra de não mexer no catálogo); afeta o realismo. |

Bugs encontrados e corrigidos durante a calibração do motor novo (todos com evidência numérica):
o portador nunca passava (0 passes/jogo); zona de pressão invertida; bola solta sem ninguém disputar
(29% do tempo); time que se movia primeiro em cada tick vencia muito mais (96×35 gols com elencos
idênticos → 52×57 após atualização simultânea); linha defensiva ficava atrás da bola.
No navegador: escalação automática colocava um meia no gol (o servidor rejeitava); colisão da
classe CSS `.toast` com o estilo legado; replay de lance vazio quando havia comando posterior.

## 2. Arquitetura

```
Catálogo + escalação + tática ─► MatchEngine (Python, 1 tick = 1 s de jogo, semeado)
                                   ▲ comandos (técnicos e bots, mesma API)
relógio do servidor ─► sync_live ──┘   │
                                       ├─► eventos + estatísticas + notas ─► GET /season/live (1×/s via WS)
                                       └─► frames (posições) ─► WebSocket `live.frames` ─► FrameBuffer ─► Canvas
```

- **`app/domain/match_engine.py`** — 22 agentes (10 no 5×5). Cada jogador busca um alvo derivado da forma
  da equipe, da bola e da tática (linha, compactação, apoio, corridas em profundidade, pressão, marcação
  individual com cobertura, bloco baixo, recomposição). O portador escolhe por valor esperado entre passe,
  passe em profundidade, condução, finalização e reter. Duelos, interceptações, faltas, cartões, escanteios,
  cabeceios, defesas e gols são resolvidos por atributos + distância + RNG semeado. Fadiga reduz velocidade e técnica.
- **Determinismo**: a partida é reproduzível a partir de (entradas, seed, log de comandos). Isso dá
  recuperação após reinício, replay de lances (`GET /matches/{id}/frames`) e auditoria.
- **`app/domain/bot_coach.py`** — escolhe escalação válida e, a cada 5 minutos de jogo, reage a placar, minuto,
  cansaço e expulsões usando `queue_tactics`/`queue_substitution` (as mesmas chamadas dos humanos, mesmos limites).
- **Relógio** (substituído em `docs/PARTIDAS_CONDENSADAS.md`): duração escolhida pela sala (1:30/2:00/3:00) com transmissão condensada
  + `LIVE_INTRO_SECONDS` (5 s de apresentação). As 10 partidas compartilham o relógio; o resultado só entra
  na tabela no apito final da rodada.
- **Substituições**: até 5 (11×11) / 3 (5×5), 3 janelas fora do intervalo no 11×11, aplicadas na próxima
  bola parada (ou na hora, se a bola já estiver parada/intervalo). Rejeita: jogador de outro time,
  inexistente, já substituído, pendência duplicada, limite e janelas.
- **Comandos**: `POST /season/live/commands` com chave de idempotência; validação de clube/partida;
  limite de 40 por partida. Cada técnico vê só a própria tática; o rival vê "mudou a postura".
- **Frontend** (`src/features/career/`): `CareerShell` (Central, Próxima partida, Elenco, Táticas, Mercado,
  Temporada, Classificação, Estatísticas), `LineupBoard` (clique ou arrastar), `TacticsBoard`, `PreMatch`
  (prontidão e prazo), `LiveMatchCenter`, `PitchCanvas` (rAF fora do React), `GoalCelebrationOverlay`, `PostMatch`.

### Por que não o soccer-js

O sidecar existia em outro repositório e nunca foi integrado a este jogo. Os relatórios das fases 10–12
mostram 0–3 eventos por 1.000 ticks (cada tick do soccer-js é 1/60 s: 1.000 ticks ≈ 17 s de jogo — por
isso tão poucos eventos), presets próprios sem ligação com o catálogo/banco e custo de um worker Node por
partida (10 por rodada por sala). O pedido proíbe dois motores concorrentes; o motor Python cobre o mesmo
papel com atributos reais, banco e comandos, e roda dentro da autoridade FastAPI.

## 3. Calibração (40 partidas 11×11 com o catálogo autorizado)

`cd backend && ../.venv/bin/python -m tools.engine_benchmark --matches 40 --ab`

| Métrica por jogo | Motor | Referência real (aprox.) |
|---|---:|---:|
| Gols | 3,1 | 2,5–2,8 |
| Finalizações / no alvo | 24,4 / 7,4 | 24–26 / 8–9 |
| xG total | 3,6 | ≈ gols |
| Passes / precisão | 1.407 / 79% | 850–950 / 80–85% |
| Escanteios | 11,6 | 9–10 |
| Faltas / amarelos / vermelhos | 31,9 / 3,9 / 0,5 | 22–26 / 4 / 0,2 |
| Vitória do mandante / empate | 57% / 13% | 45% / 25% |
| CPU por partida | ~0,35 s | — |

Efeito das táticas (equipe A com o plano indicado contra A equilibrada; mesmos elencos):
muito ofensiva vence 67%; pressão alta 77% (mais recuperações altas: 75 vs 34; mais cansaço: 0,68 vs 0,78 de
condição); direto 77%; contra-ataque 57%; muito defensiva 23% (menos posse do rival na área, poucas chances
próprias). Nenhum desses números vem de bônus: mudam porque o comportamento dos agentes muda.

**Pendências de calibração (honestas):** passes ~50% acima do real, poucos empates, pressão alta e jogo
direto ainda fortes demais contra o padrão "posse". Recomendado: busca automática de parâmetros em lote.

## 4. Testes

- Backend: **87 testes aprovados** (`pytest`, 7m38s; Ruff limpo), incluindo temporadas completas
  5×5 e 11×11 pela API, motor (determinismo, replay exato pelo log, regras de substituição, efeito real
  das táticas, bots só pela API pública) e rodada ao vivo (relógio único, nada simulado à frente do relógio,
  comandos idempotentes, autorização, dois técnicos, reconexão, frames por WebSocket, prazo de preparação,
  recuperação de snapshot com replay idêntico).
- Frontend: 10 testes (buffer de frames sem extrapolação, relógio de reprodução, escalação automática).
- Navegador real (Chrome, `frontend/scripts/verify-career.cjs`): **19/19** — dois técnicos (desktop e
  celular 390 px), escalação salva, tática, prontidão (e cancelamento ao mudar), apresentação, ao vivo,
  mudança tática, substituição aplicada em paralisação, gol com celebração, intervalo, pós-jogo com o
  mesmo placar nos dois clientes, rodada 2 aberta, sem erros de console e sem HTTP 429.
  Evidências em `docs/evidencias/carreira/`.

Reproduzir o teste de navegador:

```sh
# terminal 1 (backend)
APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json LIVE_INTRO_SECONDS=6 CORS_ORIGINS=http://127.0.0.1:5174 \
CAREER_ACCEPTANCE_STATE=/tmp/career.json ../.venv/bin/python -m uvicorn tools.career_acceptance:app --port 8000
# terminal 2 (frontend)
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npx vite --host 127.0.0.1 --port 5174
# terminal 3
node scripts/verify-career.cjs $PWD /tmp/career.json /tmp/career-shots
```

## 5. Limitações conhecidas

- Uma partida de 90' custa ~0,35 s de CPU; uma rodada (10 jogos) ~4 s distribuídos ao longo dos 3 minutos.
  No Render Free isso funciona para poucas salas simultâneas; não foi feito teste de carga com muitas salas.
- Fadiga não é carregada entre rodadas (todos começam com 100%); lesões não são modeladas.
- Formação não pode ser trocada durante o jogo (só mentalidade, pressão, estilo e substituições).
- A visualização é acelerada (padrão 30× o tempo real); com `LIVE_MATCH_SECONDS` maior o jogo fica mais legível.
- Playoffs são disputados instantaneamente pelo anfitrião (motor completo, com bots), sem transmissão ao vivo.
- O catálogo tem 144 suplementos sintéticos já identificados; fotos licenciadas de atletas não existem.
