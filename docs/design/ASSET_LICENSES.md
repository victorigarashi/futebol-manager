# Assets e licenças

## Em uso

| Asset | Origem | Licença |
|---|---|---|
| Atleta 3D: malha, esqueleto, pesos e cores | Gerado em código (`render/human.ts`) | Original do projeto |
| Animações dos atletas: corrida, chute, cabeceio, desarme, mergulho, encaixe, comemoração | Procedurais, sobre os ossos (`renderer3d.ts`, `poseRig` e `blendPose`) | Original do projeto |
| Estádio, torcida, placas, gramado, bola, rede | Gerados em código | Original. Os patrocinadores são fictícios |
| Sprites 2D | Desenhados no Canvas (`renderer2d.ts`) | Original do projeto |
| Sons | Sintetizados com WebAudio (`sound.ts`) | Original do projeto |
| Three.js 0.180.0 | npm | MIT |

Nenhum arquivo foi extraído de Dream League Soccer, World Soccer Champs, Mini Soccer Star ou de APKs.

## Avaliados e não adotados nesta etapa

A licença de cada um precisa ser confirmada **asset por asset** antes de qualquer uso.

| Candidato | Por que não agora |
|---|---|
| Mixamo (personagens e animações) | Os termos da Adobe permitem usar em projetos, mas limitam redistribuir os arquivos em si. Num jogo web, o GLB fica baixável pelo cliente. Exige parecer antes de usar |
| Sketchfab | A licença varia por modelo. Não houve tempo de curar um conjunto de futebol com licença verificada |
| Modelos humanos CC0 (Quaternius, Poly Pizza) | São candidatos fortes para a próxima etapa. O download e a verificação das licenças não foram feitos nesta sessão |
| MakeHuman / MPFB + Blender | Exige produção no Blender, indisponível neste ambiente |

## Próximo passo recomendado para chegar perto do DLS clássico

1. Produzir no Blender um atleta base com malha de 3 a 6 mil triângulos, com o mesmo esqueleto de 13 ossos e os mesmos nomes, ou com o rig de uma fonte CC0 verificada.
2. Fazer as texturas: uniforme com máscaras de cor, para manter a escolha de uniformes do servidor; pele; rosto.
3. Exportar em GLB e otimizar com glTF-Transform e meshopt.
4. O `buildHumanRig` troca a malha procedural pela GLB clonada com `SkeletonUtils.clone`. O sistema de poses, a mistura de poses (blending) e o resto da pipeline continuam iguais.

## Football Lab (branch research/football-gameplay-lab, só em desenvolvimento)

Os assets do laboratório também são originais: o atleta em loft, o rig de 21 ossos, os 30 clipes, os sprites gerados e as capturas. O único asset de terceiros é o GLB CC0 da Quaternius, usado como comparação. Ele **não é commitado**: fica em `public/lab-assets/third-party/`, que está no `.gitignore`. O detalhamento está em `docs/research/football-lab/LICENCAS.md`.

## V8 Broadcast Visuals (branch feature/v8-broadcast-visuals)

Tudo é gerado em código, em `render/stadium3d.ts`: gramado com faixas de corte, desgaste e marcações; torcida pintada em canvas como impostor por arquibancada; escadas, corrimões, muro azul-marinho com placas; céu em gradiente. As placas usam apenas marcas fictícias ("BRASILEIRÃO MANAGER", "RESENHA"). Não há fotos, logos reais, texturas de terceiros nem arquivos extraídos de jogos. As imagens de `references/` do pacote V8 serviram só de comparação visual e **não** foram copiadas para o repositório.
