# Sprint e deslize dos pés: causa raiz e correção (V8)

## Métrica

A métrica é a velocidade média dos pontos de sola **apoiados**: calcanhar ou ponta abaixo de 2 cm. Ela usa o mesmo medidor do Research Lab (`Locomotion.meter`) e é dada em cm/s.

O mesmo ponto de sola é comparado entre amostras, então rolar do calcanhar para a ponta não conta como deslize.

São dois percursos:

- o `RootDriver` reto da pesquisa, com acelerações, paradas e meia-volta;
- um percurso a velocidade constante.

Teste: `frontend/src/lab/football/tests/sprint.test.ts` (e `anim.test.ts`).

## Diagnóstico

A pesquisa já sincronizava a fase pela passada (velocidade ÷ passada) e travava o pé por IK. Restavam 110 cm/s no sprint. Aumentar o limite do travamento não resolvia.

A amostragem do clipe `sprint` por FK mostrou duas falhas **de autoria**, e não de locomoção:

1. Entre u = 0,25 e 0,35, o pé que avança **atravessava o gramado em até 23 cm**. O apoio do clipe continuava em "L" (o pé que decola), e o corpo era posicionado por ele.
2. Sem a penetração, o mesmo pé passava a **tocar o chão 45 cm à frente e ficar parado ali por 0,25 de ciclo**, sem recuar. Para o olho e para o medidor, é um pé apoiado deslizando para a frente na velocidade do corpo.

## Correção

1. **Nenhuma parte de nenhum pé abaixo do gramado.** O apoio escolhido define a altura do corpo, mas nunca abaixo do pé mais baixo. Vale para todos os clipes.
2. **Voo real.** Nos clipes de marcha que declaram janelas de apoio, o corpo:
   - é sustentado pelo pé de apoio dentro da janela;
   - fica no ar entre as janelas, num arco suave (pico = `lift` do clipe).
3. **Fase casada à distância** (`matched+ik`).
   - Mede-se, ao longo do clipe, quanto o ponto de sola apoiado recua (a curva S(u)).
   - A fase avança pela **distância percorrida**: u = S⁻¹(distância).
   - Com o pé apoiado, a velocidade dele no mundo é zero por construção, a qualquer velocidade.
   - O voo é esticado ou encolhido para que o ciclo siga uma **cadência humana**: 2,0 + 0,27·v passos/s, o que dá cerca de 3,1 a 4,2 m/s e 4,3 a 8,5 m/s.
4. O IK de pé continua, agora só para resíduos laterais e verticais.

**A velocidade oficial do atleta não foi alterada.** Só a animação se ajusta ao deslocamento do servidor.

## Resultado

Percurso da pesquisa, com acelerações, paradas e meia-volta. Os valores são médios, em cm/s.

| Velocidade | Antes (pesquisa, `synced+ik`) | V8, mesmo modo com o novo apoio | V8 `matched+ik` |
|---|---|---|---|
| 1,5 m/s (caminhada) | 9,9 | 9,9 | 9,1 |
| 4,2 m/s (corrida) | 25,6 | 18,7 | 11,8 |
| **7,5 m/s (sprint)** | **110,0** | 38,8 | **26,5** |
| 8,5 m/s | — | 46,1 | 28,1 |
| Curva a 8,5 m/s | — | 35,4 | 23,8 |

**A velocidade constante** (diagnóstico, sem acelerações) dá 4,3 cm/s a 4,2 m/s e 14,7 cm/s a 7,5 m/s.

## O que ainda falta

- O resíduo vem das transições: arrancada, frenagem e mudança de direção, quando a postura muda dentro do ciclo.
- Um clipe de sprint capturado (mocap, com licença verificada) ou refeito no Blender reduziria mais o resíduo. O código já aceita a troca, porque a fase vem da medição do próprio clipe.
- No 2D, o quadro do sprite avança pela distância oficial (o "stride" da cena). Lá não há medição de deslize por pixel.
