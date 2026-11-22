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
