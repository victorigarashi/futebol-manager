# Partidas condensadas: duração configurável, transmissão 2D e motor

Branch: `feature/partidas-condensadas`, criada a partir de `main` (`9c3541d`).

## 1. Auditoria (Fase 1)

| Problema | Causa encontrada no código | Correção |
|---|---|---|
| A partida demorava demais | 180 s de jogo, mais 20 s de intervalo e 8 s de apresentação: cerca de 3,5 min por rodada, fixos no servidor. | O anfitrião escolhe 1:30 (padrão), 2:00 ou 3:00. O intervalo e o apito final cabem dentro desse tempo. |
| Os jogadores pareciam correr demais | Os 5400 s de jogo eram mostrados linearmente em 180 s, ou seja, **30× a velocidade real** (60× em 90 s). Um jogador a 7 m/s aparecia a 210 m/s na tela. | A transmissão é condensada: os lances aparecem a cerca de 2× a velocidade real e o resto passa em cortes. |
| Bola aos saltos e cantos a cada segundo | A interpolação era linear entre frames de 1 s e não sabia se a bola estava viajando ou parada. | Os frames agora informam o estado da bola (`viva`, `parada` ou `em voo`). Os jogadores seguem uma curva Catmull-Rom, a bola de passe anda em linha reta e a bola parada é reposicionada com fade. |
| Teleportes medidos no motor (6 partidas) | Escanteio: o cabeceador e o marcador "pulavam" até 25 m. Gol: a bola ia direto ao meio-campo. Reinício: o cobrador era trocado na hora. Goleiro: ficava a 20 m da posição do pontapé inicial. | O motor foi corrigido: os jogadores caminham até a área durante a paralisação, a bola fica na rede ou atrás da linha, e o cobrador é o mesmo que caminhou até a bola. Resta um único reposicionamento, no início do 2º tempo, escondido pelo cartão de intervalo. |
| Estilos agressivos geravam placares absurdos | O passe em profundidade completava até 90% das vezes e aceitava um recebedor até 5 m **impedido**. | O recebedor precisa estar em posição legal, e o sucesso do passe em profundidade foi recalibrado. |

## 2. Três relógios separados (Fase 3)

- **Tempo de simulação:** os ticks do motor (1 tick = 1 s de futebol, 5400 por partida). Não mudou.
- **Tempo de apresentação:** o ritmo em que esses ticks aparecem na tela. Nos lances, fica entre 1,5× e 2,6× a velocidade real (nas medições, média de ~2,0× em 3:00 e ~2,4× em 1:30). Os últimos 3 s antes de uma finalização ficam 40% mais lentos.
- **Duração da partida:** o tempo real escolhido pelo anfitrião.

O **diretor de transmissão** (`backend/app/domain/broadcast.py`) simula um pouco à frente da tela (no máximo ~9 minutos de jogo por etapa de planejamento) e monta uma linha do tempo com três tipos de segmento:

- `PLAY`: ticks mostrados de forma contínua.
- `CUT`: ticks pulados com uma transição de cerca de 1 s, em que o relógio gira, por exemplo "⏩ 34′ → 41′".
- `BREAK`: relógio parado (intervalo e apito final).

Como o orçamento de tempo é distribuído:

- O tempo real para futebol (a duração menos o intervalo, as aberturas e o apito) é distribuído uniformemente pelos 90 minutos.
- Cada momento candidato tem uma importância:
  - gol: 1,0;
  - finalização: 0,25 + 1,6×xG, com bônus se foi no alvo;
  - expulsão: 0,55;
  - ataque que chega ao terço final: cerca de 0,12.
- O momento entra na transmissão se couber no crédito de tempo, mais uma margem que cresce com a importância.
- **Gols entram sempre.** Quando o tempo aperta, o ritmo acelera, considerando a média de gols da própria partida. Há ainda 4 s reservados para um gol no fim do jogo; se ele não sair, esse tempo vira "minutos finais".
- Cada destaque começa onde o ataque começou (a posse), limitado a 16/22/28 ticks para 1:30/2:00/3:00.

Garantias, medidas pelos testes:

- **A duração é exata.** O apito final é planejado exatamente no prazo, com tolerância de teste de 0,05 s. No navegador, a partida mediu **119,6 s** com a duração em 2:00. Os clientes exibem a linha do tempo 1 s atrás do relógio do servidor, que o navegador estima pelas mensagens recebidas. Por isso **a duração não depende da máquina do jogador**.
- **Uma fonte de verdade para tudo.** Placar, relógio, eventos, estatísticas e posições exibidos vêm todos do tick que está na tela. O motor simula à frente, mas esse futuro nunca é enviado: eventos, frames, placares das outras partidas e até o rótulo do segmento em exibição ficam ocultos.
- **Linha do tempo determinística.** Os segmentos são acrescentados e nunca reescritos, e são salvos no snapshot. Depois de um reinício, o servidor planeja **exatamente a mesma transmissão** (há um teste para isso).
- **Comandos dos técnicos.** São aplicados na fronteira da simulação: o primeiro tick ainda não planejado, normalmente o próximo lance. O técnico vê na hora a ordem "agendada" e o minuto em que ela entra em campo. Substituições feitas durante o cartão de intervalo são trocas reais de intervalo e não gastam janela.

Números medidos (`cd backend && ../.venv/bin/python -m tools.broadcast_report --matches 6`), médias por partida 11×11:

| Duração | Chances mostradas | Ataques mostrados | Gols mostrados / gols | Velocidade nos lances | Apito final congelado |
|---|---:|---:|---:|---:|---:|
| 1:30 | 3,8 | 2,8 | 100% | 2,3× | 1,6 s |
| 2:00 | 4,3 | 4,7 | 100% | 2,1× | 2,4 s |
| 3:00 | 6,5 | 7,7 | 100% | 2,0× | 2,4 s |

O custo de CPU não muda: o motor simula cada tick uma única vez, cerca de 0,35 s por partida.

## 3. Configuração da sala (Fase 2)

- `RoomState.match_duration_seconds` aceita 90, 120 ou 180; o padrão é 90. A criação e a edição da liga usam um `Literal[90, 120, 180]`.
- `PUT /rooms/{id}/match-settings` serve para mudar a duração a qualquer momento:
  - só o anfitrião pode alterar (403 para os demais);
  - durante uma rodada em andamento, a mudança é recusada (409);
  - valores inválidos são recusados (422).
- A mudança é transmitida a todos pelo WebSocket como `room.match_settings`. Quem entra depois recebe o valor no estado da sala, e o valor sobrevive ao snapshot (snapshots antigos assumem 90).
- Cada rodada congela sua duração em `live_round.match_seconds`. As 10 partidas usam a mesma duração, inclusive as dos bots.
- Na interface, a seção **CONFIGURAÇÕES DA PARTIDA** com [1:30] [2:00] [3:00] aparece em três lugares:
  - no resumo da sala (lobby);
  - no diálogo de criação e edição da liga;
  - no pré-jogo de cada rodada.

  Para quem não é anfitrião, os botões ficam desativados, e todos recebem o aviso "O anfitrião mudou a duração das partidas para 2:00".

## 4. Movimento, jogadas e visual (Fases 4 e 5)

**Cliente** (`frontend/src/features/career/live/`):

- `broadcastClock.ts`: a linha do tempo e a estimativa do relógio do servidor (puro, testado).
- `frameBuffer.ts`:
  - interpolação Catmull-Rom para os jogadores;
  - bola presa ao pé de quem a tem, ou em linha reta durante um passe;
  - fade nos reposicionamentos;
  - nunca extrapola.
- `PitchCanvas.tsx`:
  - campo com faixas de corte, iluminação, redes com malha e área técnica;
  - marcadores com volume e goleiros com uniforme contrastante;
  - destaques: anel em quem tem a bola, pulso em quem finaliza, anel tracejado azul em quem acabou de entrar;
  - rastro na bola em voo e sombra que indica a altura;
  - cortes com fade entre dois momentos reais.
- `LiveMatchCenter.tsx`:
  - placar com a duração do jogo e um indicador de posse ao vivo;
  - aviso de corte com os lances do trecho pulado;
  - faixas de substituição e de mudança de postura;
  - aviso de conexão lenta;
  - ordens táticas "agendadas".

Durante um atraso de rede, o cliente segura o último frame recebido em vez de inventar movimento.

## 5. Testes (Fase 7)

- Backend: suíte completa em `pytest` (resultado no relatório final da entrega), mais `test_broadcast.py`, com 20 testes que cobrem os itens obrigatórios:
  - 90, 120 e 180 s em 11×11 e 5×5, e o padrão de 90 s;
  - só o anfitrião altera, sincronização e aviso via WebSocket, quem entra depois recebe o valor;
  - bloqueio durante a rodada e recusa de valores inválidos;
  - término dentro da tolerância, relógio virtual e intervalo;
  - ordem dos eventos, coerência entre placar, estatísticas e eventos;
  - ausência de teleportes (jogador < 9 m/s; bola viva < 45 m/s);
  - construção das jogadas (todo gol vindo de posse com passes mostra os passes);
  - substituição no intervalo;
  - reconexão e reinício com transmissão idêntica;
  - lookahead nunca vaza;
  - snapshot da sala.
- Frontend (`vitest`): 19 testes, incluindo:
  - curva suave passando pelos frames autoritativos;
  - jogador reposicionado nunca desliza;
  - passe em linha reta e bola ao pé do dono;
  - fade da bola parada;
  - mapeamento da linha do tempo, transição de corte e espera em atraso de rede;
  - estimativa do relógio do servidor.
- Navegador real (`frontend/scripts/verify-career.cjs`, Chrome, desktop e celular de 390 px): **24/24**, incluindo:
  - duração padrão 1:30;
  - só o anfitrião altera, e o outro técnico recebe o aviso;
  - corte da transmissão visível;
  - partida de 2:00 medida em 119,6 s;
  - mesmo placar final nos dois clientes;
  - nenhum erro de console.

  Capturas em `docs/evidencias/partidas-condensadas/`.

## 6. Limitações conhecidas

- **Combinações táticas extremas.** Se as duas equipes jogam "Direto" ou "Contra-ataque", ainda saem de 6 a 8 gols por jogo (com "Posse", 2,5). A recalibração reduziu o problema, mas não o eliminou. Os bots usam "Direto" quando estão perdendo, o que eleva a média de gols das partidas ao vivo. Recomendação: busca automática de parâmetros em lote.
- **Gols em sequência no fim.** Num jogo de 8 a 10 gols em 1:30, os últimos gols podem aparecer com apenas ~1–2 s de lance.
- **Comandos.** Entram no próximo lance planejado (fronteira da simulação), não no segundo exato que está na tela.
- **Velocidade no 5×5.** O campo de 40 m usa um ritmo 20% menor, mas com muitos gols os lances chegam a ~3×.
- **Contagem dos frames.** Os frames continuam a 1 por segundo de jogo; a suavidade vem da interpolação no cliente.
