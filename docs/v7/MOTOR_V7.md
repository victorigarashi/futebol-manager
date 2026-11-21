# Football Engine V7: arquitetura, física, IA e contrato

- **Branch:** `feature/gameplay-v7`.
- **Código:** `backend/app/domain/football/`.
- **Auditoria que motivou cada decisão:** `docs/v7/AUDITORIA_CRITICA.md`.

## 1. Camadas

| Camada (conceito do pedido) | Onde | O que faz |
|---|---|---|
| Football Game Core | `football/world.py` | Atletas, bola, locomoção, colisões entre corpos, previsão da trajetória |
| | `football/keeper.py` | Agente goleiro |
| | `football/brain.py` | IA coletiva: papéis de ataque e de defesa |
| | `football/play.py` | Uma ação: preparação, contato, bola livre, recepção, condução por toques, desarmes, cabeceios, traves, gol |
| | `football/choice.py` | Decisão da IA com a bola (bots, tempo esgotado, desconexão) |
| | `football/scenario.py` | Movimento na abertura do lance e treinos do Lab |
| Football Match Orchestrator | `highlights.HighlightMatch` (**mantido**) | Relógio, oportunidades, decisão com cronômetro, idempotência, reconexão de 30 s, IA que assume, estatísticas, snapshot |
| Football Presentation | `frontend/.../interactive/render/presentation.ts` → `renderer2d.ts` e `renderer3d.ts` | Só desenham os quadros oficiais |
| Integration Layer | `season_service.py`, `lab_service.py`, rotas | Inalterada, exceto pela escolha do motor |

**Um único motor autoritativo.** O cliente não simula nada. A previsão da linha da mira integra **a mesma equação** do servidor (`gesture.ts`, `rollDistance`) e é só uma previsão.

## 2. Seleção do motor

- `HighlightMatch.engine` vale `"v6"` ou `"v7"`. É gravado no snapshot: uma partida termina com o motor em que começou.
- **Partidas competitivas** usam `GAMEPLAY_ENGINE`, cujo padrão é **`v6`**. A V7 só entra em competições depois da aprovação do proprietário: basta `GAMEPLAY_ENGINE=v7`.
- **Football Lab** usa `v7` por padrão, com seletor V7/V6 para comparação.
- Nenhuma configuração experimental aparece nas salas.

## 3. Tempo

| Grandeza | Valor | Motivo |
|---|---|---|
| Passo físico | 0,025 s (40 Hz), fixo | Colisões estáveis e sem atravessar a bola. Determinístico e independente do FPS do cliente |
| Quadros enviados | 0,1 s (10 Hz) | O payload continua do tamanho da V6; o cliente interpola com spline |
| Replanejamento da IA | 0,2 s (5 Hz), com histerese | Intenções estáveis, sem mudar de ideia a cada quadro |
| Ação mais longa | 7 s | Contra ataque infinito; depois disso decide quem estiver mais perto |

**Custo medido.** Uma partida 11×11 inteira, IA contra IA, fica em torno de 0,25 s de CPU (`gameplay_metrics.py`: 30 partidas por formato em cerca de 8 s, num processo).

## 4. Atleta e locomoção

| Atributo usado | Origem |
|---|---|
| Velocidade máxima | 5,9 + 3,1 × ritmo/100 (de 7,4 a 8,7 m/s) |
| Aceleração | 4,6 + 3,6 × aceleração/100 m/s², sendo **aceleração = 0,7 ritmo + 0,3 drible** (derivada) |
| Frenagem | 1,3 × aceleração |
| Curva | Aceleração lateral máxima de 4,2 + 4,6 × agilidade/100, sendo **agilidade = 0,55 drible + 0,45 ritmo** (derivada) |
| Rotação do corpo | 5,5 + 4 × agilidade/100 rad/s |
| Equilíbrio | 0,6 físico + 0,4 drible (derivado), usado na disputa de bola |
| Aceleração total | Nunca passa de 9,5 m/s² |
| Condução | Velocidade com a bola = (0,80 + 0,15 × drible/100) × máxima |

O catálogo só tem seis atributos (PAC, SHO, PAS, DRI, DEF, PHY) mais os de goleiro. Os derivados estão escritos aqui e no código; nenhum valor foi inventado.

**Locomoção** (`world.move`): é um perfil de chegada que freia para parar **sobre** o alvo. A aceleração é decomposta:

- ao longo da velocidade, para acelerar ou frear;
- lateralmente, para fazer a curva.

Cada componente tem o seu limite. Daí nascem curvas em arco, sem giro instantâneo nem parada seca.

**Contato entre corpos.** Um empurrão de no máximo 5 cm por passo, e os corpos perdem a velocidade de aproximação.

## 5. Bola

- **Integração:** `ball_step`, a 40 Hz.
- **No chão:** a desaceleração é 2,6 + 0,010·v² m/s². Por exemplo, um passe a 14 m/s rola 27,9 m.
- **No ar:**
  - gravidade e arrasto de 0,0105·v²;
  - quique com restituição vertical de 0,52, mantendo 86% da velocidade horizontal.
- **Passe:** v₀ = 6,5 + 19,5·força. O erro de ângulo cresce com:
  - a pressão;
  - a força;
  - o quanto o corpo precisa virar;
  - a velocidade do atleta.
- **Lançamento e cruzamento:**
  - balístico, com a velocidade inicial **resolvida** (`solve_loft`) para cair a (12 + 46·força) m;
  - o ângulo é mais alto em bolas curtas (cavadinha).
- **Chute:**
  - v₀ = 15 + 19·força;
  - subida = 0,6 + 8,6·max(0, força − 0,35), mais o erro do atributo;
  - a bola sai **no instante do contato**, depois da preparação (corpo virando e pé de apoio). O cliente recebe o `windup`.
- **Assistência moderada:** se um companheiro está a até 0,24 rad da linha desenhada, o passe é corrigido em 35% a 70% do ângulo, na direção de onde ele estará. Num passe para o espaço vazio, nada é corrigido.

## 6. Posse, recepção e condução

**A bola nunca é colada ao atleta.** Ela só fica nos pés:

- durante a preparação do chute;
- no instante final em que a ação termina.

**Recepção** (`receive`). A qualidade é:

`0,72 + 0,32·controle − 0,016·max(0, v − 11) − 0,15·pressão − 0,1·(bola alta) − 0,06·(de costas)`

Ela leva a um de três resultados:

- **domínio limpo:** primeiro toque na direção da corrida, nunca para fora;
- **toque pesado:** a bola espirra viva;
- **deixar passar.**

Depois do domínio vêm cerca de 0,4 s de assentamento por toques. A próxima decisão só abre com a bola controlada, **e todos continuam em movimento**.

**Condução por toques** (`touch` e `dribble_step`):

1. O atleta toca e a bola rola à frente: cerca de 3,2 m em espaço livre, 2,2 m com marcação e 1,3 m sob pressão, valores menores para quem dribla bem.
2. Ele corre para alcançá-la e toca de novo.
3. Entre os toques a bola fica **exposta**.

**Desarme.** Um defensor só dá o bote se alcança a bola ou o corpo. A chance é:

`0,27 + (marcação − drible)/160 + (físico − equilíbrio)/400 + 0,28·exposição + pressão do lance − (agilidade − 60)/500`

- **Sucesso:** rouba a bola ou a cutuca, que fica livre.
- **Fracasso:** o defensor fica "batido" por 0,75 s, com aceleração reduzida.

**Interceptação.**

- Um defensor só se compromete com o ponto da trajetória que alcança **antes da bola e antes do receptor**, com reação de 0,1 s.
- Comprometido, a chance é 0,24 + 0,44·marcação/100 − 0,022·(v − 10). Se ele falha, desvia a bola.
- Um defensor que só estava perto do caminho da bola tem chance de 0,04 + 0,20·marcação/100.

## 7. Goleiro

**Estados** (`keeper.py`): POSITIONING, SET, reação, STEP, JUMP, DIVE, DOWN, RISE, HOLD e CLAIM.

**Posicionamento.** Na linha entre o centro do gol e a bola, a 0,6 a 3,6 m da linha do gol, sem abandoná-lo. Diante de um finalizador próximo, ele sai.

**Reação.** O tempo de reação, contado a partir do **contato real**, é:

`0,30 − 0,16·goleiro/100` s, mais 0,07 s se a visão estiver tapada

Antes disso ele só mantém a inércia.

**Decisão.** Prevê o ponto de cruzamento da trajetória real e escolhe:

- passo lateral (até 3,6 + 1,4·goleiro/100 m/s);
- salto, para bola alta;
- ou mergulho, um compromisso único com lançamento lateral de 3,4 + 2,6·goleiro/100 m/s. O **corpo realmente se desloca**: isso está nos quadros.

**Contato.** É um teste de varredura entre o caminho da bola e as mãos:

- em pé: uma janela frontal da largura dos braços, do gramado até o alcance;
- no mergulho: o segmento do quadril às mãos, na altura escolhida.

Depois do contato, a defesa é decidida pelo manejo: encaixa, espalma (o rebote continua vivo) ou toca sem evitar o gol. **Uma bola fora do alcance físico nunca é defendida.**

**Bateria de testes** (`tools/keeper_battery.py`, 40 sementes por cenário):

| Cenário | Resultado |
|---|---|
| Chute fraco e central | Defendido 36 a 39 vezes em 40 |
| Bola alcançável a 20 m | Defendida 37 a 40 vezes em 40 |
| Canto fora do alcance a 9 m | 0 defesas em 120 chutes |
| Canto a 16 m | Goleiro 55 sofre 13 gols em 40; goleiro 75 sofre 6; goleiro 90 sofre 1 |

Resultado completo: `docs/evidencias/v7/depois/goleiro_bateria.json`.

## 8. IA coletiva

**Ataque:**

- dois apoios curtos em ângulos com linha de passe livre;
- pontas abrindo o campo;
- centroavante na linha do último defensor, que **corre em profundidade** quando o portador pode jogar para frente;
- ataque à área (primeiro pau, segundo pau, marca do pênalti) em cruzamentos;
- segurança atrás da bola;
- tabela: quem passa continua correndo.

**Defesa:**

- **um** pressionador, que acompanha goleiro-lado e não se joga;
- cobertura;
- marcadores goleiro-lado;
- **linha comum**;
- compactação para o lado da bola.

**Táticas existentes:**

- estilo: profundidade, amplitude, apoio;
- mentalidade defensiva: altura do bloco;
- pressão: distância do bote e segundo pressionador.

**Dificuldade** (fácil, normal, difícil) muda só o tempo de reação, o ruído da decisão e a agressividade. **Nunca os atributos.**

**IA com a bola** (`choice.py`) é uma utility AI. Ela pesa:

- chute, pelo xG;
- passe ao pé e passe em profundidade, pelo **tempo de cada defensor até a linha de passe**;
- cruzamento;
- condução.

## 9. Contrato com os renderizadores

**Quadro V7** (`step.layout = "v7"`):

`[t, bola_x, bola_y, bola_z, (x, y, orientação, estado) × atleta]`

- Coordenadas normalizadas no campo real; orientação em radianos no espaço em metros.
- O espelhamento do 2º tempo é feito **uma vez** no servidor: a posição é refletida e a orientação ganha π.

**Estados por atleta:**

| Código | Estado |
|---|---|
| 0 | Normal |
| 1 | Chute |
| 2 | Domínio |
| 3 | Desarme |
| 4 | Cabeceio |
| 5 | Batido |
| 6 | Goleiro pronto |
| 7 | Mergulho |
| 8 | Encaixe |
| 9 | Caído |
| 10 | Levantando |
| 11 | Conduzindo |
| 12 | Salto |
| 13 | Passo lateral |

**Na decisão**, `opportunity.motion` traz a orientação e a velocidade de cada atleta: o corpo fica congelado em movimento.

**Interpolação no cliente:**

- atletas: spline Catmull-Rom, que passa por todos os pontos oficiais;
- bola: linear.

**Cues.** Os mesmos da V6 (KICK com `windup`, CONTROL, TOUCH, TACKLE, DRIBBLE, INTERCEPT, DEFLECT, BLOCK, HEADER, DIVE, SAVE, CLAIM, POST, BAR, GOAL, OUT), mais `level` no mergulho.

**Física para a mira:** `view.physics` com `model: "v7"` e `roll`.

## 10. Football Lab (`#lab`)

- Partida completa contra o bot.
- 10 cenários de lance: os nove da V6 e a superioridade 3 × 2.
- 5 treinos isolados, só na V7: atacante × goleiro, 2 × 1, 3 × 2, contra-ataque 3 × 3, cruzamento e área.
- Formato 5 × 5 ou 11 × 11, 2D ou 3D, dificuldade e motor.
- Semente, com o botão **↺ Repetir**, que reproduz a mesma situação.

## 11. Ferramentas de medição

| Ferramenta | O que mede |
|---|---|
| `backend/tools/gameplay_metrics.py` (`ENGINE=v6\|v7`) | Naturalidade e equilíbrio sobre os quadros oficiais |
| `backend/tools/keeper_battery.py` | Goleiro |
| `frontend/scripts/playtest-lab.cjs` | Playtest **automatizado** pela interface real: vídeo, rajadas de quadros, mira e latência |
| `frontend/scripts/verify-interactive.cjs`, com `backend/tools/interactive_acceptance.py` | Dois navegadores, um em 2D e outro em 3D, na mesma partida |
