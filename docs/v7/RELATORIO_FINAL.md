# Football Engine V7: relatório crítico final

- **Data:** 21/11/2026.
- **Branch:** `feature/gameplay-v7`, local, **sem push, merge ou deploy**.
- **Situação:** pronto para o **playtest do proprietário** no Lab (`#lab`). As competições continuam na V6 até a aprovação.

**Aviso de honestidade.** Todos os playtests deste relatório foram **automatizados**: scripts Playwright jogam pela interface real com mouse e gravam vídeo. **Não há feedback humano aqui.** Diversão não está comprovada: isso depende da sua avaliação.

## 1. O que mudou de verdade

O núcleo de jogo foi **reconstruído** em `backend/app/domain/football/` (ver `MOTOR_V7.md`). A orquestração, os contratos, as competições e o multiplayer foram mantidos.

| Problema da V6 (prioridade) | V7 | Evidência |
|---|---|---|
| Jogo em fotografias: a ação acaba no contato com a bola (P0) | Domínio em movimento: primeiro toque e assentamento; a decisão abre com os atletas em movimento. Cada ação dura cerca de 2 a 3 s de futebol contínuo | Rajadas `depois/sheet-*` × `baseline/sheet-*` |
| Movimento robótico (P0) | Locomoção vetorial com aceleração, frenagem e curva limitadas por atributos | Acelerações acima de 10 m/s²: **264,6 → 66,9** por mil quadros de jogador (11×11) e **339,2 → 41,9** (5×5). Arrancadas instantâneas: **20,2 → 0,1** |
| Bola colada na condução (P0) | Condução por toques: a bola tem física própria e fica exposta entre os toques | Distância bola–pé varia de 0,16 m de desvio-padrão (cinemática) para **0,45 m** (toques); cerca de 1 ciclo de toque registrado por condução |
| Goleiro artificial (P0) | Agente com corpo: reação ao contato real, passo, salto e mergulho com **deslocamento físico**, contato por varredura | Bateria (seção 4); teste `test_keeper_dive_is_a_real_displacement` |
| Defensor congela e dispara (P1) | Inércia durante o tempo de reação | `instant_start` ≈ 0 |
| Giro instantâneo e pose de frente (P1) | Orientação e estado de ação por quadro; spline no cliente | Contrato V7; `presentation.ts` |
| Bola sem peso (P1) | Rolagem com arrasto, voo balístico e quique a 40 Hz | `test_ball_*`, `test_lofted_ball_*` |
| Chute sem preparação (P1) | Preparação de 0,12 a 0,42 s; a bola sai no contato; o erro cresce com o giro do corpo | `test_kick_has_a_windup_*` |
| IA: todos na bola (P1) | Papéis: pressionador, cobertura, marcadores, linha comum, apoios, profundidade e ataque à área | Rajadas; sobreposição de corpos: **5,8 → 0,8** por mil |
| Arquibancada na tela e portador sob a barra (P1) | Câmera 3D refeita; câmera 2D olha além da lateral; rótulo vai para o topo | `baseline/*-mira.png` × `depois/*-mira.png` |
| Abertura estática e pouca variedade (P1) | Lance já começa em movimento; superioridade 3×2; a IA conduz **0,7 → 7,7** vezes por partida (11×11) | `metricas_v7.json` |

## 2. Métricas antes e depois

30 partidas IA × IA por formato, sobre os quadros oficiais (`gameplay_metrics.py`).

| 11×11 | V6 | V7 |
|---|---|---|
| Acelerações acima de 10 m/s² (por mil) | 264,6 | 66,9 |
| Arrancadas instantâneas (por mil) | 20,2 | 0,1 |
| Corpos sobrepostos (por mil) | 5,8 | 0,8 |
| Velocidade máxima do goleiro (m/s) | 5,4 | 7,0 (mergulho) |
| Gols por partida | 1,43 | 1,00 |
| Chutes por partida | 7,7 | 4,7 |
| Passes certos | 84% | 69% |
| Conduções por partida | 0,7 | 7,7 |
| Duração média do lance (s) | 5,3 | 8,0 |
| Duração real da partida, só bots (s) | 124 | 124 |

| 5×5 | V6 | V7 |
|---|---|---|
| Acelerações acima de 10 m/s² (por mil) | 339,2 | 41,9 |
| Arrancadas instantâneas (por mil) | 29,6 | 0,4 |
| Corpos sobrepostos (por mil) | 24,0 | 3,0 |
| Gols por partida | 3,13 | 1,40 |
| Chutes por partida | 7,4 | 7,2 |
| Passes certos | 86% | 59% |

Arquivos: `evidencias/v7/baseline/metricas.json` (V6) e `evidencias/v7/depois/metricas_v7.json` (V7), ambos com os parâmetros finais.

**Leitura crítica.**

- A naturalidade melhorou muito.
- O **equilíbrio entre bots** ficou mais travado que na V6: menos gols, sobretudo no 5×5 (3,1 → 1,4), e passes menos certos.
- Ataques humanos tendem a converter mais; isso **não foi medido** com humanos.
- É o principal ponto de calibragem antes de ligar a V7 nas competições. Os parâmetros estão todos no topo dos módulos.

## 3. Avaliação interna por área (0 a 10, com evidência)

A meta interna era 8. **Ela não foi atingida em todas as áreas, por isso a V7 não está aprovada internamente para as competições.**

| Área | Nota | Evidência e limitação |
|---|---|---|
| Física da bola | 8 | 40 Hz, rolagem, arrasto, quique, traves, travessão e varredura; previsão do cliente idêntica à do servidor (`rollDistance` = `pass_reach`) |
| Locomoção | 7 | Limites físicos medidos e testados. Ainda há 6% de quadros acima de 10 m/s², vindos de choques entre corpos e mudanças de alvo |
| Goleiros | 7 | Estados, reação, mergulho com corpo, bateria. Faltam reposição e animações específicas de defesa baixa e de encaixe no 3D |
| Domínio e recepção | 7 | Domínio em movimento, toque pesado, bola que passa |
| Condução e drible | 7 | Toques, exposição, desarme, defensor batido. Sem gestos de drible específicos (finta) |
| Passes | 6 | Físicos, com assistência moderada e passe em profundidade. Taxa de acerto entre bots ainda baixa |
| Chutes | 6 | Preparação, altura, erro físico. Sem efeito (curva) e sem chute de primeira dedicado |
| Cruzamentos e cabeceio | 6 | Balísticos, disputa aérea, saída do goleiro. Pouco testados no navegador |
| IA ofensiva | 6 | Papéis e corridas; avaliada só por rajadas e métricas |
| IA defensiva | 6 | Linha, pressionador e cobertura; interceptações ainda altas no 5×5 |
| Controles e mira | 6 | Mira mínima mantida; o gesto pode começar em qualquer lugar. A curva de potência não foi revista. **Toque em celular não foi testado** |
| Responsividade | 7 | Confirmação oficial entre 70 e 100 ms na máquina local (Lab, localhost). Não medido em rede real |
| Animações 2D e 3D | 5 | Agora sincronizadas com os estados do servidor e com o deslocamento real. Os sprites 2D e as animações procedurais 3D são os da V6 |
| Visual 2D | 6 | Câmera corrigida; sprites da V6 |
| Visual 3D | 6 | Câmera refeita; modelos da V6 |
| Ritmo | 6 | Jogada contínua; partida com a mesma duração; lance mais longo |
| Performance | — | Backend com cerca de 0,25 s de CPU por partida. **FPS não medido em hardware real** (capturas com SwiftShader) |
| Multiplayer | 7 | Dois navegadores, um 2D e outro 3D: sem divergência, recarga no meio da partida retomada. Uma execução completa até o apito; ver seção 5 |

## 4. Goleiro: bateria de testes

`tools/keeper_battery.py`, 40 sementes por cenário, atacante sozinho contra o goleiro. G = gols, D = defesas.

| Cenário | Goleiro 55 (G/D) | Goleiro 75 | Goleiro 90 |
|---|---|---|---|
| Chute fraco e central, 15 m | 4/36 | 1/39 | 1/39 |
| Bola alcançável, 20 m | 3/37 | 0/40 | 0/40 |
| Canto, 16 m | 13/22 | 6/32 | 1/37 |
| Rasteiro no canto, 14 m | 6/30 | 0/39 | 0/40 |
| Canto fora do alcance, 9 m | **0 defesas** | **0** | **0** |
| À queima-roupa, 6 m | 40/0 | 40/0 | 37/3 |

**Plausível:**

- o atributo do goleiro importa;
- nenhuma defesa fisicamente impossível acontece.

**Rígido:** à queima-roupa o goleiro quase nunca defende, porque na bateria ele parte da linha do gol, sem tempo de sair.

## 5. Matriz de compatibilidade

| Item | Situação | Evidência |
|---|---|---|
| Football Lab: partida completa, 10 cenários, 5 treinos, 5×5 e 11×11, 2D e 3D, dificuldade, motor, repetir semente | Feito | `GameplayLab.tsx`; playtests `depois/*` |
| Mesmo resultado no 2D e no 3D (um único motor) | Feito | Mesma `view`; teste de determinismo `test_same_seed_same_match_*` |
| Dois navegadores (2D contra 3D) na mesma partida | Feito | `evidencias/v7/multiplayer/results.json`: zero divergências em até 205 comparações sincronizadas; recarga no meio retoma a mesma partida, placar e relógio; resultado gravado (vencedor MIR na 1ª execução). As execuções seguintes, com janela de 5 min, não chegaram ao apito porque o driver automático demorou a gesticular no 3D por software. Isso não é uma falha da partida |
| Reconexão, tempo esgotado e IA assumindo | Mantidos (orquestração da V6) | `test_highlights.py` |
| Idempotência (ação duplicada) na V7 | Feito | `test_human_gesture_is_executed_once_*` |
| Snapshot e restauração com a V7 | Feito | `test_same_seed_same_match_and_snapshot_round_trip` |
| Carreira, Draft Eliminatório, Pack & Play e Último Sobrevivente com partidas interativas na V7 | Feito: campeão nos 4 modos, com técnicos jogando e ausentes | `test_football_v7_competitions.py` (8 de 8) |
| Copa do Brasil e Draft (liga) na V7 | Não executado separadamente | Mesmo fluxo de mata-mata e liga |
| Modo Técnico | Intacto (não usa este motor) | — |
| V6 intacta e selecionável | Sim | `test_highlights.py` (48 testes) e `test_v6_matches_still_use_v6` |

## 6. Testes

| Conjunto | Resultado |
|---|---|
| `test_football_v7.py` | 17 passaram |
| `test_football_v7_competitions.py` | 8 passaram |
| `test_highlights.py` (V6) | 48 passaram |
| Suíte completa do backend | ver seção 8 |
| Frontend | `npm run typecheck` limpo; eslint limpo; vitest dos módulos interativos passou |

## 7. O que NÃO foi feito (sem esconder)

1. **Feedback humano.** Nenhum. A aprovação de diversão é sua.
2. **Sprites 2D novos** (Fase 8): os sprites, campo e animações 2D são os da V6. Ganharam orientação real e sincronia com o servidor, mas não foram redesenhados.
3. **Modelos e animações 3D** (Fase 9): sem rig importado, sem captura de movimento, sem IK de pé. Os modelos e poses procedurais são os da V6, agora alimentados por estados reais. Ver ASSET_LICENSES.md.
4. **Chute com efeito, chute de primeira, finta, reposição do goleiro e barreira com apresentação própria.**
5. **Touch em celular:** não foi testado nesta etapa. O cálculo do gesto é o mesmo do mouse.
6. **FPS e memória em hardware real.**
7. **Calibragem do equilíbrio entre bots:** está mais baixa que na V6. Precisa de uma rodada com o proprietário.
8. **Referências em vídeo** (World Soccer Champs, DLS 2019, Mini Soccer Star, Score! Hero, Pixel Cup Soccer): não consigo assistir a vídeos neste ambiente. As decisões seguiram as descrições da mecânica: momentos decisivos, arraste, passe desenhado e ritmo arcade.
9. **Pesquisa de repositórios** (Google Research Football, RoboCup, Yuka, Rapier): foi conceitual, sem importar código. O motor é próprio, determinístico e sem dependências novas.

## 8. Como avaliar

1. `cd backend && APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json ../.venv/bin/python -m uvicorn app.main:app --port 8000`
2. `cd frontend && npx vite`, depois abra `http://localhost:5173/#lab`.
3. Escolha **Partida completa contra o bot**, ou um treino. Use o **Motor V7** e compare com o **V6**; **↺ Repetir** refaz a mesma situação.
4. Para testar a V7 numa sala de verdade, inicie o backend com `GAMEPLAY_ENGINE=v7` e crie uma sala no Modo Jogável.

**Não houve deploy.** Para ligar a V7 nas competições, é preciso:

- a sua aprovação;
- `GAMEPLAY_ENGINE=v7` no Render;
- e o merge.
