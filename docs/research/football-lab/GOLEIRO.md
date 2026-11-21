# Goleiro físico (Goalkeeper Lab)

O código está em `src/lab/football/keeper/sim.ts`: puro e determinístico, sem renderização, pronto para ser portado ao Python. A animação dirigida pela física fica em `keeper/animate.ts`, a interface em `tabs/goalkeeper.ts` e os testes em `tests/keeper.test.ts`.

## Diagnóstico do V6 (`highlights.py`, `_keeper_vs_shot`)

- O goleiro só se move de lado, em **velocidade constante**, sem aceleração e sem altura.
- O "mergulho" é um booleano: tempo maior que a reação mais 0,2 s. O alcance é um raio fixo.
- Se o contato não é "limpo", a defesa é um **sorteio**: `rng < 0,15 + 0,4·k`. Encaixe ou espalmada é outro sorteio.
- O cliente recebe só o evento "DIVE" e desenha o corpo deitado. **Não existe trajetória do corpo para animar**, e é daí que vem o "mergulho instantâneo".

## Modelo proposto

| Fase | O que acontece | Parâmetro (padrão "elite") |
|---|---|---|
| Reação | Nada muda até o goleiro perceber o chute | `reaction` 0,22 s (nota 45: 0,28 s; 92: 0,21 s) |
| Plano | Prevê onde a bola cruza o plano dele, simulando a mesma física da bola, com ruído de percepção opcional. Reavalia a cada 0,05 s | — |
| Escolha | Ver a lista abaixo | — |
| Passos laterais | Velocidade e aceleração limitadas | 3,0 m/s; 9 m/s² |
| Preparação | O centro de gravidade (CG) desce 12 cm e começa a ir para o lado. Ainda não decolou | `load` 0,12 s |
| Voo | O CG é **balístico**. A velocidade de decolagem é a necessária para o braço esticado terminar na bola, limitada a `diveSpeed` (lateral) e `jumpSpeed` (vertical). A inclinação do corpo segue os braços, de 0° (em pé) a cerca de 90° (horizontal) | 4,4 m/s; 2,9 m/s |
| Braços | Estendem em cerca de 0,18 s até `reach`, do CG à palma, e acompanham a bola dentro de cerca de 100° da direção do mergulho | 1,12 m |
| Contato | É **contínuo**: duas esferas de luva (raio de 10 cm) e uma cápsula do corpo contra a bola. Os subpassos da bola são de 4 cm ou menos | — |
| Encaixe ou espalmada | Encaixa se as duas mãos estão na bola e a velocidade relativa é menor que `catchMaxSpeed` × (1 − 0,45 × extensão). Senão espalma: reflexão na luva, absorção, e empurrão ativo do punho para fora e para longe do gol. **A bola espalmada continua na física**: pode entrar, bater na trave ou virar rebote | 24 m/s |
| Chão e recuperação | Aterrissa de lado e levanta | 0,75 s |

**Opções na escolha:**

- encaixar no corpo;
- dar passos laterais;
- mergulhar **cronometrado**: se sobra tempo, ele se aproxima nos pés e só decola quando falta o tempo de voo necessário;
- colapso, para bola rasteira perto;
- salto, para bola alta, com o envelope real do braço de cerca de 2,05 m em pé;
- sair do gol para agarrar um cruzamento: procura na trajetória o primeiro ponto alcançável e calcula a decolagem para chegar nesse ponto no instante certo;
- deixar passar a bola que vai para fora.

**Ruído de percepção.** É a única aleatoriedade, e só existe se for ligada. Ele erra a *estimativa* do goleiro, nunca o resultado. **Não há sorteio de defesa.**

## Erros encontrados e corrigidos

O primeiro protótipo tinha cinco problemas, todos corrigidos e cobertos por testes:

- decolava imediatamente em chutes lentos e pousava antes de a bola chegar;
- espalmava chutes de 18 m/s no peito;
- as mãos ficavam ao lado do corpo, e não à frente;
- as mãos não subiam, e a bola por cobertura passava 20 cm acima das luvas;
- no cruzamento, decolava com a velocidade da corrida e passava do ponto.

## Resultados (`data/keeper-scenarios.json`, mesmos chutes para todos)

| Cenário | GK 45 | GK 70 | GK 92 | Regra V6 (nota 70) |
|---|---|---|---|---|
| Central | CATCH | CATCH | CATCH | defesa garantida |
| Canto esquerdo rasteiro | **GOAL** | PARRY | PARRY | sorteio 43% |
| Canto direito rasteiro | **GOAL** | PARRY | PARRY | sorteio 43% |
| Ângulo esquerdo (alto) | GOAL | GOAL | GOAL | sorteio 43% |
| Meia altura à direita | PARRY | PARRY | PARRY | defesa garantida |
| De perto (8 m) | GOAL | GOAL | GOAL | não alcança |
| De longe (28 m) | PARRY | PARRY | PARRY | defesa garantida |
| Forte (32 m/s) | GOAL | GOAL | GOAL | sorteio 43% |
| Fraco (13 m/s) | CATCH | CATCH | CATCH | defesa garantida |
| Fora do alcance | GOAL | GOAL | GOAL | não alcança |
| Dentro do alcance | CATCH | CATCH | CATCH | defesa garantida |
| Rebote | **GOAL** | PARRY | PARRY | defesa garantida |
| Colocado (efeito) | **GOAL** | PARRY | PARRY | defesa garantida |
| Topspin | GOAL | GOAL | GOAL | defesa garantida |
| Cruzamento | WIDE | WIDE | **CATCH** (sai e agarra) | — |

**Leitura crítica:**

- A nota do goleiro passa a mudar resultados pela física: o goleiro 45 chega tarde nos cantos rasteiros.
- O V6 dá defesa garantida em 8 chutes. No topspin, nenhum goleiro físico alcança a bola que cai. No rebote e no chute colocado, o goleiro 45 sofre o gol e os outros só espalmam, sem encaixe.
- **O chute forte (32 m/s) é gol para todos**, mesmo depois de tocado. É fisicamente plausível, mas o balanceamento de jogo tem de decidir se o jogador vai achar isso justo. Os parâmetros ficam todos expostos na aba.
- O **cruzamento** só é agarrado pelo goleiro 92. Os outros não alcançam a tempo e deixam a bola passar. A decisão de *sair* precisa de mais cenários: atacante disputando, e soco quando não dá para encaixar.

## Animação dirigida pela física (sem teletransporte)

- O quadril segue o CG simulado, e o rolamento do corpo é a inclinação simulada.
- O clipe de mergulho é só **forma**, indexada pelo progresso: preparação de 0 a 0,24, voo de 0,24 a 0,62 e queda de 0,62 a 1.
- **Os dois braços são resolvidos por IK nas posições das luvas da simulação.** A luva visível está onde o teste de contato a colocou.
- O teste `the dive is progressive` exige inclinação abaixo de 20° na decolagem e acima de 34° no voo. O teste `never teleports` limita a velocidade do CG quadro a quadro.

**Evidências** (pasta `evidence/`):

- quadros `gk-left_low-*.png`, `gk-right_mid-*.png`, `gk-cross-*.png` e `gk-dip-*.png`;
- vídeos `video-mergulho.webm` e `video-defesas.webm`;
- tabela `20-goleiro-tabela.png`.

## O que falta para integrar

- Portar `simulateShot` para Python em `highlights.py`, no lugar de `_keeper_vs_shot`. Os frames passam a carregar CG, inclinação, progresso do mergulho e as duas mãos (cerca de 12 números por quadro, ou só em decolagem, contato e aterrissagem como "cues").
- A física da bola tem de vir junto: o goleiro prevê com a mesma física. Ver FISICA.md.
- Calibrar os parâmetros com o proprietário, no playtest da aba.
- O atacante disputando a bola no cruzamento e o soco ainda não existem.
