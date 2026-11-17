# Diagnóstico e correção do 2D (Fases A e B)

Data: 17/11/2026. Branch `feature/modos-2d-redesign`, sobre `main` `0216532`.

## Resumo

O 2D parecia estranho por **causas medidas no motor e na transmissão**, não por desenho. O Canvas já desenhava corretamente o que recebia. O problema era o que recebia, e com que ritmo:

1. **Transmissão em avanço rápido.** Na partida de 1:00 (o padrão), as jogadas apareciam a 3,3× a velocidade real (mediana), 5,3× no p90 e até 6×. Mostravam só cerca de 4 s de construção antes do chute. Cada lance começava no meio do ataque.
2. **Movimento sem inércia.** Os jogadores trocavam de direção sem desacelerar. Em 13% dos pares de deslocamentos consecutivos houve inversão maior que 120°, e em 47% nas trocas de posse. O time inteiro "voltava" num único segundo.
3. **Finalizações sem trajetória.** O chute era resolvido no mesmo tick e a bola ia direto para a rede, as mãos do goleiro ou a linha de fundo. Como o quadro seguinte já era bola parada, o cliente aplicava o efeito de reposicionamento (sumir e reaparecer):
   - 64% dos chutes para fora sumiam em vez de voar;
   - 20% dos gols também.

   O goleiro não reagia ao chute.
4. **Futebol frenético e irreal.** Em produção, com bots e elencos reais, o 11×11 tinha:
   - **5,7 gols por partida**, 48 chutes e cerca de 560 trocas de posse;
   - cerca de 620 passes por time e 71% de acerto;
   - COUNTER vencendo POSSESSION por 3,2 × 0,9 entre times idênticos;
   - 5×5 com **11,75 gols**.

   Origem confirmada por instrumentação:
   - **Interceptação na geometria errada.** No passe falho, o interceptador era o adversário mais próximo da linha do passe **desde o primeiro metro**. Um atacante que pressionava o goleiro "interceptava" chutões de 40 m na entrada da área e marcava. 22 de 35 gols nasciam de passe curto do goleiro ou de zagueiro interceptado no próprio terço.
   - **Perder a bola não tinha custo de transição.** O valor da posse adversária no campo de ataque é quase zero, então passes arriscados eram quase grátis.
   - **Taxa de desarme por tick alta demais.** Eram cerca de 160 desarmes por partida (o real fica entre 35 e 45).
   - **Bônus de infiltração do COUNTER/DIRECT** e aversão a risco muito diferente entre estilos.
   - **Reação dos bots em vantagem.** Recuavam (COUNTER + LOW) a partir dos 70', o que deixava escapar 13 de 28 vantagens: 42 a 57% de empates.

A câmera **não foi alterada** (decisão do usuário: manter "Campo inteiro" e "Dinâmica" como estão).

## Como foi medido

Scripts de auditoria simulam partidas reais (catálogo, elencos, bots, plano tático dos bots) e leem os quadros autoritativos do motor: 1 quadro = 1 tick = 1 s de jogo. Métricas usadas:

- inversões de direção (ângulo entre deslocamentos consecutivos maior que 120°, com mais de 1,5 m cada);
- salto da bola no tick do chute;
- origem de cada troca de posse e de cada gol;
- composição da transmissão: segmentos PLAY e CUT, ritmo em ticks por segundo, duração dos lances.

## Correções

| # | Onde | O quê |
|---|---|---|
| B1 | `domain/broadcast.py` | Perfis com mais construção (1:00 → até 20 ticks; 3:00 → 38) e ritmo menor (2,3 → 2,0 ticks/s). Correção de ritmo limitada a 0,8–1,3× (era 0,65–1,8×). Num gol, primeiro encurta-se a construção, depois acelera-se até 1,6×; além disso só quando o prazo exige. O lance começa 8 ticks antes da recuperação da bola. |
| B2 | `match_engine._move_agents` | **Inércia**: cada jogador tem velocidade; a mudança por tick é limitada (4,5 m/s² na linha e 6 no goleiro), com frenagem na chegada. Teleportes de reposicionamento zeram a velocidade. |
| B3 | `match_engine._shoot` e `_record_frame`; cliente `frameBuffer.ts` e `PitchCanvas.tsx` | O tick do chute recebe estado 3: a bola **voa** até onde o chute terminou (rede, mãos do goleiro, fora, bloqueio), com rastro. O goleiro **mergulha** em direção ao chute, alcançando a bola na defesa e ficando curto no gol, sem nenhum sorteio novo. Em defesa ou bloqueio que vira escanteio, o chute termina no goleiro ou no bloqueador; o escanteio é montado na paralisação. |
| B4 | `match_engine._pass` | Interceptação só onde a bola pode ser ganha: bola longa na metade final do trajeto, passe rasteiro a partir de 15% do caminho. Linha de interceptação reduzida de 6 m para 4 m. |
| B5 | `match_engine._decide` | Custo fixo de perder a bola (`TURNOVER_COST`), maior perto do próprio gol. O goleiro só joga curto para companheiro livre com linha limpa; sob pressão, chuta longe. Sem passe atravessado para companheiro marcado na própria área. |
| B6 | `match_engine` (constantes) | Desarmes por tick: 0,055 / 0,060 / 0,080, conforme a pressão. Domínio antes de decidir (0,78/0,68). Aversão a risco próxima entre estilos. Bônus de infiltração reduzidos. COUNTER defende num bloco 1,5% mais baixo. DIRECT com progressão 1,12. |
| B7 | `bot_coach.decide` | Em vantagem, o bot mantém o plano; só recua um passo com 2 gols de vantagem depois dos 75'. Atrás no placar, a pressão é gradual (+1 aos 62', DIRECT só aos 80'). |
| B8 | `PITCH.finish_scale` | Recalibrado depois de B2–B7: 11×11 0,70; 5×5 0,36. O fator entra antes de registrar o xG, então o xG exibido continua sendo a probabilidade usada. |

Invariantes preservados:

- simulação determinística (mesma semente e mesmos comandos dão a mesma partida);
- placar igual aos eventos;
- autor e assistência sempre do time certo;
- nenhum evento futuro vazado;
- duração da partida exata;
- 100% dos gols mostrados.

## Antes e depois

### Motor em produção (elencos reais e bots)

| | Antes | Depois |
|---|---|---|
| 11×11: gols por partida | 5,7 | **2,40** em 80 partidas (Brasileirão real: cerca de 2,3 a 2,5) |
| 11×11: chutes por partida | 47,7 | 34–36 |
| 11×11: trocas de posse por partida | 559 | 413 |
| 11×11: empates | 20–57% (oscilava com os bots) | 25–35% |
| 11×11: inversões bruscas de direção | 13,2% | **5,2%** |
| 11×11: inversões nas trocas de posse | 47% | 22,6% |
| 5×5: gols por partida | 11,75 | 5,7–6,0 |
| 5×5: inversões bruscas | 33% | 12,9% |
| COUNTER × POSSESSION (times idênticos) | 3,19 × 0,88 | 1,46 × 0,81 |
| Gols com bola recuperada e chutada pelo mesmo jogador | 75% | 27% |
| Duração da posse antes do gol (mediana) | 3 ticks | 11 ticks |
| Chutes cuja bola "sumia" em vez de voar | 64% dos chutes para fora; 20% dos gols | **0** |

### Transmissão de 1:00 (padrão)

| | Antes | Depois |
|---|---|---|
| Lances por partida | 10,6 | 8 |
| Lance mediano | 12,6 ticks em 4,2 s | 14,4 ticks em 6,7 s |
| Ritmo mediano / p90 / máximo | 3,3× / 5,3× / 6,0× | 2,3× / 3,9× / 3,9× |
| Gols visíveis | 100% | 100% |

### Transmissão de 3:00

| | Antes | Depois |
|---|---|---|
| Construção mostrada antes do lance (mediana) | 5,5 ticks | 9,6 ticks |
| Lance mediano | 13 ticks em 6,4 s | 16,4 ticks em 9,4 s |

## Testes

- `test_match_balance.py`:
  - mix de estilos com faixas realistas;
  - **nenhum estilo domina** (antes o COUNTER vencia por mais de 2 gols);
  - faixas do espelho sintético atualizadas: times idênticos de 72 jogando posse são cautelosos de propósito.
- `test_broadcast.py`: amostra do teste de construção ampliada de 6 para 12 partidas, porque o motor calibrado marca menos entre times idênticos.
- `frameBuffer.test.ts`: o chute voa (estado 3) e a bola parada sendo posicionada continua com transição.

## Limitações conhecidas

- **Bloco MUITO DEFENSIVO.** Com os dois times muito defensivos saem mais gols que com dois muito ofensivos. Isso já existia antes e não foi corrigido nesta fase: o bloco baixo fica alinhado à bola e deixa a área atrás dele. Os bots não usam esse nível; um humano que o use para segurar um placar se expõe. Fica registrado para uma próxima calibração.
- **5×5 chuta muito.** São cerca de 160 chutes por partida num campo pequeno; o placar é realista (cerca de 6 gols) graças à calibração da finalização.
- **Partida de 1:00.** Mostra cerca de 8 lances: todos os gols e as chances que cabem. É a escolha consciente de priorizar jogadas compreensíveis a mostrar tudo acelerado.
