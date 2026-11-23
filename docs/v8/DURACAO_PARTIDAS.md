# Duração real das partidas do Modo Jogável

**Ferramenta:** `backend/tools/match_duration.py`.

**O que mede:** o relógio lógico do servidor. A ferramenta aplica as transições oficiais com um relógio falso e soma o tempo real gasto em cada estado da partida.

**O que fica de fora:** não há navegador, script de teste nem renderização. O resultado isola o tempo do próprio jogo.

**Amostra:** 6 partidas por linha, com médias. A faixa (mínimo–máximo) está em `docs/evidencias/v8/duracao.jsonl`.

## 11×11

| Motor | Técnicos | Duração real (s) | Relógio | Intervalo | Decisões humanas | Execução das ações humanas | Lances dos bots (replay) | Faixas de resultado |
|---|---|---|---|---|---|---|---|---|
| V6 | Só bots | 145 | 22,5 | 6 | — | — | 95,9 | 20,7 |
| V7 | Só bots | 140 | 22,5 | 6 | — | — | 90,9 | 20,7 |
| **V8** | Só bots | **140** | 22,5 | 6 | — | — | 90,7 | 20,7 |
| V8 | Humanos decidem na hora | 109 | 22,5 | 6 | 6,0 | 54,9 | — | 20,1 |
| V8 | Humanos levam 2 s | 149 | 22,5 | 6 | 45,9 | 54,8 | — | 20,1 |
| V8 | Humanos levam 5 s | 208 | 22,5 | 6 | 104,8 | 54,7 | — | 20,1 |
| V8 | O cronômetro de 10 s esgota (a IA decide) | 483 | 22,5 | 6 | 345,0 | 88,9 | — | 20,7 |
| V6 | O cronômetro de 10 s esgota | 603 | 22,5 | 6 | 476,7 | 76,8 | — | 20,7 |

## 5×5

| Motor | Técnicos | Duração real (s) |
|---|---|---|
| V6 / V7 / V8 | Só bots | 110 / 104 / 110 |
| V8 | Humanos decidem na hora / 2 s / 5 s | 85 / 119 / 169 |
| V8 | O cronômetro esgota | 412 |

## Conclusões

1. **A V8 não é mais lenta que a V6.** A estrutura do tempo é a mesma: relógio de 22,5 s, intervalo de 6 s e cerca de 20 s de faixas de resultado. A execução das ações humanas dura 54,9 s contra 51 s na V6. Os lances dos bots duram 90,7 s contra 95,9 s.
2. **O tempo de uma partida com humanos é dominado pela decisão de cada técnico.** São cerca de 23 decisões numa partida 11×11 com dois humanos. Cada segundo de reflexão por decisão soma cerca de 20 s à partida.
3. **O 3D não muda a duração.** A linha do tempo oficial não depende do renderizador. Uma renderização lenta só atrasa o *gesto* do técnico, e isso entra como "decisão".
4. **O timeout dos testes multiplayer não era lentidão do jogo.** A janela de 560 s terminou perto do minuto 80 porque:
   - o script automatizado demora a gesticular no 3D em renderização por software (SwiftShader);
   - várias decisões esgotaram o cronômetro de 10 s, e cada uma custa até 10 s.

   **Aumentar o timeout do teste não "corrige" nada no jogo.** Os testes finais medem a partida inteira até o apito, e o tempo do script é registrado separadamente (`multiplayer-final/*/timing.json`).

## Problema de produto encontrado (preexistente, não introduzido pela V8)

**A duração configurada da sala (1:00 / 1:30 / 2:00 / 3:00) não é aplicada às partidas do Modo Jogável.**

- Ela vale para o Modo Técnico: a rodada termina em `ends_at`.
- No Modo Jogável, a rodada espera as partidas interativas terminarem.
- Só com bots, a partida já leva cerca de 140 s no 11×11. Com dois humanos ela leva de 2,5 a 8 minutos, conforme o tempo de decisão.

**Opções** (decisão do proprietário; **nada foi alterado**):

- **A.** Escalar o relógio, a quantidade de momentos decisivos e as pausas para caber na duração escolhida. Com 1:00, seriam poucas oportunidades e pausas curtas.
- **B.** Tratar a duração configurada como "duração da simulação". A partida jogável continua durando o que os técnicos levarem, e a sala avisa isso.
- **C.** Um limite total por partida: quando o tempo acaba, a IA joga as decisões restantes.

**Recomendação:** A + C para salas competitivas e B para amistosos/Lab.
