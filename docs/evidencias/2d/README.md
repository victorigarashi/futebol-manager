# Evidências visuais do 2D: antes e depois

As imagens são **quadros reais do motor**: posições autoritativas a 1 tick por segundo de jogo, desenhadas como o cliente desenha. Isso inclui a interpolação entre segundos, a antiga regra de "sumir" a bola parada (no antes) e o voo do chute (no depois).

- **Antes:** motor de `0216532` (anterior às correções do 2D).
- **Depois:** branch `fix/resgate-beta`.
- **Mesmas sementes e mesmos elencos reais** (6 primeiros jogos do calendário, 11×11, bots dos dois lados).

## Cenas

| Cena | Arquivos | O que observar |
|---|---|---|
| Gol | `antes/gol.gif`, `depois/gol.gif`, `*_quadros.png` | **Antes:** a bola fica parada fora do campo, na bandeira de escanteio, durante quase toda a sequência; o gol "aparece". **Depois:** o ataque azul leva a bola pela direita até a área (anel verde = quem tem a bola); a defesa vermelha fecha a área; a bola cruza a linha e vem a saída de bola. |
| Defesa do goleiro | `defesa.*` | **Depois:** o chute voa até o goleiro, que mergulha na direção da bola. |
| Chute para fora | `chute_fora.*` | **Antes:** a bola some (regra de bola parada do cliente). **Depois:** a bola voa até a linha de fundo. |
| Escanteio | `escanteio.*` | **Depois:** construção pela ponta e saída pela linha de fundo; atacantes na área, defesa protegendo do pequeno à marca do pênalti. |

## Defeito encontrado na validação visual (e corrigido)

**Problema.** Nas primeiras capturas do "depois", a defesa ficava **em linha sobre a própria linha do gol** sempre que a bola estava na linha de fundo (escanteio, cruzamento de fundo).

**Causa.** O bloco baixo posicionava cada defensor a "profundidade da bola − 2 m".

**Correção.** No 11×11, profundidade mínima de 5,8 m (`match_engine._move_agents`). O 5×5 foi mantido como estava: no campo de 40 m o piso eliminava o efeito do entrosamento (medido +0,29 → 0).

Depois da correção:

- 11×11 em produção: 2,42 gols por partida, 25% de empates, 10% de 0–0 (80 partidas);
- 5×5: 6,0 gols por partida.

## Como reproduzir

```bash
cd backend
../.venv/bin/python tools/visual_scenarios.py /tmp/quadros     # quadros do motor (JSON)
python3 ../docs/evidencias/2d/render.py /tmp/quadros /tmp/viz DEPOIS   # precisa de Pillow
```

Câmera da partida ao vivo:

- campo inteiro por padrão;
- a câmera dinâmica continua disponível como opção manual;
- jogadores e bola maiores, e a bola com halo para ser seguida mais facilmente.
