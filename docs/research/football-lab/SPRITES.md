# Pipeline de sprites 2D e personalização compartilhada

## Pipeline (`sprites/bake.ts`, aba Sprites)

Atleta do lab → rig → clipe → câmera ortográfica elevada (52° por padrão, ajustável de 30° a 75°) → 8 direções (S, SE, E, NE, N, NW, W, SW) → **dois passes por célula**: SOMBRA (iluminado, branco) e MÁSCARA (sem luz, cores de ID por região) → **um atlas-máscara** → recoloração por uniforme no cliente.

- **Pixel do atlas-máscara.** R = sombra (posterizada, 6 níveis por padrão), G = região × 20 + 10, A = cobertura. As regiões são: pele, primária, secundária, calção, meião, chuteira, cabelo, luva e escuro.
- **O padrão do uniforme sobrevive.** O passe de máscara usa a textura da camisa com cores de ID, e as listras viram a região "secundária". É um atlas-máscara por família de padrão (5), não por time.
- **A recoloração custa uma passada nos pixels por time e aparência**, cerca de 30 ms para 1920×2400. Sai um contorno de 1 px para leitura sobre o gramado.
- **Medido no Intel UHD:**
  - 11 animações × 8 direções = 88 linhas, até 8 quadros, **704 células de 80 px**;
  - atlas de **1920×2400** (as linhas são redistribuídas em blocos para ficar abaixo de 4096 px no celular);
  - **cerca de 2,8 s** para gerar;
  - **17,6 MB** em RGBA na GPU por atlas. Com células de 64 px seriam cerca de 11 MB.
- **Animações no atlas:** idle, run, sprint, dribble, pass, shot, receive, header, celebrate, gk_ready e gk_dive. O JSON informa `contactFrame` para os clipes com contato.
- **Âncora nos pés** (no JSON). O sprite é desenhado na escala real e ancorado no ponto do pé. A "escala visual" da prévia, de 1× a 2,2×, só muda o desenho. **A colisão oficial não muda.**
- **Sem escorregar no 2D.** O quadro avança pela **distância percorrida ÷ passada medida no 3D**, e não pelo tempo.

**Evidências:**

- `evidence/sprite-atlas-mascara.png`, `sprite-atlas-mandante.png` e `sprite-atlas.json`;
- `40-sprites-2d.png` e `video-sprites-2d.webm`.

## Crítica

- Na escala real, um atleta de 1,82 m tem só cerca de 20 px numa câmera de 50 m. Ou o 2D usa câmera mais próxima (24–30 m, como no World Soccer Champs), ou uma escala visual de cerca de 1,5×. O V6 usa 2,2× (4,4 m), o que gera as "cabeças grandes" que o proprietário rejeitou. O lab mostra que **1,4–1,6× com câmera de cerca de 26 m** mantém as proporções e a leitura.
- O sombreado posterizado dá um ar "pixel art" limpo, mas o World Soccer Champs é mais liso. Para chegar perto: célula de 96 px, 8–10 níveis de sombra e um contorno mais suave.
- O número da camisa não fica legível em 80 px. O 2D deve desenhar o número por cima quando o jogador estiver de costas: o JSON indica a direção, então N, NE e NW.
- O mergulho no atlas é uma aproximação, com rolamento sintético. No 2D, a posição do goleiro também deve vir dos quadros da física (GOLEIRO.md).

## Estratégia compartilhada 2D/3D de uniformes e aparência

A mesma descrição vale para os dois renderizadores. Ela é a saída da escolha de uniformes que já existe (CIEDE2000, `kits.py`):

```ts
KitSpec  = { primary, secondary, pattern, shorts, socks, number, numberColor }
Cosmetic = { skin, hair, hairStyle, boots, build }   // vem do hash do id, nunca do nome nem da nacionalidade
```

- **3D:** uma textura de 256 px por jogador (padrão, número e rosto) mais cores por vértice. A malha e o esqueleto são compartilhados por estilo de cabelo e nível de detalhe.
- **2D:** um atlas-máscara por padrão, recolorido por time e aparência (2 times × 3 aparências = 6 atlas recoloridos numa partida).
- **Resultado:** nunca há milhares de modelos ou atlas. O sistema automático de contraste continua a decidir as cores, e a pipeline só as aplica.
