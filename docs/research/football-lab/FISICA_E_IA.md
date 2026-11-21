# Física e IA coletiva

## Física da bola (`physics/ball.ts`, testes em `tests/physics.test.ts`)

| Fenômeno | Modelo | Parâmetro |
|---|---|---|
| Arrasto | Quadrático com crise de arrasto: Cd 0,45 abaixo de 8 m/s, 0,22 acima de 12 m/s | m 0,43 kg; r 0,11 m |
| Efeito Magnus | Cl = S, onde S = rω/v, limitado a 0,3. A direção é ω × v. Topspin faz a bola cair, efeito lateral +z curva para a esquerda | — |
| Deslizar e rolar | Atrito de Coulomb com momento de esfera **oca** (I = 2/3·m·r²). Sem rotação, a bola rola a 3/5 da velocidade inicial | μ deslizamento 0,55 |
| Rolamento | Resistência c·g, mais um termo de grama proporcional à velocidade, mais arrasto | c 0,065 (dentro do teste FIFA de 4–10 m na rampa); k 0,22 s⁻¹ (**calibrado, a confirmar com tracking**) |
| Quique | Restituição dependente da velocidade (0,72 → 0,55), com impulso tangencial que altera a rotação | atrito no impacto 0,45 |
| Trave e travessão | Esfera varrida contra cilindros, com subpassos de 4 cm ou menos (sem atravessar). e = 0,7 | — |

## Comparação com o V6 (mesmas entradas; gráficos em `evidence/30-fisica.png`)

| Medida | V6 | Proposto |
|---|---|---|
| Passe a 15 m/s: alcance | 22,5 m (desaceleração constante de 5 m/s²) | cerca de 30–40 m, com deslize e rolamento (teste: entre 25 e 45 m) |
| Chute de 30 m/s a 20 m | 29 m/s (1,5 m/s² constante) | 70–86% da velocidade inicial (teste), pelo arrasto do ar |
| Lançamento | Parábola fixa de 3,2 m, com velocidade horizontal constante | Balística com arrasto e backspin. A altura depende da velocidade e do ângulo (30 m: cerca de 3,4 m; 45 m: cerca de 6 m) |
| Efeito | Não existe | Curva lateral e queda por topspin |
| Aceleração na diagonal | **12,4 m/s²** com nominal 8,8: o limite é aplicado *por eixo* em `_steer`, o que dá √2 | 9,6 m/s² (círculo de atrito) |
| Corte de 90° a 7 m/s | Trajetória em "L" | Curva limitada pela aderência (7,5 m/s²) |
| Arrancada (ritmo 80) | 10 m em 1,63 s; 30 m em 4,03 s | Modelo força-velocidade dentro da faixa profissional, verificado por teste: 10 m entre 1,7 e 2,0 s, 30 m entre 4,0 e 4,5 s |
| Condução | A bola fica num dente de serra preso ao jogador | Toques numa bola solta: a bola sai, desacelera, o jogador alcança e toca de novo |

**Achado principal.** O `_steer` do V6 limita a aceleração separadamente em x e em y. Isso explica parte da movimentação "artificial": arrancadas na diagonal 41% mais fortes e mudanças de direção em "L". A correção é pequena e pode ser feita no próprio `highlights.py`: limitar o **vetor**, com o componente tangencial e o lateral separados. Ver `steer()` em `physics/player.ts`.

**Frequência do motor.** `DT = 0,1 s` é grosso demais para a bola: um chute de 30 m/s anda 3 m por passo. O protótipo usa subpassos (1/240 s, ou 4 cm). A recomendação é manter os quadros de 10 Hz para o cliente e subdividir a física da bola internamente. O custo em Python é de cerca de 1.700 passos por ação, que é desprezível.

## IA coletiva (`ai/tactics.ts`, aba Football AI)

**Técnicas:**

- **Tempo até interceptar.** Reação, mais tempo para frear ou virar, mais o modelo força-velocidade, usando a velocidade atual do jogador.
- **Controle de campo.** logistic((t_def − t_ataque) / 0,45 s).
- **Segurança do passe.** Nenhum defensor chega à linha antes da bola (com o mesmo modelo de rolamento), multiplicada pelo controle do receptor.
- **Utility AI para quem está sem a bola.** Combina controle, ameaça (superfície do tipo xT), passe possível, espaçamento, corredor da função, impedimento, esforço, "passa e se move", ultrapassagem e ruptura, com histerese.
- **Defesa em bloco.** O bloco desliza com a bola. Há **um** pressionador escolhido pelo tempo até a bola (não pela distância), que se aproxima pelo lado da linha de passe mais perigosa, fazendo a sombra de cobertura. Há uma cobertura atrás dele. Os outros marcam a zona e ficam entre o atacante e o gol. Um passe só é interceptado por quem chega fisicamente antes da bola.

**Medições** (`data/ai-scenarios.json`, 8 s por cenário, semente 1), comparadas com um baseline em que todos perseguem a bola:

| Cenário | Perseguidores médios (IA / baseline) | Espaçamento médio dos atacantes (IA / baseline) | Fim |
|---|---|---|---|
| 2 contra 1 | 0,31 / 0,95 | 12,5 / 4,9 m | — |
| 3 contra 2 | 0,11 / 1,68 | 15,4 / 7,2 m | — |
| Contra-ataque | 0,19 / 2,51 | 13,6 / 6,2 m | — |
| Ataque organizado | 0,85 / 4,51 | 12,0 / 5,6 m | interceptação |
| Passe em profundidade | 0,66 / 1,25 | 12,0 / 11,1 m | finalização |
| Tabela | 1,36 / 2,45 | 7,1 / 2,2 m | — |
| Ultrapassagem | 0,50 / 2,41 | 12,7 / 5,6 m | — |
| Cruzamento | 0,11 / 2,48 | 15,3 / 7,6 m | — |
| Defesa compacta | 0,66 / 5,19 | 11,6 / 5,0 m | interceptação |
| Pressão alta | 0,33 / 1,86 | 15,3 / 10,1 m | — |

**Correções feitas depois da primeira rodada.** Foram achadas no registro de eventos:

1. O passador "dominava" o próprio passe 0,2 s depois, e por isso a tabela nunca fechava.
2. O portador jogava passes com só 48–55% de segurança.
3. O cruzamento era rasteiro e cortado no meio do caminho. Agora é aéreo e só pode ser disputado perto da área de queda.
4. O portador inicial "achava" que estava com a bola havia 9 s (`lastPass = -9`). Por isso todos os cenários começavam com um passe instantâneo, e a regra de segurar a bola para a ultrapassagem nunca disparava.
5. A ultrapassagem perdia para "ficar parado" por causa da penalidade de estar perto do portador.

**Leitura crítica:**

- **O espaçamento e a disciplina estão bons.** Ninguém persegue a bola sem função, e o bloco fica compacto.
- **A tabela agora fecha** (#9 → #10 → #9). A métrica de "perseguidores" no cenário da tabela (1,36) inclui o passador correndo ao lado da bola, o que nesse caso é o comportamento desejado.
- **O cruzamento agora é aéreo** e é dominado na área.
- **A ultrapassagem é parcial.** O ponta segura a bola até 1 s e o lateral avança, mas o lateral recebe pela meia (6 s), e não do ponta. Falta um gatilho de combinação explícito.
- **Os cenários são só posições iniciais.** Todo o comportamento vem da mesma IA, sem roteiro.
