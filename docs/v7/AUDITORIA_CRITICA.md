# Football Engine V7: auditoria crítica e causa raiz (Fase 0)

- **Data:** 21/11/2026.
- **Branch:** `feature/gameplay-v7`, worktree `futebol-manager-gameplay-v7`, a partir de `6c0a033` (V6, que é o que está em produção).

Este documento registra o estado **antes** da V7.

## 1. Como a baseline foi medida

| Fonte | O que é | Onde está |
|---|---|---|
| Playtest pela interface real | Lab (`#lab`) no Chrome, com arrastes do mouse no campo. Partidas 11×11 nos cenários construção, infiltração, cruzamento e cara a cara, **em 2D e em 3D**. Grava vídeo, rajadas de quadros durante a execução, mira e fim do lance | `docs/evidencias/v7/baseline/` |
| Métricas do motor | 30 partidas IA × IA por formato, sobre os **quadros oficiais** que o cliente recebe | `backend/tools/gameplay_metrics.py`; resultado em `baseline/metricas.json` |
| Leitura do código | `highlights.py` (motor), `presentation.ts`, `renderer2d.ts`, `renderer3d.ts`, `gesture.ts` | — |

**Atenção:** o playtest é **automatizado**, feito por um script que joga como um humano simples. Isto **não** é feedback humano. A aprovação da diversão depende do proprietário.

## 2. Crítica independente da V6

| Pergunta | Resposta | Evidência |
|---|---|---|
| O jogo é divertido? | Pouco. A jogada é uma sequência de **fotografias**: cada ação dura cerca de 0,3 a 1 s, e então tudo congela | Rajadas `sheet-burst-*`. Na 1ª imagem a bola já está viajando; na 2ª, o lance seguinte já está congelado |
| A movimentação lembra futebol? | Não. **26%** dos quadros de jogador têm aceleração acima de 10 m/s² (um atleta de elite chega a 6–8). **2%** dos quadros vão do parado a mais de 3 m/s em 0,1 s | `metricas.json`: `accel_over_10` = 264,6 por mil (11×11) e 339,2 por mil (5×5); `instant_start` = 20,2 por mil |
| O jogador parece controlar uma bola? | Não. Na condução, a bola é **posicionada** a cada passo (`carrier + heading·ahead`), num dente de serra de 0,5 s, e não tem física | `highlights.py` `_carry` |
| O domínio é natural? | Não. Ao chegar a 0,9 m do receptor, a bola **zera a velocidade** e é teleportada para 0,4 m do pé. O lance termina na hora | `_execute`, ramo `control` |
| A defesa reage corretamente? | Em parte. Três defensores fecham sobre o receptor, e antes do tempo de reação o defensor **fica parado** com a velocidade guardada | Rajadas; `move_players`, `continue` antes de `reaction` |
| O goleiro parece humano? | Não. Ele desliza de lado em velocidade constante (`gk.y += clamp`), sem aceleração, passada nem mergulho de verdade. A defesa é decidida num único teste de alcance no plano do goleiro, e o mergulho é só um rótulo (cue) para a animação | `_keeper_vs_shot` |
| Os ataques são variados? | Pouco. No 11×11 a IA **conduz 0,7 vez por partida**: quase tudo é passe. Os cenários nascem com todos parados | `balance_per_match.carries` = 0,7 |
| Os passes respeitam a intenção? | Em geral sim, com assistência moderada. O receptor é sempre o mais próximo do alvo | `_assist_receiver` |
| As animações têm continuidade? | Não. O cliente interpola **linearmente** posições a 10 Hz e deriva a orientação da diferença entre dois quadros. Isso gera giros instantâneos e a mesma pose de frente no 2D | `presentation.ts` `sample` e `facing` |
| A câmera 3D ajuda? | Pouco. Cerca de 35% da tela é arquibancada, os jogadores ficam pequenos e o rótulo do lance cobre o portador | `baseline-3D-*-mira.png` |
| Produto ou protótipo? | Protótipo jogável: as regras e o fluxo funcionam, mas a sensação de futebol não existe | — |

## 3. Causas raiz

| # | Prioridade | Sintoma | Componente | Causa | Situação | Correção na V7 | Teste de aceitação |
|---|---|---|---|---|---|---|---|
| 1 | P0 | Jogo em fotografias ("para e anda") | Orquestração e física | A ação acaba no instante em que a bola chega (domínio instantâneo) | Confirmada | O domínio em movimento faz parte da ação: primeiro toque e assentamento (cerca de 0,4 s), e a decisão só abre com a bola controlada | Duração média da ação; rajadas |
| 2 | P0 | Movimento robótico | Locomoção (`_steer`) | Aceleração limitada **por eixo** (o vetor chega a 13 m/s²), sem limite de curva nem de frenagem | Confirmada (métrica) | Locomoção vetorial: aceleração, frenagem e curva limitadas, com chegada suave (arrive). Os parâmetros vêm dos atributos | `accel_over_10` < 5 por mil |
| 3 | P0 | Bola colada na condução | `_carry` | Bola cinemática | Confirmada | Condução por **toques**: a bola tem física própria, o atleta a alcança e toca de novo. Entre toques, a bola fica exposta ao desarme | Distância da bola ao pé varia em ciclos; bola nunca teleporta |
| 4 | P0 | Goleiro artificial | `_keeper_vs_shot` | Deslize sem aceleração; mergulho só visual; defesa decidida num teste no plano | Confirmada | Agente goleiro com estados POSIÇÃO, PRONTO, REAÇÃO, PASSO, MERGULHO, CAÍDO e LEVANTANDO; deslocamento físico do mergulho; contato por varredura entre mãos e bola | Bateria de 13 chutes; nunca defende fora do alcance físico |
| 5 | P1 | Defensor congela e depois dispara | `move_players` | Antes do tempo de reação, a posição não integra | Confirmada | Durante a reação o defensor **mantém a inércia** (segue o vetor atual) | `instant_start` ≈ 0 |
| 6 | P1 | Giros instantâneos e pose sempre de frente | `presentation.ts` | Orientação derivada de quadros e interpolação linear | Confirmada | O servidor envia a orientação e o estado de ação por quadro; o cliente usa spline Catmull-Rom nas posições e interpola ângulos | Teste de `sample` |
| 7 | P1 | Bola sem peso | Física | Atrito constante de 5 m/s² e sem arrasto no ar; lançamento por parábola roteirizada (`air_left`) | Confirmada | Bola 3D integrada a 40 Hz: rolagem mais arrasto, gravidade, quique e arrasto no ar. O lançamento é balístico (velocidade inicial resolvida para a distância pedida) | Previsão do cliente igual ao servidor |
| 8 | P1 | Chute sem preparação | `_execute` | A bola sai no instante 0, na direção da mira, a 0,5 m do atleta | Confirmada | Preparação (virar o corpo e plantar o pé) antes do contato; erro maior quando a mira está longe da orientação do corpo | `KICK.windup` > 0 |
| 9 | P1 | Defesa inteira vai na bola | IA | Um pressionador mais marcação individual por proximidade; sem linha defensiva | Parcial | Papéis: pressionador (fica na frente e só dá o bote quando a bola fica exposta), cobertura, marcadores, **linha da defesa** comum e compactação | Rajadas; distância média ao portador |
| 10 | P1 | Ataques repetitivos, todos parados no início | `build_scenario` | Abertura estática | Confirmada | Abertura dinâmica (cada tipo de lance começa com velocidades); novos cenários de superioridade (3×2) | — |
| 11 | P1 | Arquibancada ocupa a tela no 3D | Câmera 3D | Inclinação e altura | Confirmada | Câmera mais baixa e mais próxima do lance, com o horizonte acima | Captura comparativa |
| 12 | P1 | Rótulo do lance cobre o portador | Interface | O chip "jogada x/8" fica no centro inferior | Confirmada | Chip movido para o topo | Captura |
| 13 | P2 | Ação rejeitada como "estado desatualizado" logo depois de uma nova decisão | Cliente | Gesto feito enquanto o cliente ainda mostrava o fim do lance anterior (revisão antiga) | Hipótese (1 caso em 9) | Acompanhar no playtest V7 | Taxa de 409 |
| 14 | P2 | Cruzamentos | `_header` | Disputa aérea simplificada; o goleiro não avalia a saída | Confirmada | O goleiro decide sair ou ficar pela previsão do ponto de queda | Cenário de cruzamento |
| 15 | P3 | Sprites 2D sem leitura de direção | `renderer2d.ts` | Usa a orientação derivada (item 6) | Confirmada | Corrigido junto com o item 6 | Captura |

## 4. Refatorar ou reconstruir

| Componente | Decisão | Por quê |
|---|---|---|
| `HighlightMatch` (máquina de estados, relógio, reconexão, idempotência, estatísticas, snapshot) | **Manter** | Funciona, tem testes e é o contrato de todos os modos |
| `Pitch` (física, locomoção, goleiro, IA, resolução da ação) | **Reconstruir** em `app/domain/football/` | Os defeitos P0 são estruturais: bola cinemática, domínio instantâneo, goleiro sem corpo e aceleração por eixo. Corrigir peça por peça manteria o modelo errado |
| `ai_action` (escolha da IA) | Reconstruir junto | Precisa avaliar o tempo de interceptação e a condução |
| `build_scenario` | Manter e acrescentar dinâmica de abertura e cenários de treino | A colocação por formação é boa |
| `presentation.ts` | Refatorar | Formato de quadro novo (orientação e estado), spline nas posições |
| `renderer2d.ts` e `renderer3d.ts` | Refatorar | Consomem a cena nova; ajustes de câmera, sprites e goleiro |

**Seleção.** A V6 continua intacta e selecionável. A V7 é escolhida por `HighlightMatch.engine`:

- o Lab usa a V7 por padrão, com seletor de motor;
- as partidas usam `GAMEPLAY_ENGINE`, cujo padrão continua `v6` até a aprovação do proprietário;
- partidas antigas (snapshots) seguem com o motor com que começaram.
