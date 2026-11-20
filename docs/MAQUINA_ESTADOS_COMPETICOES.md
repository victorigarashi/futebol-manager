# Máquina de estados das competições e o travamento dos eliminatórios

Data: 20/11/2026. Branch `fix/resgate-beta`, a partir de `main` `49f3049`, que está em produção.

## 1. Diagnóstico do travamento (reproduzido e corrigido)

**Sintomas relatados:**

- os eliminatórios travam;
- as partidas não aparecem para jogar;
- o sorteio trava;
- não dá para avançar para a próxima partida.

**Reprodução.** Um driver joga a competição exatamente como a interface:

- o técnico só aperta "Pronto" quando a tela de pré-jogo mostra uma partida dele;
- fora isso, só passa o tempo (o timer de preparação do servidor);
- nenhum botão escondido é apertado.

**Matriz testada:**

- Carreira com 8 clubes: playoffs em jogo único e em ida e volta;
- Carreira com 20 clubes e Copa do Brasil;
- Draft Eliminatório com 8 e 16 clubes;
- Pack & Play com 4 clubes;
- Último Sobrevivente com 8 e com 12 clubes (eliminando 4 por rodada);
- em cada configuração: humanos fortes ou fracos, confirmando ou não.

Resultado **antes da correção: 31 de 32 execuções travaram.**

**Causa raiz.** `SeasonService.preparation_deadline` devolvia `None` sempre que `current_round > rodadas da liga`, ou seja:

- em **todos os playoffs**;
- em **todas as rodadas** das competições curtas, cuja liga tem 0 rodadas.

Sem prazo, uma rodada de mata-mata só começava quando todos os humanos que **jogam** nela confirmassem (`required_ready`). Quando nenhum humano jogava aquela rodada (eliminados, ou fora daquela fase), a sequência era:

1. a tela deles mostra "seu clube não disputa esta rodada", sem botão de confirmar;
2. ninguém pode confirmar;
3. o timer está desligado;
4. a competição fica parada para sempre.

O único desbloqueio era o botão do anfitrião na aba Temporada, que só existe na Carreira, e não nas competições curtas.

**Correções:**

| # | Onde | O quê |
|---|---|---|
| 1 | `season_service.preparation_deadline` | O prazo vale para toda rodada: liga, Copa, playoffs, torneio e sobrevivência.<br>• Fase ainda não sorteada: prazo imediato (o servidor sorteia).<br>• Rodada sem humano obrigado a confirmar: pausa de 15 s para espectadores.<br>• Demais casos: o prazo configurado na sala. |
| 2 | `season_service.start_if_preparation_expired` | Quando o servidor só sorteou (sem iniciar rodada), o prazo seguinte conta a partir daquele momento: o sorteio aparece antes dos jogos. |
| 3 | `GET /season` e `/season/preview` | `next_round_starts_at`: quando a próxima rodada começa sozinha. O pré-jogo mostra a contagem até para quem não joga. |
| 4 | `PreMatch.tsx` | Deixou de ficar em "Montando o confronto…" para sempre quando ainda não há confronto: mostra "Próxima fase" com a contagem. |
| 5 | `season_service._publish_round` / `_own_live_match` / `_personal_match` / `live_state` | **Modo espectador.** Se nenhum humano joga a rodada, a primeira partida vira destaque (`featured`), com transmissão 2D. Quem não joga assiste a uma partida com transmissão. Espectador não vê a tática de nenhum dos lados. |
| 6 | `LiveMatchCenter.tsx` | No modo espectador: sem painel de técnico, sem "Você" e sem substituição. Faixa "Você está assistindo". Cabeçalho com o nome real da fase (`live_round.label`). |
| 7 | `season_service` | Logs estruturados (`brasileirao.competition`, JSON) para cada transição: `STAGE_DRAWN`, `ROUND_STARTED`, `ROUND_COMMITTED`, `TIE_DECIDED` e `CHAMPION`. Contêm só ids de sala, fase, rodada e confrontos, sem nomes nem tokens. |

**Depois da correção: 32 de 32 execuções chegam ao campeão.** O teste `test_competition_flow.py` cobre 24 cenários da matriz, mais:

- sorteio idempotente e recuperado de snapshot;
- espectador com transmissão e sem táticas;
- prêmios pagos uma única vez;
- início da temporada seguinte.

### O sorteio

O sorteio é feito pelo servidor, sob o lock da sala, assim que a fase anterior termina:

- no último `finish_due` da liga, ou no `advance` ou no timer.

Propriedades:

- **Determinístico:** semente `room:temporada:playoffs:QF` registrada no próprio sorteio.
- **Idempotente:** cada fase só é criada se ainda não existe confronto dela.
- **Persistido:** fica em `knockout.draws` e vai no snapshot.

Os potes dos playoffs são: pote 1 = 1º ao 4º, pote 2 = 5º ao 8º.

A cerimônia no navegador só revela o resultado já gravado; nada depende da animação terminar.

## 2. Estados reais

### Rodada (liga, Copa, playoffs, torneio, sobrevivência)

```
PREPARING ──(todos os humanos que jogam confirmam | prazo | sem humano: pausa de 15 s)──▶ STARTING ──▶ LIVE ──(fim da transmissão; tarefa da rodada sob lock)──▶ commit ──▶ PREPARING
     ▲                                                                                                                                                           │
     └────────────────────────────── janela de transferências (liga, após a metade): o anfitrião encerra ◀──────────────────────────────────────────────────────┘
```

| Estado | Pré-condição | Quem dispara | Saída | Repetição |
|---|---|---|---|---|
| PREPARING | Nenhuma rodada ao vivo; janela fechada | — | STARTING | Confirmar duas vezes é igual a uma (`ready_clubs` é um conjunto) |
| STARTING / LIVE | `advance` montou os motores (lock da sala) | Último "Pronto", timer (`prepare_rooms_forever`, 1 s) ou anfitrião | commit | `advance` com rodada ao vivo devolve a mesma rodada |
| commit | Relógio passou `ends_at`; todos os motores no apito final | Tarefa `broadcast_round`, sob o lock | PREPARING; liquidação do mata-mata | `finish_due` sem rodada vencida não faz nada; `record_leg` ignora o mesmo jogo registrado de novo |

### Mata-mata (`KnockoutState`)

```
(liga terminada | Copa/torneio/sobrevivência criada) ──▶ STAGE_DRAWN (confrontos + rodadas PENDING)
STAGE_DRAWN ──▶ rodada PENDING é a vez (due_round) ──▶ LIVE ──▶ DONE (placar de cada jogo registrado)
todos os jogos do confronto DONE ──▶ agregado ──(empate)──▶ pênaltis (semente do confronto) ──▶ TIE_DECIDED
todos os confrontos da fase decididos ──▶ próxima fase sorteada (STAGE_DRAWN) | final ──▶ CHAMPION (+ prêmios, 1 vez)
```

Outros pontos:

- **Ida e volta:** a rodada do jogo 2 só fica PENDING depois do jogo 1; o melhor colocado decide em casa; sem gol fora.
- **Prêmios dos playoffs:** `_pay_award` com id de operação, então nunca são pagos duas vezes. Torneio e sobrevivência não pagam prêmios.
- **Sobrevivência:** a rodada é ranqueada; os eliminados saem; a próxima rodada é sorteada com os ativos; com 2 restantes, final com pênaltis.

### Reconexão e reinício

- Cliente que reconecta relê `GET /season` e `/season/live`; nada é recalculado no cliente.
- Servidor que reinicia restaura o snapshot (sorteios, confrontos, rodadas DONE e PENDING) e recompõe a rodada ao vivo em fatias, a partir das entradas e do log de comandos, com resultado idêntico.
- O timer de preparação volta a funcionar sozinho em `prepare_rooms_forever`.

### Locks

- Todas as transições da rodada passam pelo mesmo `round_locks[room]` (asyncio):
  - "Pronto";
  - avanço do anfitrião;
  - timer;
  - commit;
  - leitura ao vivo.
- Não há lock aninhado nem `await` dentro dos métodos síncronos do `SeasonService`, que fazem a mudança de estado inteira sem ceder o loop.
- A transmissão é enviada fora do lock.
