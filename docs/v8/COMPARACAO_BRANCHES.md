# Football V8: comparação das frentes e decisões de integração

Data: 22/11/2026. Branch de integração: `feature/football-v8-integrated` (worktree `futebol-manager-football-v8`).

## 1. Estado verificado (não presumido)

| | Frente A: Football Engine V7 | Frente B: Football Research Lab |
|---|---|---|
| Branch | `feature/gameplay-v7` | `research/football-gameplay-lab` |
| Commits | `b25f206`, `694eefc` | `28eb216`, `cfd3f56`, `e9d8700` |
| Ancestral comum | `6c0a033` (V6) | `6c0a033` (V6) |
| Worktree | limpa | limpa |
| Natureza | Motor autoritativo no backend (`app/domain/football/`) e renderizadores oficiais | Protótipos **só no frontend** (`frontend/src/lab/football/`, 113 arquivos novos, nenhum arquivo do V7 tocado) |
| Testes verificados | 317 aprovados e 5 falhas preexistentes no backend (as mesmas da V6) | 78 aprovados e 1 ignorado (vitest do lab), confirmado nesta sessão |
| Laboratório | `#lab` (motor real, partidas e cenários) | `/football-lab.html` (abas de personagem, animação, goleiro, sprites, física, IA e performance) |

**Conflitos.** Não existem. As frentes não se sobrepõem em arquivos, exceto `frontend/.gitignore`, que só ganhou uma linha. Os três commits da pesquisa foram aplicados sem conflito sobre o V7 (cherry-pick, histórico preservado). As branches originais ficaram intactas.

## 2. O que veio de cada frente

| Componente | Origem | Destino na V8 | Situação |
|---|---|---|---|
| Física da bola, locomoção, goleiro-agente, IA, resolução da ação | V7 | Motor oficial (`app/domain/football/`, perfil `v8`) | Base mantida |
| Orquestração (relógio, decisões, reconexão, snapshot) | V6/V7 | `highlights.HighlightMatch` | Mantida |
| Atleta humano (21 ossos, corpo em loft, uniforme) | Pesquisa | `frontend/src/football/athlete/` (**promovido à produção**) | Usado pelo 3D oficial (`avatar3d.ts`) e pelo 2D (sprites) |
| Biblioteca de 30 clipes com metadados de contato | Pesquisa | `frontend/src/football/anim/clips.ts` | Clipes de ação alinhados ao instante do contato oficial |
| Locomoção com fase sincronizada e IK de pé | Pesquisa | `frontend/src/football/anim/locomotion.ts` | **Corrigida na V8** (seção 3 e SPRINT.md) |
| Pipeline de sprites (atlas-máscara de 8 direções) | Pesquisa | `frontend/src/football/sprites/bake.ts`, atlas em `frontend/public/sprites/` | O 2D oficial usa os sprites gerados do atleta 3D |
| Animador físico de goleiro (`keeper/animate.ts`) | Pesquisa | Fica no lab | Ver a nota abaixo |
| Simulação física de goleiro em TS (`keeper/sim.ts`) | Pesquisa | Fica no lab como referência | Ver a nota abaixo |
| Física de bola com Magnus (`physics/ball.ts`) | Pesquisa | O efeito foi portado para Python (`world.MAGNUS`, chute colocado com curva) | Modelo de arrasto com crise **não** portado |
| IA tática TS (`tti`, `pitchControl`, `passSafety`, cenários de tabela/ultrapassagem/cruzamento) | Pesquisa | Os conceitos foram portados para `brain.py`/`choice.py` (perfil v8): tempo até a linha de passe, terceiro homem, ultrapassagem por instrução, sombra de cobertura | O código TS continua no lab como prototipagem |

**Goleiro.** O motor oficial já tinha um goleiro físico com estados (V7), e o V8 corrigiu dois pontos físicos dele (mãos baixas e cobertura das pernas). Duplicar a simulação TS da pesquisa criaria um segundo goleiro autoritativo. O renderizador usa os clipes de goleiro da pesquisa (`gk_dive_low/high`, `gk_getup`, `gk_catch`, `gk_jump`, `gk_throw`), dirigidos pelos estados e pelo deslocamento oficiais.

**Um único motor.** Existe uma só física e uma só IA autoritativas: `app/domain/football`. A V6 e a V7 continuam selecionáveis só para comparação: a V7 é o mesmo pacote com o perfil `v7`. O lab de pesquisa não decide nada.

## 3. Defeitos encontrados nas frentes (e corrigidos)

| Defeito | Onde | Causa confirmada | Correção V8 |
|---|---|---|---|
| Sprint desliza 110 cm/s | Pesquisa, `clips.ts` | O pé em balanço do sprint **afundava até 23 cm no gramado** enquanto ainda ia para a frente, porque o apoio "L" era forçado durante o voo. O pé de apoio ainda "pisava" à frente por 0,25 de ciclo, sem recuar | Nenhuma parte do pé abaixo do gramado. Voo real, a partir das janelas de apoio declaradas. Fase casada à distância, com cadência humana (SPRINT.md) |
| Número da camisa espelhado | Pesquisa, `kit.ts` | O UV da camisa corre da direita para a esquerda | O número é desenhado espelhado na textura |
| Gols e passes dos bots baixos | V7 | Funil (`tools/attack_funnel.py`): os lances chegam à zona de finalização como na V6. As perdas estão na **finalização**: bloqueios 20% no 5×5 contra 1,4% na V6, goleiro alcançando bola rasteira com os braços em pé, cruzamentos e conduções sem avaliação de chance | Mira do chute por bloqueadores e alcance do goleiro, física do goleiro corrigida, disputa aérea, corridas à área, condução avaliada por xG × chance de manter a bola (MOTOR_V8.md) |
