# Evidências da Football Engine V7

Os playtests aqui são **automatizados**: Playwright jogando pela interface real. Não são feedback humano.

| Pasta | Conteúdo |
|---|---|
| `baseline/` | V6 (`6c0a033`): vídeos `baseline-*.webm`, mira `*-mira.jpg`, fim do lance `*-fim.jpg`, rajadas de quadros durante a execução `sheet-burst-*` e `bursts/`, métricas `metricas.json` |
| `depois/` | V7: vídeos `v7*-*.webm` e `final-*.webm`, rajadas `sheet-v7*`, métricas `metricas_v7.json`, bateria do goleiro `goleiro_bateria.json` |
| `multiplayer/` | Dois navegadores (2D contra 3D) na mesma partida: vídeos, `results.json`, capturas antes e depois da recarga e do fim |

**Comparação mais direta:**

- `baseline/sheet-burst-2D-11x11-THROUGH-a0.jpg` (V6): na 2ª imagem o lance já acabou e tudo está congelado;
- `depois/sheet-v7b-2D-11x11-THROUGH-a0.jpg` (V7): cerca de 2 s de jogada contínua, com desmarques, domínio em movimento e o defensor batido.

No 3D, compare `baseline/baseline-3D-11x11-THROUGH-mira.jpg` (arquibancada ocupa cerca de 35% da tela) com `depois/v7b-3D-11x11-THROUGH-mira.jpg`.

**Reproduzir:**

```bash
cd backend && ENGINE=v7 ../.venv/bin/python tools/gameplay_metrics.py 30
cd backend && ../.venv/bin/python tools/keeper_battery.py 40
cd frontend && BURST=1 node scripts/playtest-lab.cjs /tmp/pt v7 both THROUGH,ONE_ON_ONE ELEVEN_A_SIDE
```
