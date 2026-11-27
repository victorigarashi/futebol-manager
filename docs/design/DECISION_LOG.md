# Registro de decisões — Modo Jogável

Este registro só cresce. Uma decisão antiga é marcada como **substituída**, nunca apagada.

| Data | Decisão | Situação |
|---|---|---|
| 20/11/2026 | Um único motor autoritativo (`highlights.py`), compartilhado pelo 2D, pelo 3D e por todos os modos | Em vigor |
| 20/11/2026 | 3D com estética voxel inspirada no Mini Soccer Star | **Substituída** em 21/11/2026 |
| 21/11/2026 | Escala física real: 11×11 com 105×68 m e gol de 7,32×2,44 m; 5×5 com 50×32 m e gol de 4×2 m. O uniforme oficial é escolhido pelo servidor (CIEDE2000) | Em vigor |
| 21/11/2026 | **A nova direção artística do 3D é semirrealista, com atletas humanos articulados, inspirada no Dream League Soccer clássico.** | Em vigor |
| 21/11/2026 | O Mini Soccer Star continua como referência de mecânica: momentos decisivos e arraste. O World Soccer Champs continua como referência do 2D | Em vigor |
| 21/11/2026 | **Mira mínima**, igual no 2D e no 3D: só uma linha tracejada com uma bolinha no destino. Saem a seta, o cone, os limites laterais, o % no gramado e os anéis de recebedores. O % fica, discreto, junto aos controles | Em vigor |
| 21/11/2026 | O atleta 3D é modelado em código: SkinnedMesh com esqueleto humanoide de 13 ossos e animação procedural sobre os ossos. O voxel fica como alternativa (`localStorage bm_3d_style=voxel`) | Em vigor; ver ASSET_LICENSES.md |
| 21/11/2026 | **Football Engine V7**: o núcleo de jogo (`Pitch`) foi reconstruído em `app/domain/football/`. A V7 traz bola física a 40 Hz, locomoção com aceleração, frenagem e curva, domínio em movimento, condução por toques, agente goleiro com corpo e IA por papéis. A orquestração `HighlightMatch` e os contratos foram mantidos (docs/v7) | Em vigor no Lab; **competições seguem na V6 até a aprovação do proprietário** (`GAMEPLAY_ENGINE`) |
| 21/11/2026 | O quadro V7 envia a orientação e o estado de ação de cada atleta. O cliente interpola com spline Catmull-Rom e não deriva mais a pose das diferenças de posição | Em vigor (V7) |
| 21/11/2026 | A pausa para decisão abre só **depois** do domínio: a jogada assenta em cerca de 0,4 s e os atletas ficam congelados em movimento | Em vigor (V7) |
| 21/11/2026 | Câmera 3D mais inclinada e próxima: o portador fica acima da barra de ações e a arquibancada sai do quadro. No 2D, a câmera "Jogada" pode olhar além da lateral, para a jogada de ponta não ficar sob o placar. O rótulo "jogada x/8" foi para o topo | Em vigor |
| 26/11/2026 | **Câmera 3D configurável**: Transmissão, Cooperativa, Dinâmica, Tática e Personalizada, com altura, distância, zoom, FOV, ângulo vertical, deslocamento lateral e suavidade. Aplicada na hora, salva só neste navegador; nunca altera o resultado nem a tela do adversário | Em vigor |
| 26/11/2026 | A bola 3D gira pela rolagem sem escorregamento (`rollStep`, derivada do deslocamento oficial); cada atleta ganhou sombra de contato e os recebedores do passe ganharam marcadores no 3D | Em vigor |
| 27/11/2026 | **O fim da partida tem estado próprio na tela**: `inplay` → `finished` (apito, aguardando o registro) → `settled` (resultado gravado). O placar final é preservado mesmo quando o endpoint responde `NONE`, e a tela de resultado oferece a saída; a carreira não depende mais de atualizar a consulta no instante exato do registro | Em vigor |
| 27/11/2026 | A consulta do Modo Jogável desacelera (1,2 s) no apito e **para** quando a sessão sai da rodada; o laço de quadro lê o relógio por `ref` e não é recriado a cada consulta | Em vigor |
| 27/11/2026 | `Renderer3D.dispose()` libera atletas, materiais, texturas e o contexto WebGL ao sair da partida | Em vigor |
