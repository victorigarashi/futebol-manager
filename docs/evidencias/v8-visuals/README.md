# V8 — Broadcast Visuals (evidências reais)

Capturas do Lab (`#lab`, motor V8, 11×11, qualidade alta), feitas com `frontend/scripts/v8visuals/capture.cjs` no Chrome headless (`--use-angle=gl`, iGPU Intel), no momento em que a decisão abre.

- `antes/`: o renderizador 3D em 21c68b6, antes desta frente.
- `depois/`: esta frente, em 1672×941, 1366×768, 1920×1080 e 390×844 (retrato).
- `comparativo-1672.png`: antes × depois.
- `referencia-vs-v8.png`: referências 01 e 06 do pacote × V8. As referências ficam só aqui, na montagem de comparação.
- `tamanhos.png`: outros tamanhos de tela.

Desempenho (`scripts/v8visuals/fps.cjs`, construção, 1672×941, headless/iGPU): low 57,5 · medium 55,7 · high 60,1 fps. Os valores ficam limitados pelo vsync, não pela GPU. Falta medir num celular real.

## O que mudou

- **Câmera de transmissão**, em `camera3d.ts`: fica alta na arquibancada principal, com lente fechada (26–29°), acompanha a jogada ao longo da lateral e, perto do gol, aproxima e enquadra portador, goleiro e gol. As câmeras de retrato, ampla, bola parada e cinemática continuam as do renderizador.
- **Estádio**, em `stadium3d.ts`:
  - gramado oliva com faixas largas, grão, desgaste e a sombra da arquibancada;
  - tonemapping ACES e luz de tarde;
  - muro azul-marinho com placas fictícias e grade;
  - arquibancadas inclinadas com torcida densa nas cores do mandante, corredores com escadas e cobertura com refletores;
  - bandeirinhas.

## Diferenças que ainda existem em relação às referências

- **Atletas:** ficam com cerca de 65% da altura vista nas referências e têm menos detalhe. A malha e as animações pertencem à frente de personagens e não foram mexidas aqui.
- **Torcida:** é pintada, então parece mais plana que a fotografia das referências.
- **Aprovação:** ainda não há aprovação visual do proprietário.

## HUD e câmera de retrato (branch feature/v8-hud-portrait, a partir de e658f12)

- **HUD**, baseado na referência 09. As regras foram só acrescentadas ao fim de `interactive.css`, sem mudar o markup.
  - Placar retangular plano: relógio numa célula lima, times em células claras e placar numa célula escura.
  - Botões de ação quadrados e claros; o selecionado fica lima.
  - Vale para 2D e 3D.
  - No celular, o chip da jogada saiu de baixo do banner "Sua jogada".
- **Câmera de retrato**, `portraitShot` em `camera3d.ts`: câmera de fundo, elevada.
  - O jogo corre na vertical, com o portador no terço inferior, acima da barra de ações.
  - A arquibancada do fundo e o gol aparecem no alto.
  - Perto do gol, o eixo gira para o gol.
- **Área clicável:** `scripts/v8visuals/hud-check.cjs` confirma que a faixa de até 120 px acima da barra de ações atinge `.im-input` em 2D e 3D, a 1672, 1366 e 390 px. Os 6 casos passam.
- **Evidências:**
  - `hud/comparativo-hud.png`;
  - `hud/antes|depois`;
  - `retrato/comparativo-retrato.png`;
  - `retrato/antes|depois`.
- **Desempenho no retrato** (390×844, headless/iGPU): 60 fps em low, medium e high.
- **Fora desta frente:** a linha de competição/rodada da referência 09 exigiria markup novo em `InteractiveMatch.tsx` e ficou de fora.
