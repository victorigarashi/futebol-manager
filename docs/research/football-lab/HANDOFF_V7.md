# Handoff para o Football Engine Rebuild V7

**Branch:** `research/football-gameplay-lab`, partindo de `6c0a033`. A worktree é `futebol-manager-football-lab`. Nenhum arquivo em edição pela frente V7 foi tocado: `InteractiveMatch.tsx`, `renderer3d.ts`, `gameplay_metrics.py` e `playtest-lab.cjs` estão intactos. **Não há merge nem deploy.**

Tudo o que é novo fica em `frontend/football-lab.html`, `frontend/src/lab/football/`, `frontend/scripts/football-lab/` e `docs/research/football-lab/`. O único arquivo compartilhado que mudou é `frontend/.gitignore`, com uma linha a mais.

## Integração por prioridade

### 1. Corrigir `_steer` em `highlights.py` (pequeno e de alto impacto)

Trocar o limite por eixo por um limite **vetorial**, com o componente tangencial (propulsão menor com a velocidade, frenagem) e o lateral (aderência de cerca de 7,5 m/s²) separados.

- Referência: `steer()` em `frontend/src/lab/football/physics/player.ts`.
- Efeito: elimina a aceleração √2 nas diagonais e as curvas em "L".
- Parâmetros sugeridos: `vMax = 7,4 + 2,0·pace`, `aMax = 7,8 + 2,2·pace`, `brake = 8,5 + 1,0·pace` e `grip = 7,5` (pace de 0 a 1).

### 2. Física da bola com subpassos (médio)

Portar `stepBall` (cerca de 150 linhas) para Python: arrasto com crise, Magnus, deslize e rolamento de esfera oca, quique com rotação e traves contínuas.

- Manter os quadros de 10 Hz para o cliente, com subpassos internos de 1/240 s.
- O lançamento deixa de usar `air_left` com parábola fixa e passa a ser balístico. O renderizador já desenha `z`.
- **Verificar com o proprietário** o alcance do passe, que vai de 22,5 m para cerca de 35 m a 15 m/s, e rebalancear `PASS_SPEED` se for preciso.

### 3. Goleiro físico (grande, prioridade crítica)

Portar `simulateShot` (keeper/sim.ts) para o lugar de `_keeper_vs_shot`.

- **Remover os sorteios de defesa.** Defesa, encaixe ou espalmada passam a sair do contato físico.
- Mapear `keeping` para `keeperFromRating`: reação, impulsão, alcance e limite de encaixe.
- Emitir cues para o renderizador: `GK_SET` (no chute), `GK_LOAD`, `GK_TAKEOFF {vLat, vUp}`, `GK_CONTACT {hands: [L, R], part, hold}` e `GK_LAND`. Também podem ir por quadro `com`, `tilt`, `diveU`, `handL` e `handR` (12 floats).
- O `KeeperAnimator` (keeper/animate.ts) é o renderizador pronto desses dados: quadril no CG e braços por IK nas mãos.
- Os testes em `tests/keeper.test.ts` viram a especificação dos testes em Pytest. Para paridade, gere fixtures dos 15 cenários com `REPORT=1 npx vitest run src/lab/football/tests/report.test.ts`, que grava `data/keeper-scenarios.json`.

### 4. Locomoção sem escorregar (renderizadores)

- Fase do ciclo = ∫ velocidade ÷ passada (`gaitTable()` mede a passada por FK).
- IK de pé no ponto da sola: `Locomotion.footLock`, `anim/ik.ts`.
- No 2D: avançar o quadro do sprite pela distância percorrida.

### 5. Atleta e animação no renderer3d (grande)

- **Contrato do rig:** 21 ossos com os nomes de `athlete/rig.ts`, +Z para a frente, Y para cima, metros, L = +X, pose de bind com identidade.
- **Clipes e metadados:** `clipMetadata()` em `data/clip-metadata.json`. O contato é sincronizado com o evento do servidor (RIG_E_ANIMACAO.md).
- **Caminho para o visual do DLS:**
  1. corpo base no Blender (MPFB2/MakeHuman, CC0), com 4–6 mil triângulos, **com este esqueleto**;
  2. texturas pintadas com máscaras de região no canal de vértice, mantendo `KitSpec` e a recoloração;
  3. GLB otimizado com `gltf-transform optimize --compress meshopt`;
  4. se houver parecer jurídico, retargeting de captura de movimento para o sprint, a corrida e os mergulhos.

### 6. Sprites 2D

Atlas-máscara mais recoloração (SPRITES.md). Gerar offline (o botão da aba Sprites baixa o PNG e o JSON) e servir como asset estático.

### 7. IA

Usar `tti`, `pitchControl` e `passSafety` (ai/tactics.ts) no lugar das heurísticas `_openness` e `_intercept` para escolher receptores e interceptadores. A escolha do pressionador pelo tempo até a bola (não pela distância) e a sombra de cobertura são as mudanças de maior retorno.

## Dependências

Nenhuma nova. Three.js 0.180, que já está no projeto. glTF-Transform e meshopt só entram quando houver GLB de artista.

## Como rodar

```bash
cd frontend
npx vite --port 5190                    # http://127.0.0.1:5190/football-lab.html  (só em desenvolvimento)
npx vitest run src/lab/football          # testes do lab
npm run typecheck                        # tsc -b
node scripts/football-lab/evidence.cjs   # regera capturas, vídeos e benchmarks (com o lab servido)
```

## Riscos e limitações

- O atleta gerado em código tem um teto visual. Ver REVISAO_CRITICA.md.
- O sprint desliza: 205 cm/s.
- A tabela e a ultrapassagem não são confiáveis na IA.
- O termo de resistência da grama não foi calibrado com dados reais.
- Performance medida só no iGPU Intel da máquina de desenvolvimento. **Falta celular real.**
- O multiplayer não foi testado com nada do lab.
