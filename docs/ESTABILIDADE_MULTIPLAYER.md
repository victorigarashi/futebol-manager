# Estabilidade multiplayer no Render: diagnóstico, correções e medições

Data: 15/11/2026. Branch `fix/multiplayer-estabilidade`.

## 1. Diagnóstico (com evidências)

### 1.1 O que o Render registrou

| Evidência | Fonte | O que mostra |
|---|---|---|
| `server_failed`: *"HTTP health check failed (timed out after 5 seconds)"*, `evicted: false`, às 21:37, 21:42 e 21:47 UTC | API de eventos do Render (`/v1/services/{id}/events`) | O Render **reiniciou a API três vezes durante a partida** porque `/api/v1/health` não respondeu em 5 s. Não foi falta de memória (`evicted: false`). |
| CPU entre 0,10 e 0,15 durante toda a sessão; memória entre 130 e 180 MB de 512 MB | API de métricas do Render | O serviço estava **no teto de CPU do plano Free (0,1 CPU)**. Memória sobrando. |
| Último pedido às 21:45:31, silêncio de 13 s e depois `Running 'uvicorn …'` sem `Shutting down` | `render logs` | O processo ficou travado e foi morto, sem encerramento limpo. |
| Os pedidos que antecedem cada travamento são `POST /season/ready` (início da rodada) e `GET /season/live/frames?since=-1` | `render logs` | Os travamentos começam quando a rodada começa a ser simulada. |
| Cerca de 4 pedidos/s de 3 navegadores (`/state`, `/season`, `/season/live`, `/squad`, `/season/preview`) | `render logs` | Cada evento do WebSocket fazia todos os navegadores recarregarem tudo. |

### 1.2 Causas no código

1. **Simulação dentro do event loop (causa principal).**
   - `sync_live()` simulava as 10 partidas da rodada sincronamente, dentro de pedidos HTTP (`/season/live`, `/season/live/frames`, comandos) e da tarefa da rodada.
   - Medido localmente com o perfilador: uma chamada chegava a **583 ms** num núcleo de desktop. Com 0,1 CPU isso vira vários segundos com o loop parado, e nem o health check é atendido.
2. **Ciclo de reinicializações.**
   - Ao reiniciar, `restore_snapshots()` refazia as 10 partidas ao vivo antes de abrir a porta, e duas vezes (validação e restauração).
   - O servidor voltava já travado e o Render o derrubava de novo, cerca de 5 min depois (21:37, 21:42, 21:47).
3. **Rajadas de pedidos.**
   - Qualquer evento do WebSocket invalidava **todas** as consultas da sala em todos os navegadores.
   - `season.tick` forçava um `/season/live` por segundo por técnico, e cada um desses pedidos simulava de novo.
4. **Snapshot a cada ação.**
   - Cada clique relia e reprocessava o arquivo inteiro e regravava todas as salas, formatado.
   - Uma partida terminada ocupa cerca de 67 KB, então uma temporada chega a **cerca de 25 MB por sala**, cerca de 113 ms de CPU por clique num desktop e segundos no Free.
5. **Replay 2D pós-jogo** (`/matches/{id}/frames`) re-simulava até 5400 ticks dentro do pedido.
6. **"CORS" e 502 são o mesmo sintoma.**
   - Enquanto a instância reinicia, o proxy do Render responde 502 sem cabeçalhos CORS, e o navegador registra isso como erro de CORS.
   - Não há configuração de CORS errada (`CORS_ORIGINS` está correto e responde nos pedidos normais).
7. **PRONTO preso em "PREPARANDO".**
   - Com a API reiniciando, o `POST /season/ready` falhava (502) ou a confirmação ficava no estado em memória perdido.
   - Além disso, o botão dependia de recarregar `/season` depois do clique: se esse recarregamento falhasse, o botão voltava para "Confirmar equipe" mesmo com a confirmação registrada.
   - O erro de um 502 ainda aparecia como *"Confira os campos e tente novamente."*.
8. **Prazo de preparação** só era aplicado quando alguém consultava `GET /season`.
9. **"Conexão lenta" falso.**
   - O aviso disparava após 4 s sem receber dados.
   - No intervalo e nos cortes da transmissão o servidor legitimamente não manda frames novos, então o aviso aparecia com a conexão perfeita.

### 1.3 Reprodução local (antes da correção)

O plano Free foi reproduzido com uma cota de CPU no cgroup (`systemd-run --user --scope -p CPUQuota=10%`). O teste de carga leve (`backend/tools/load_test.py`) usa 1 sala, 2 técnicos e uma partida de 1:30:

| Métrica | Antes |
|---|---|
| Health checks acima de 5 s ou falhos | **16 de 35** (o Render reiniciaria a instância) |
| Latência p95 / máxima | **17,3 s / 27,7 s** |
| Erros de rede / quedas do WebSocket | 3 / 2 |
| Pushes de frames por segundo | 0,11 (lacunas de 44 s: campo congelado) |
| Duração da rodada de 1:30 | 124 s |

## 2. Correções

### 2.1 Simulação cooperativa (backend)

- **`SeasonService.simulate_slice`.**
  - Cada unidade de trabalho simula no máximo 40 ticks de uma partida, cerca de 5 a 8 ms num desktop.
  - A tarefa da rodada devolve o controle ao event loop após cada fatia (`await asyncio.sleep(0)`).
  - Enquanto a transmissão precisa de trabalho, a tarefa continua sem pausas ociosas. Sem isso, a rodada usaria menos CPU do que o plano permite. Ela só descansa quando está em dia.
  - Os frames são enviados no máximo a cada 0,25 s.
- **Os pedidos nunca simulam.** `live_view`, `live_frames` e comandos só leem o que a tarefa já calculou.
- **Partidas sem técnico humano (bot contra bot).**
  - Usam um `LinearClock` (o placar avança linearmente no tempo da rodada, com o mesmo intervalo da transmissão).
  - Não guardam frames 2D nem snapshots de estatística. Ninguém as assiste, e os pedidos de partidas alheias já eram proibidos (403).
- **Pré-simulação durante a preparação.**
  - As partidas bot contra bot da próxima rodada não dependem de nada que um técnico ainda possa mudar. Por isso são simuladas no tempo ocioso da preparação (`prepare_slice`).
  - As entradas são guardadas com uma impressão digital. Se algo mudar (um técnico assume o clube, uma transferência), o trabalho é descartado e a partida é simulada do zero. **O resultado é idêntico** (há testes para isso).
  - A pré-simulação cede a vez sempre que uma transmissão ao vivo estiver atrasada.
- **Recuperação após reinicialização.**
  - O restore não refaz mais as partidas antes de abrir a porta. Os motores são reconstruídos em fatias (`ReplayJob`) pela tarefa da rodada.
  - Enquanto isso, a API responde `round_state = "RECOVERING"` e a tela mostra "Recuperando a partida…".
  - Um snapshot feito no meio da reconstrução guarda o log de comandos completo.
- **Tarefa da rodada resiliente.** Se uma iteração falhar, o erro é registrado e a tarefa é reagendada. A sala nunca fica "ao vivo" sem tarefa.
- **Preparação.** Uma única tarefa de manutenção aplica o prazo de preparação a cada segundo, mesmo sem ninguém consultando, e roda a pré-simulação.
- **Snapshots incrementais** (`app/services/snapshot_store.py`).
  - Cada sala fica serializada em memória no formato canônico do checksum.
  - Partidas terminadas, que são imutáveis, são serializadas uma única vez.
  - O arquivo é gravado fora do event loop (`asyncio.to_thread`), agrupando gravações próximas (1 s), e no encerramento.
  - O formato continua o que `load_snapshot` lê.
- **Replay 2D pós-jogo** roda em `asyncio.to_thread`, num motor próprio, sem estado compartilhado.
- **Push de frames mais barato.**
  - O histórico é percorrido do fim (O(frames novos)).
  - As linhas normalizadas ficam em cache e são compartilhadas entre os dois técnicos do mesmo jogo.
  - O segmento de cada tick é achado por busca binária.
  - A janela da transmissão só é refeita quando muda.
  - Um heartbeat por segundo mantém o relógio do cliente sincronizado nos intervalos.
- **`/health` é `async`**: não depende do thread pool.

### 2.2 Máquina de estados da rodada

`PREPARING → READY → STARTING → LIVE → FINISHED → (PREPARING da próxima)`, mais `RECOVERING` depois de uma reinicialização.

- O estado aparece em `round_state` em `GET /season` e `GET /season/live`.
- Os estados existentes foram preservados: `live_round`, `ready_clubs` e `preparation_opened_at` continuam iguais, e `human_clubs` foi acrescentado.
- **READY é idempotente**: confirmar duas vezes equivale a confirmar uma.
- **Início atômico**: o lock da sala torna "todos prontos → começar" uma única transição, e a rodada começa **exatamente uma vez**, mesmo com cliques simultâneos (há teste com 8 pedidos concorrentes).
- **Bots** nunca bloqueiam o início.
- **Prazo**: quem não confirmou joga com a escalação e a tática salvas, como já era a regra.

### 2.3 Tempo real (frontend)

- **Invalidação por tipo de evento** (`lib/roomEvents.ts`).
  - Cada evento atualiza só o que ele altera. Por exemplo, `season.ready_changed` atualiza apenas a temporada e o pré-jogo.
  - Rajadas viram uma única atualização a cada 250 ms.
  - O `season.tick` agora sai a cada 2 s.
- **Uma só conexão WebSocket por aba e sala**, com reconexão em backoff exponencial com jitter e ressincronização completa ao reconectar.
- **Retentativas.**
  - Só falhas transitórias são repetidas (sem resposta, 502, 503, 504, 408, 429), com backoff e jitter.
  - Regras do jogo (4xx) nunca são repetidas, e mutações nunca são repetidas automaticamente.
- **Erros classificados.** O front distingue "sem conexão", "servidor reiniciando" e "o jogo recusou", e mostra uma **faixa global** clara enquanto o servidor está fora (`ServerStatusBanner`).
- **Botão PRONTO.**
  - Usa a resposta do próprio `POST /season/ready`.
  - Mostra os estados "Confirmando…", "✓ Pronto" e "Iniciando partida…".
  - Em caso de falha, explica que **a equipe não foi marcada** e oferece "Tentar de novo".
- **Aviso de atraso honesto.** Só aparece quando a tela realmente passou do fim da transmissão que tem. Ele diferencia "Conexão perdida — reconectando…" de "Aguardando o servidor…".
- O polling de reserva dos frames também usa backoff.
- Durante a partida, `/season` passa a ser consultado a cada 15 s em vez de 5 s.

### 2.4 Motor e resultados

- **Nenhuma regra do motor mudou.** As otimizações preservam a ordem dos sorteios aleatórios.
- Uma referência de 9 partidas completas (eventos, frames e estatísticas, 11×11 e 5×5) tem impressão digital **idêntica** antes e depois.
- Nenhum resultado oficial é alterado para suavizar animação.

## 3. Medições depois das correções

Mesmo teste, cota de 10% de CPU, 1 sala, 2 técnicos, 1:30:

| Métrica | Antes | Depois (prontos após 3 s) | Depois (preparação de 60 s) |
|---|---|---|---|
| Health checks acima de 5 s ou falhos | 16 de 35 | **0 de 97** | **0 de 148** |
| Health check p95 / máximo | 4,7 s / falhas | 0,30 s / 0,70 s | 0,39 s / 0,70 s |
| Lag máximo do event loop | — | 0,90 s | 0,80 s |
| Latência p95 / máxima | 17,3 s / 27,7 s | 0,78 s / 1,09 s | 0,52 s / 1,89 s |
| Erros HTTP / quedas do WebSocket | 3 / 2 | **0 / 0** | **0 / 0** |
| Duração da rodada de 1:30 (90 s + 5 s de apresentação) | 124 s | 98,9 s | **94,3 s** |

Sem limite de CPU, a rodada dura 94,9 a 95,0 s, e o pré-jogo e o mercado respondem em 5 a 14 ms.

**Capacidade no plano Free (0,1 CPU).** Medido com 3 salas jogando ao mesmo tempo (6 técnicos, 60 s de preparação), sob a cota de 10%:

| Métrica | Primeira versão da correção | Versão final (push otimizado) |
|---|---|---|
| Duração das três rodadas de 1:30 | 212 a 264 s | **92,9 a 93,2 s** |
| CPU do push de frames | 14 a 19,8 s | **2,9 s** |
| Latência p95 / máxima | 1,05 s / 2,1 s | 0,45 s / 1,4 s |
| Health check máximo / erros / quedas do WebSocket | 0,9 s / 0 / 0 | 1,2 s / 0 / 0 |
| CPU média do processo | 0,095 | 0,083 |

Com mais salas simultâneas, a CPU de 0,1 se esgota e as transmissões passam a atrasar aos poucos (sem travar o servidor). A rodada custa cerca de 3,6 s de CPU de desktop por sala, e boa parte disso é antecipada na preparação.

Comandos para reproduzir: veja `backend/tools/load_test.py` e `backend/tools/load_server.py`.

## 4. Limitações que só se resolvem com infraestrutura

- **CPU.** O Free tem 0,1 CPU. O código agora usa esse orçamento sem travar, mas várias salas jogando ao mesmo tempo dividem a CPU.
  - O plano Starter (0,5 CPU) comporta cerca de 5 vezes mais.
  - Comprar CPU só serve com **1 instância**; ver o ponto seguinte.
- **Estado em memória com 1 processo.**
  - O jogo exige `--workers 1` e `numInstances: 1`, porque o estado da sala é a memória do processo.
  - Mais workers ou instâncias quebrariam o multiplayer.
  - Escalar horizontalmente exigiria mover o estado para um banco ou Redis, o que é uma reescrita fora deste escopo.
- **Disco efêmero.**
  - No Free, `/tmp` sobrevive a um reinício do processo na mesma instância, que foi o caso do incidente. Não sobrevive a um deploy nem à hibernação após 15 min sem tráfego.
  - Para salas que durem dias, é preciso um disco persistente (planos pagos, montado em `SNAPSHOT_PATH`) ou um banco externo.
- **Hibernação do Free.** O primeiro acesso depois de 15 min ocioso leva cerca de 1 min. A faixa "servidor reiniciando" aparece e o cliente reconecta sozinho.

## 5. Deploy no Render

Não há mudança obrigatória no `render.yaml`. O comando continua com `--workers 1`, e o health check continua em `/api/v1/health`.

1. Fazer o merge da branch em `main`. O auto-deploy publica a API e o site.
2. Conferir:
   - `GET https://brasileirao-manager-api.onrender.com/api/v1/health` deve responder `{"status":"ok"}`;
   - `GET …/api/v1/metrics` mostra a CPU por subsistema e o lag do loop. Durante uma partida, `event_loop_lag.max` deve ficar bem abaixo de 5 s.
3. Recomendado, se o jogo for usado com várias salas ao mesmo tempo: o plano Starter para a API (mantendo 1 instância) e um disco persistente montado no diretório de `SNAPSHOT_PATH`.
