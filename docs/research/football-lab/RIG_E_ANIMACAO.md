# Atleta, rig e animação — especificação

## Atleta (Character Lab)

- **Malha em loft.** O tronco, cada perna e cada braço são **uma superfície contínua**, varrida ao longo da cadeia de juntas (`athlete/body.ts`). Cada anel é uma superelipse com meia-largura, meia-profundidade, deslocamento e expoente próprios. Os valores são medidas em metros de um atleta de 1,82 m: quadríceps, vasto medial, panturrilha, deltoide, bíceps, trapézio. O joelho e o cotovelo dobram como uma pele só. Não há cápsulas sobrepostas, como no V6.
- **Cabeça.** É uma esfera deslocada (mandíbula, queixo, nariz, arcos das sobrancelhas, maçãs e occipital). Há cinco estilos de cabelo, incluindo a cabeça raspada, como uma casca com afinamento até a linha do cabelo.
- **Rosto pintado.** O rosto é **pintado na textura do jogador** (olhos, sobrancelhas, lábios e sombreamento), com projeção planar e UVs presas à borda. Isso não custa geometria. A primeira versão usava elipsoides para os olhos, e eles pareciam óculos; foi descartada.
- **Uniforme.** É uma textura de 256 px por jogador com o padrão (liso, listras horizontais, listras verticais, faixa diagonal, metades), o número grande nas costas, o número pequeno no peito e um escudo fictício. A gola, o calção, a barra, os meiões, a chuteira e a sola vêm de cores por vértice.
- **Oclusão.** Uma oclusão barata vai embutida na cor dos vértices: escurece em direção ao chão, sob o queixo, entre as pernas e nas axilas.
- **Goleiro.** Mangas longas com volume, luvas brancas e mãos 22% maiores.
- **Orçamento medido** (triângulos por atleta, varia com o cabelo): alto 9,7–10,8 mil, médio cerca de 5,6 mil, baixo cerca de 3,2 mil (`data/performance-vsync.json`, `assetSizes`). O V6 tem 2.975, 4.838 e 6.386.

## Rig (21 ossos)

```
hips ─ spine ─ chest ─ neck ─ head
             └ chest ─ clavicleL ─ upperArmL ─ foreArmL ─ handL   (e o lado R)
hips ─ thighL ─ shinL ─ footL ─ toeL                               (e o lado R)
```

- **Unidades e eixos.** Metros, Y para cima, o atleta olha para **+Z**, pés em y = 0, 1,82 m. **"L" é a esquerda do próprio atleta, que é +X.** Esta convenção é a mesma do glTF: Y para cima, +Z para a frente do modelo.
- **Pose de bind.** Rotações identidade, só com deslocamentos. As proporções seguem Drillis & Contini para H = 1,82 m.
- **API de pose em graus anatômicos.** `hipFlex`, `knee`, `ankle` (positivo = plantiflexão), `toe`, `hipAbd`, `hipTwist`, `shFlex`, `shAbd`, `shTwist`, `elbow`, `wrist`, `clav`, `clavFwd`, `pelvis*`, `spine*`, `chest*`, `neckFlex` e `head*`, mais `rootX/Y/Z` em metros. `poseRotations` converte para os quatérnios dos ossos com Euler ZXY: torção, depois flexão, depois abdução. Ninguém escreve sinais de eixo à mão.
- **Pesos.** Mistura linear em metros em cada junta: 6–7 cm no tronco e nas pernas, 5 cm nos braços, 2 cm no pé e no dedo. Os ombros e a parte de cima do tronco seguem parcialmente as clavículas. O topo do calção segue as coxas.
- **Exportação.** A aba Characters tem o botão "Baixar GLB": `GLTFExporter` em binário, com malha, esqueleto, pesos e os 30 clipes assados. O tamanho medido está em `data/performance-vsync.json`.

## Biblioteca de animação (30 clipes)

| Categoria | Clipes |
|---|---|
| Locomoção | idle, walk, run, sprint, brake (frenagem), cut (mudança de direção) |
| Bola | dribble (condução com toque), pass_short, pass_long, cross, shot, first_time, receive, chest_control, header |
| Duelo e reação | stand_tackle, slide_tackle, fall, celebrate |
| Goleiro | gk_ready, gk_set (split step), gk_shuffle, gk_dive_low, gk_dive_high, gk_collapse, gk_jump, gk_catch, gk_parry, gk_getup, gk_throw |

**Como os clipes são escritos.** Os keyframes ficam em graus anatômicos, com tempo normalizado. A regra de apoio `ground: "L" | "R" | "lowest"` põe o pé no gramado por FK. Isso é calculado uma vez por clipe, numa tabela de 120 amostras suavizada na troca de pé. `lift` levanta o corpo nas fases de voo. O ciclo de marcha é escrito para a metade do pé esquerdo e espelhado. A amostragem usa Catmull-Rom por parâmetro. `bakeClip` gera o `THREE.AnimationClip` a 30 fps, com quatérnios por osso e a posição do quadril.

**Erros encontrados e corrigidos durante o trabalho:**

- As chaves de voo estavam apoiadas no pé errado, e o pé de balanço atravessava o gramado em 30 cm. Agora usam "lowest".
- A passada medida estava inflada em 40%, porque o ponto mais baixo da sola alterna entre calcanhar e ponta. Agora a medição compara sempre o mesmo ponto.
- No chute, a velocidade do pé no contato era de 10,7 m/s, irreal. Com o golpe em 0,1 s e o joelho ainda estendendo no contato, passou a **19,0 m/s**, dentro da faixa real de 18–25 m/s.

## Metadados: o contrato para integração

`clipMetadata()` gera os metadados; a versão gravada está em `data/clip-metadata.json`. Cada clipe tem:

```ts
{ name, label, category, duration, loop,
  contact?: { u, time, part },          // instante e parte do corpo que toca a bola
  plant?: { time, foot },               // pé de apoio plantado
  recovery?,                            // s após o contato até outra ação poder entrar
  speed?: [min, max],                   // velocidade da raiz para a qual o clipe foi feito
  direction, rootDriven?,               // rootDriven = a física move a raiz (mergulhos)
  stride?,                              // m por ciclo, medido por FK
  stance?: { L: [u0,u1], R: [u0,u1] },  // janelas de apoio
  contactFootSpeed }                    // m/s no contato (FK), para checar plausibilidade
```

**Uso pelo renderizador.** O motor emite "chute no instante t_s, bola em B, chutador olhando para h". O renderizador:

1. começa o clipe em `t_s − contact.time`;
2. posiciona o atleta para que o ponto de contato calculado por FK caia sobre B (`contactPoint` em `tabs/animation.ts`; o mesmo cálculo é feito em `tabs/goalkeeper.ts` para o chutador);
3. no quadro do contato, a bola sai com o vetor do servidor.

Assim a animação nunca decide o resultado.

## Escorregamento dos pés (medido, `data/foot-sliding.json`)

O motor move a raiz e a animação só escolhe a pose. O teste usa um trajeto reto com arrancadas, frenagens e meia-volta a 9 m/s². A tabela dá o deslizamento médio dos pés apoiados:

| Velocidade | Ingênuo (clipe no ritmo do autor) | Sincronizado (fase = v ÷ passada medida) | Sincronizado + IK de pé |
|---|---|---|---|
| 1,5 m/s | 45 cm/s | 54 cm/s | **13 cm/s** |
| 4,2 m/s | 224 cm/s | 212 cm/s | **34 cm/s** |
| 7,5 m/s | 552 cm/s | 519 cm/s | **205 cm/s** |

**Conclusões:**

- **Sincronizar a cadência sozinha não basta.** Com chaves feitas à mão, o pé gira em torno do tornozelo no contato do calcanhar e varre para trás a cerca de 2 m/s, mesmo com a fase correta.
- **O que resolve** é travar o **ponto real da sola** (calcanhar e depois a ponta, re-ancorando no rolamento) com IK de dois ossos (`anim/ik.ts`) e um limite suave de 22 cm. Isso reduz o deslizamento 6,6× na corrida e 3,6× na caminhada.
- **No sprint o resultado ainda é insuficiente: 205 cm/s.** A fase de apoio do sprint escrito à mão tem a varredura do pé irregular. A recomendação é captura de movimento (Mixamo, com parecer, ou uma gravação própria) ou um sprint escrito com o pé travado por IK desde a autoria.
- **Passadas medidas:** caminhada 1,48 m, corrida 2,83 m (cerca de 3,0 passos/s a 4,2 m/s), sprint 3,54 m (cerca de 4,5 passos/s a 8 m/s), condução 1,78 m e passo lateral do goleiro 0,31 m. Todas estão na faixa humana.

Na aba Animation, o modo "Locomoção" mostra as pegadas (azul = esquerda, vermelho = direita) e o medidor ao vivo. Os vídeos são `video-corrida.webm` (sincronizado + IK) e `video-deslize-ingenuo.webm`.

## Limites conhecidos

- O atleta ainda é **gerado em código**, sem textura de pele nem mapa de normais. A silhueta e a proporção são de atleta. O acabamento fica abaixo do DLS clássico, que usava texturas pintadas e animação capturada.
- Em poses extremas (braços acima da cabeça) o deltoide e o tronco se interpenetram um pouco. As peças sobrepostas não são costuradas.
- Os clipes foram escritos à mão. Os de bola convencem nos quadros-chave, mas não têm a microvariação da captura de movimento.
