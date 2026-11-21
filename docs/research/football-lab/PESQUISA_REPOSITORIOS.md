# Pesquisa técnica de repositórios — Football Lab

Data: 21/11/2026. As licenças, as estrelas e a data do último push vêm da API pública do GitHub, consultada nesta data (`data/` não guarda essa consulta; ela pode ser refeita com `curl https://api.github.com/repos/<repo>`).

Quatro repositórios de futebol foram clonados com `--depth 1` e tiveram o código lido: striker-3d, GoalDao, websoccer e Yuka. Nenhum código de terceiros foi executado na máquina, e nenhum foi copiado para o projeto.

## Futebol e IA

| Repositório | Licença | Situação | O que foi verificado | Utilidade para o Brasileirão Manager |
|---|---|---|---|---|
| google-research/football | Apache-2.0 | **Arquivado** (último push em 06/2025) | Motor C++ completo com bots e ambiente de aprendizado por reforço | Serve como referência conceitual de estados de jogo e recompensas. Não serve como dependência: usa C++ nativo e não roda no navegador, e o projeto já tem motor autoritativo |
| rcsoccersim/rcssserver | LGPL-3.0 | Ativo | Servidor 2D da RoboCup: percepção com ruído e stamina | Inspirou o ruído de percepção opcional do goleiro (`perceptionNoise`). A licença LGPL desaconselha incorporar código |
| Mugen87/yuka | MIT | Ativo | O playground atual tem só *blackjack*, *hideAndSeek* e *shooter*: **o exemplo de futebol não está mais no repositório** | Os steering behaviors (arrive, pursuit, separation) foram reimplementados à mão em `physics/player.ts` e `ai/tactics.ts`. Não vale importar a biblioteca inteira |
| kendrekaran/striker-3d | **sem licença** no código | Ativo, sem estrelas | Lido `AIController.js`: o goleiro mergulha em velocidade constante (`GK_DIVE_SPEED`), e a animação de **carrinho** é reaproveitada como mergulho ("low lunge visual doubles as a dive"). O posicionamento acompanha o ângulo e avança quando a bola se aproxima | É um exemplo do que **não** fazer no mergulho. O posicionamento por ângulo é parecido com o adotado (bissetriz). Traz um GLB da Quaternius com licença CC0 (ver LICENCAS.md) |
| Swarup113/GoalDao | **sem licença** | Uma estrela | `game.js` com 830 linhas: jogo 2D simples | Nada aproveitável. Sem licença, não pode ser reutilizado |
| markclausing/websoccer | MIT | Ativo | Jogo 2D com constantes bem comentadas. Tem um mecanismo de posse de bola do goleiro com tempo máximo (`KEEPER_HOLD_TICKS`, `KEEPER_HOLD_MAX`) | Mostra a ideia de limitar a posse do goleiro para evitar bloqueio do jogo. Também traz o comentário "limitar demais deixa a bola baixa mas vence o goleiro", que reforça que a altura do chute decide defesas |
| red3d.com/cwr/steer (Reynolds) | Artigo | — | Seek, arrive, pursuit, separation | Base de `steer()` (arrive com distância de frenagem) e do `tti()` |

## Física

| Repositório | Licença | Avaliação |
|---|---|---|
| dimforge/rapier | Apache-2.0 | Excelente (WASM, determinístico). Exagerado para uma bola e 22 cápsulas, e o motor oficial está em Python. **Não adotado.** A física proposta (`physics/ball.ts`) tem cerca de 200 linhas, sem dependência, e pode ser portada para Python |
| pmndrs/cannon-es | MIT | Sem push desde 01/2024. Não tem rolamento com rotação de esfera oca nem Magnus. **Não adotado** |
| bulletphysics/bullet3 | zlib, mas a API reporta NOASSERTION | C++. Faz sentido só se houver ragdoll de queda no futuro |

## Modelagem humana

| Recurso | Licença | Avaliação |
|---|---|---|
| makehumancommunity/makehuman e mpfb2 | Código AGPL/GPL. Os assets exportados são CC0, segundo a documentação do projeto (a API reporta NOASSERTION) | É a melhor fonte para um corpo de referência realista, mas **exige Blender**, que não está disponível neste ambiente. Recomendado para a próxima etapa (ver HANDOFF_V7.md) |
| blender/blender | GPL (o resultado exportado é do autor) | Ferramenta. Indisponível nesta máquina |
| Mixamo | Termos da Adobe | Permite usar em produtos, mas restringe redistribuir os arquivos. Num jogo web o GLB é baixável. **Precisa de parecer** antes de usar |
| Quaternius | CC0 1.0 | O "Animated Men" (via striker-3d) foi inspecionado: 1.854 triângulos, 31 juntas com pés e mãos, e 11 clipes genéricos (andar, correr, pular, soco, espada…) **sem nenhum clipe de futebol**. O estilo é low-poly estilizado. Útil como referência de rig CC0 e de orçamento. Não atinge o visual do DLS clássico |
| mesh2motion.org | — | Não testado (precisa de interface web e upload). Fica como candidato para o retargeting de animação |
| Sketchfab | Licença por modelo | Não foi feita curadoria. Seria preciso verificar a licença de cada modelo |

## Renderização, otimização e testes

| Repositório | Licença | Uso |
|---|---|---|
| three.js | MIT | Já é dependência. O lab usa `SkinnedMesh`, `AnimationMixer`, `GLTFExporter`, `OrbitControls` e `BufferGeometryUtils` |
| react-three-fiber e drei | MIT | **Não adotados.** O renderizador atual é imperativo, e trocar por eles não melhora a jogabilidade |
| glTF-Transform e meshoptimizer | MIT | Recomendados para a etapa de GLB final: `gltf-transform optimize --compress meshopt`. Não foram instalados porque o atleta do lab é gerado em código, e o GLB exportado dele é medido em PERFORMANCE.md |
| google/draco | Apache-2.0 | Alternativa ao meshopt. O meshopt é preferível para malhas com skin, porque decodifica mais rápido e preserva os pesos |
| KTX-Software | Apache-2.0 | Para os atlas recoloridos por time (ETC1S/UASTC). **O atlas-máscara não pode ser comprimido com perda**, porque o canal G guarda IDs |
| pixijs e phaser | MIT | O 2D atual em Canvas já desenha os sprites do lab (`drawImage` de um atlas). O PixiJS só se justifica se o 2D passar de cerca de 30 sprites com efeitos |
| LibreSprite | GPL-2.0 | Ferramenta de edição. A pipeline do lab gera os sprites a partir do 3D, então não é necessária |
| Kenney | CC0 | Os "Sports Packs" são estilizados (cabeça grande) e não atendem a direção artística |
| Playwright | Apache-2.0 | Já usado. `scripts/football-lab/evidence.cjs` gera todas as capturas e os vídeos |
| Spector.js | MIT | Útil para inspecionar draw calls manualmente. As métricas do lab vêm de `renderer.info`, que é suficiente para contar chamadas e triângulos |

## Jogos de futebol open source com jogabilidade demonstrável

Nos quatro jogos de futebol lidos, nenhum tem goleiro físico. Todos decidem a defesa por velocidade constante e um raio fixo, ou por sorteio. O striker-3d é o mais completo, e mesmo nele o mergulho é a animação de carrinho reaproveitada. Isso confirma que o goleiro físico do lab (GOLEIRO.md) precisava ser construído do zero.
