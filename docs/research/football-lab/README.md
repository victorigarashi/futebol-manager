# Football Research & Animation Lab

Laboratório de pesquisa e prototipagem do Modo Jogável. Roda **só em desenvolvimento**, em `/football-lab.html`, e não aparece no menu público.

**Os protótipos não decidem resultado de partida.** O motor autoritativo continua sendo `backend/app/domain/highlights.py`.

## Como rodar

```bash
cd frontend && npx vite --port 5190
# abra http://127.0.0.1:5190/football-lab.html
```

## Abas

| Aba | O que tem | Documento |
|---|---|---|
| Characters | Atleta semirrealista em loft, goleiro, 5 padrões de uniforme, variedade cosmética, comparação com o V6 e com o CC0, exportação GLB | RIG_E_ANIMACAO.md |
| Animation | 30 clipes, controles de velocidade, tempo, espelho e contato, bola sincronizada no contato, locomoção dirigida por "motor" com pegadas e medidor de deslize, blend | RIG_E_ANIMACAO.md |
| Goalkeeper | Goleiro físico, chute por arraste com mira mínima, 15 cenários, ajuste de parâmetros, câmera lenta, tabela comparando com a regra V6 | GOLEIRO.md |
| Sprites | Pipeline 3D → atlas-máscara de 8 direções → recoloração por time → prévia 2D | SPRITES.md |
| Physics | 8 gráficos comparando o V6 com o modelo proposto (passe, chute, lançamento, arrancada, corte, condução, quique, curva) | FISICA_E_IA.md |
| Football AI | 10 cenários táticos determinísticos, controle de campo, linhas de passe, decisões e métricas, baseline "todos perseguem" | FISICA_E_IA.md |
| Performance | 1, 5, 10 e 22 atletas animados, qualidades, sombras, LOD e DPR; FPS, p95, draw calls, triângulos, custo de animação e carga | PERFORMANCE.md |

## Entregáveis

1. Pesquisa técnica de repositórios: `PESQUISA_REPOSITORIOS.md`.
2. Licenças: `LICENCAS.md`.
3. Labs executáveis: `frontend/src/lab/football/`.
4. Testes: `frontend/src/lab/football/tests/`, com 24 testes. Os dados são gerados com `REPORT=1 npx vitest run src/lab/football/tests/report.test.ts`.
5. Dados medidos: `data/*.json`.
6. Evidências reais (capturas e webm do Playwright): `evidence/`, gerado por `node scripts/football-lab/evidence.cjs`.
7. Revisão crítica: `REVISAO_CRITICA.md`.
8. Handoff e integração: `HANDOFF_V7.md`.

## Mapa do código

```
athlete/  rig.ts (21 ossos, API de pose anatômica) · body.ts (malha em loft) · kit.ts (uniformes e rosto) · athlete.ts
anim/     clips.ts (30 clipes e metadados, assados para AnimationClip) · fk.ts · ik.ts (dois ossos) · locomotion.ts (fase, IK de pé, medidor)
keeper/   sim.ts (goleiro físico e réplica da regra V6) · animate.ts (animação dirigida pela física)
physics/  ball.ts (bola) · player.ts (cinemática proposta e réplica do V6)
ai/       tactics.ts (TTI, controle de campo, utility AI, bloco defensivo, cenários)
sprites/  bake.ts (atlas-máscara e recoloração)
tabs/     uma aba por arquivo · stage.ts, props.ts, charts.ts
```
