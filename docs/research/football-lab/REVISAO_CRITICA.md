# Revisão crítica independente

Este documento não aprova nada só porque funciona. A nota final fica com o playtest do proprietário.

## Critérios de aceitação do briefing

| Critério ("não aceitar…") | Situação | Evidência |
|---|---|---|
| Personagem humano deslizando | **Parcial.** Caminhada 10 cm/s e corrida 26 cm/s com IK. **O sprint ainda desliza: 110 cm/s** | `data/foot-sliding.json`, `video-corrida.webm` contra `video-deslize-ingenuo.webm` |
| Corrida sem flexão natural | Atendido: joelho de 100–128° no balanço, fase de voo, braços com cotovelo a cerca de 90° | `06-perfil-sprint.png`, `video-corrida.webm` |
| Chute sem contato | Atendido. O contato é um quadro definido no clipe, a bola é posicionada por FK e o pé chega a 19 m/s | `10-chute-contato.png`, `video-chute.webm` |
| Goleiro teleportando | Atendido. A velocidade do CG é limitada e verificada por teste | `tests/keeper.test.ts`, `video-mergulho.webm` |
| Mergulho instantâneo | Atendido: preparação de 0,12 s, decolagem depois da reação e inclinação progressiva (teste) | quadros `gk-left_low-*.png` |
| Sprite estático durante a corrida | Atendido. O quadro avança pela distância percorrida | `video-sprites-2d.webm` |
| Movimentação coletiva artificial | **Parcial.** Perseguidores e espaçamento estão bons, a tabela fecha e o cruzamento é aéreo. **A ultrapassagem é só parcial** | `data/ai-scenarios.json`, `video-coletivo.webm` |
| Bola colada ao atleta | Atendido no protótipo de condução (toques na bola solta). **O V6 ainda cola a bola** | `video-conducao.webm`, gráfico 6 de `30-fisica.png` |
| Modelos incompatíveis com o navegador | Atendido. É gerado em código e exporta GLB pelo `GLTFExporter` | aba Characters |
| Performance sem diagnóstico | Atendido com números medidos (PERFORMANCE.md). Só o iGPU Intel; **sem medição em celular** | `data/performance-*.json` |
| Recurso sem licença verificada | Atendido. Nada de terceiros foi commitado | LICENCAS.md |

## Perguntas por protótipo

**Atleta 3D.**

- *Convincente?* A silhueta, as proporções e o uniforme convencem a distância de TV e a meia distância. **De perto, ainda parece um modelo low-poly sem textura de pele.** Está melhor que o V6 (cápsulas) e que o CC0 da Quaternius (estilizado), mas **não chega ao DLS clássico**, que usava texturas pintadas à mão, mapa de normais e captura de movimento.
- *Alternativa melhor?* Sim. Uma base MakeHuman (CC0) ou modelada no Blender, com textura pintada e o **mesmo rig de 21 ossos**, que a API de pose e os clipes já usam (ver HANDOFF_V7.md).

**Animações.**

- *Parece futebol?* O chute, o passe, o cabeceio, o carrinho e o encaixe têm preparação, contato e acompanhamento corretos.
- *Movimento humano?* A corrida e a caminhada, sim. O sprint escrito à mão é o elo fraco (110 cm/s de deslize).
- *Acompanha a física?* Sim na locomoção, com fase e IK. Nas ações, o contato é sincronizado por metadado.

**Goleiro.**

- *Reage naturalmente?* A decisão (ficar, deslizar, mergulhar no tempo certo, sair) e o corpo (CG balístico, braços por IK) são coerentes. **A pose de voo tem as pernas um pouco rígidas**, e a recuperação do chão é simples.
- *A bola tem peso?* Tem: a espalmada sai com absorção e empurrão, e o rebote continua na física.
- *Rápido o suficiente?* Uma simulação completa leva poucos milissegundos (os 18 testes rodam em menos de 0,5 s).

**Física.**

- Os modelos são clássicos e baratos. **O termo de grama (k = 0,22) foi calibrado por plausibilidade, não por dados de tracking.** Precisa de validação.

**IA.**

- O bloco defensivo e a disciplina de pressão estão bons. A tabela e o cruzamento aéreo funcionam. **A ultrapassagem ainda é parcial.** Ainda é um protótipo 2D.

**Sprites.**

- A pipeline funciona e resolve a personalização. A estética posterizada é diferente da suavidade do WSC, e precisa de ajuste de células e níveis.

**Integração e licença.**

- Todos os módulos são puros (TS) ou independentes do gerenciamento. A licença é toda original.
- A física e o goleiro **precisam ser portados para Python** para virarem oficiais. O lab não é uma segunda fonte de verdade.

## Comparação com as referências

Não incluímos imagens de DLS, WSC, Mini Soccer Star ou Score! Hero: são material protegido. A comparação abaixo é por características.

| Característica | Referência | Lab | Distância que falta |
|---|---|---|---|
| Atleta 3D | DLS 2016–19: cerca de 3–5 mil triângulos com textura pintada (rosto, dobras do uniforme) e animação capturada | Cerca de 9,7 mil triângulos (alto), sem textura de pele e sem mapa de normais, rosto pintado simples, animação escrita à mão | Textura e captura de movimento, não polígonos |
| Goleiro | DLS: mergulho animado com bloqueio de mão perto da bola | Mergulho físico com mãos por IK na bola (mais honesto que um clipe fixo) | Pernas e queda mais expressivas |
| 2D | WSC: sprites lisos, câmera de cerca de 25–30 m, jogadores levemente maiores que o real | Sprites gerados do 3D, câmera de 24–30 m, escala de 1,4–1,6× | Suavidade (mais níveis de sombra), número da camisa |
| Mecânica | Mini Soccer Star e Score! Hero: arrastar com trajetória visível | Mira mínima aprovada (tracejado e ponto no destino real, com arrasto e efeito) | — |
