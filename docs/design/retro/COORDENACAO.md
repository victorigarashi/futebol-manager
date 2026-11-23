# Retro Career: componentes visuais compartilhados e coordenação entre frentes

Situação em 2026-11-23. A única sessão ativa além desta é a da frente Football V8 (`feature/football-v8-integrated`). As frentes Manager Intelligence, Identity & Social, Football Experience e Tactical Engine não têm sessão nem branch ativa. Este documento serve de contrato para quando forem retomadas. Ninguém deve copiar estes componentes: todos devem importá-los.

## O que é compartilhado e quem usa

| Peça | Arquivo | Uso pelas frentes |
|---|---|---|
| Tokens (céu, painel, tinta, turquesa, lima, tipografia condensada) | `features/retro/retro.css` (`.rt`) | Todas. Não criar paleta paralela. |
| Moldura e cenário (`RetroFrame`, `RetroStage`) | `features/retro/primitives.tsx` | Telas novas de carreira, perfil, notícias e pré/pós-jogo. |
| Navegação (`RetroNav`, `RetroSubNav`) e rodapé de comandos reais (`RetroFooter`) | idem | Não listar atalhos que não funcionam. |
| Tiles (`.rt-tile`, `data-rt-tile`) e navegação por setas (`useTileNav`) | `retro.css` e `useTileNav.ts` | Hubs de Mercado, Competições e Clube na propagação. |
| Camisa (`Shirt`) e ícones de traço (`TileArt`) | `primitives.tsx` | Campo tático, Draft e Pack. |
| Escudo (`ClubCrest`) e foto (`PlayerPhoto`) | `components/` | Já são os componentes oficiais. A frente V8 confirmou que não vai alterá-los. |
| Projeção do campo (`project`, `surname`) e desenho (`PitchArt`) | `features/career/lineup.ts` e `LineupBoard.tsx` | Elenco, visão geral, pré-jogo e táticas. |

## Limites com cada frente

- **Football V8 / Football Experience (partida, HUD, áudio, replay, pré/pós-jogo):**
  - A HUD da partida (`InteractiveMatch.tsx`, `interactive.css`) pertence à frente V8. O Retro Career não reestiliza a HUD.
  - Pedidos para a tela de partida vão para a sessão V8. Pedido em aberto: a linha de competição/rodada da referência 09.
  - O pré/pós-jogo só recebe a moldura retrô quando a Football Experience definir o fluxo.
- **Tactical Engine:**
  - O tile Táticas mostra só `squad.strategy` e o efeito vindo do servidor. O Entrosamento usa `squad.cohesion`.
  - Nenhum slider ou opção tática nova na UI enquanto o contrato oficial não existir.
- **Manager Intelligence:**
  - Notícias, caixa de entrada e relatórios devem consumir os eventos reais do servidor. A Central já deriva as manchetes do estado da carreira.
  - Textos gerados por IA entram como dados num contrato, não dentro dos componentes.
- **Identity & Social:**
  - Perfil do técnico, convite, presença e conexão aparecem nas placas do topo (`rt-plate`, `Connection`, convite).
  - Avatar e nome vêm do perfil real, sem campos inventados.

## Decisões que aguardam o proprietário

1. Aprovação visual das 10 interfaces da prévia (`/avaliacao/index.html`).
2. Escala fluida da interface em 1920×1080 ou mais (hoje o layout cresce, mas a tipografia continua no tamanho de 1366).
3. Depois disso, propagar para Mercado, Táticas, Competições, Perfis, Notícias, Estatísticas e demais modos.
