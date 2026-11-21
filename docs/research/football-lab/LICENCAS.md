# Relatório de licenças — Football Lab

## O que o lab contém (commitado nesta branch)

| Item | Origem | Licença |
|---|---|---|
| Atleta (malha em loft, rig de 21 ossos, pesos, rosto pintado, uniformes) | Gerado em código: `src/lab/football/athlete/*` | Original do projeto |
| 30 clipes de animação e os metadados | Keyframes anatômicos escritos em código: `anim/clips.ts` | Original do projeto |
| Física da bola, do jogador e do goleiro | `physics/*` e `keeper/*` | Original do projeto. Os modelos físicos são de domínio público (Coulomb, arrasto, Magnus) |
| IA tática | `ai/tactics.ts`, inspirado em Reynolds (steering) e em modelos de controle de campo da literatura | Original do projeto. Nenhum código copiado |
| Sprites e atlas | Gerados a partir do atleta do lab (`sprites/bake.ts`) | Original do projeto |
| Capturas e vídeos (`evidence/`) | Gravados com Playwright a partir dos protótipos | Original do projeto |
| Three.js 0.180 (`OrbitControls`, `GLTFLoader`, `GLTFExporter`, `BufferGeometryUtils`) | npm, já era dependência | MIT |

Nenhum arquivo de Dream League Soccer, World Soccer Champs, Mini Soccer Star, Score! Hero, EA FC ou Football Manager foi usado. Nenhum APK foi aberto. Os patrocinadores e o escudo são fictícios.

## Opcional, NÃO commitado

| Item | Origem | Licença | Situação |
|---|---|---|---|
| `quaternius-animated-man.glb` (Quaternius, "Animated Men") | Copiado do repositório kendrekaran/striker-3d, que traz `LICENSE-quaternius.txt` (CC0 1.0) | CC0 1.0 | Usado só como base de comparação na aba Characters, a partir de `public/lab-assets/third-party/`, que fica no `.gitignore`. Ele é baixado por `scripts/football-lab/fetch-cc0.cjs`. Antes de qualquer uso em produção, baixe de novo da fonte original (quaternius.com), porque o striker-3d não tem licença própria e fez a conversão FBX→GLB |

## Avaliados e não usados

Mixamo (termos de redistribuição), Sketchfab (licença por modelo, sem curadoria), Kenney (estilo fora da direção artística), código sem licença (striker-3d e GoalDao: só leitura), código GPL/LGPL/AGPL (rcssserver, MakeHuman, LibreSprite: só como referência conceitual ou ferramenta).

## Dependências novas

Nenhuma. O `package.json` não foi alterado.
