# Desempenho do tempo real no Render Free

Data: 15/11/2026. Branch `perf/tempo-real-render-free`. Continua `docs/ESTABILIDADE_MULTIPLAYER.md`, que trata da simulação cooperativa, dos reinícios e do fluxo de PRONTO.

**Regra mantida.** Nenhuma otimização altera placar, resultado, dinheiro, jogadores ou regras. A simulação, o calendário e o mercado são os mesmos, e os testes de resultado idêntico continuam passando.

A duração mínima da partida continua **1:30**, porque o jogo não tem uma opção de 60 s e criá-la mudaria uma regra. As medições usam 1:30, o caso mais apertado.

## 1. Gargalos encontrados e corrigidos

| Gargalo | Evidência | Correção |
|---|---|---|
| Cada `season.tick` (a cada 2 s) invalidava a consulta `live` inteira em todos os navegadores, além do polling HTTP de 4 s. | Baseline com 5 salas: 181 KB/s de HTTP, sobretudo o `/season/live` completo (cerca de 43 KB por resposta). | **Estado leve pelo WebSocket.** `live.state` (confiável e sequenciado) e `live.stats` (compacto, a cada 8 s). O HTTP do ao vivo só roda na entrada, na reconexão, numa lacuna de sequência, no fim da rodada e a cada 30 s como reconciliação. O `season.tick` deixou de existir. |
| O push de frames recalculava a mesma janela para cada técnico e aba do mesmo jogo, e enviava JSON a cada socket em sequência. | Baseline: **37,7 s de CPU** em push de frames, mais do que a simulação (25 s). | **Memo de janelas** por (sala, partida, intervalo), já que os frames não são privados entre os dois técnicos do mesmo jogo. Mais um **writer por socket**. |
| Os envios não tinham controle por cliente: um socket lento segurava o laço da rodada (`await send` com timeout em cada push). | Lag máximo do event loop de 12,7 s no baseline com 20 conexões. | **Backpressure** (ver §2). |
| O texto da partida re-renderizava 5 vezes por segundo, filtrando todos os eventos a cada vez. | Leitura do código (`filter` por atualização, `setShown` a cada 200 ms mesmo sem mudança). | Texto 4 vezes por segundo e **só quando o que mostra muda**; eventos visíveis por busca binária; painéis (lances, rodada, estatísticas) memoizados. |
| O canvas pintava em toda chamada de `requestAnimationFrame` (60 Hz ou mais) e montava um gradiente radial por jogador por frame. | Leitura do código. | **30 fps** por padrão, 20 em aparelhos limitados e até 60 opcional quando sustentado. Sprites dos marcadores em cache. Pausa com a aba oculta. Modo econômico. |

## 2. Mensagens e confiabilidade

**Estado confiável (`live.state`).**
- Traz gols, cartões, substituições, mudanças de placar, os placares da rodada, a classificação (só quando algum placar muda) e o fim da rodada.
- `seq` é o número de eventos da partida **já na tela**. Cada mensagem traz os eventos em (`seq_from`, `seq`].
- O cliente só aceita a mensagem se `seq_from` for igual ao que já tem. Se houver lacuna, ele **reconcilia pelo HTTP**, que é a fonte autoritativa, em vez de adivinhar.
- Uma mensagem mais velha que o estado do cache é ignorada, para nunca voltar o placar.
- Eventos acima do tick em exibição nunca são enviados. A tática do rival continua mascarada como no HTTP (há teste para isso).

**Estado visual descartável (`live.frames`).**
- Traz posições, bola e frames intermediários.
- Enquanto um envio está pendente, frames novos são **mesclados** a ele (sem duplicar ticks, com no máximo 240 linhas; o excedente mais antigo é descartado e contado).
- Os segmentos da linha do tempo, que marcam o ritmo da transmissão, nunca se perdem na mescla.

**Backpressure** (`backend/app/services/realtime.py`).
- **Um writer por WebSocket.** Todo envio passa por ele (inclusive `season.sync` e `pong`), então nunca há dois envios simultâneos no mesmo socket (há teste para isso).
- **Fila confiável limitada (128).** Se estourar, ela é trocada por um único `live.resync`, e o cliente se reconcilia pelo HTTP. Mensagem confiável nunca some em silêncio.
- **Cliente permanentemente lento**, que não aceita uma escrita em 2 s: o socket é fechado com o código `1013` e removido. O cliente reconecta com backoff e se ressincroniza.
- Uma fila em memória **não é entrega garantida após desconexão**. Na reconexão, o cliente sempre relê o estado (`season.sync` e HTTP).

## 3. Simulação

O avanço da rodada já era de um único mecanismo por sala: a tarefa da rodada, em fatias, com locks por sala. Os pedidos nunca simulam. Essa parte foi feita na etapa anterior.

- Nesta etapa a simulação ganhou o contador `ticks_simulated`.
- O lock é mantido só durante cada fatia, e nunca durante envio ou disco.
- O prazo absoluto e a oficialização única continuam garantidos pelos testes de `test_multiplayer_flow.py`.

## 4. Observabilidade

Em `GET /api/v1/metrics` (público e sem identificadores; as salas aparecem só como contagens):

- CPU por subsistema: simulação, pré-simulação, push de frames, push de estado e snapshot;
- `ticks_simulated` e `frame_memo_hits`;
- lag do event loop (último valor, máximo e quantas vezes passou de 1 s);
- memória (RSS máximo) e CPU média;
- `realtime`: bytes e mensagens enviados por tipo, maior payload por tipo, frames mesclados, linhas descartadas, resyncs, clientes lentos fechados e conexões por sala;
- `client_rendering`: FPS efetivo, tempo de desenho do canvas e atraso servidor→cliente, enviados pelos navegadores a cada 10 s (anônimos e agregados).

Não há log por frame.

## 5. Medições

As medições usam a ferramenta `backend/tools/load_test.py` com `tools/load_server.py`, sob `systemd-run --user --scope -p CPUQuota=10%`, que reproduz o 0,1 CPU do Render Free.
- **Cenário:** 1:30, 60 s de preparação e 2 abas por técnico.
- **`--client v1`** imita o frontend anterior (live por HTTP a cada ~2 s).
- **`--client v2`** imita o atual.

### 5 salas, 10 técnicos, 20 WebSockets

| | Antes | Depois |
|---|---|---|
| CPU do push de frames | 37,7 s | **0,48 s** |
| CPU do push de estado (`live.state` e `live.stats`) | — | 0,89 s |
| Lag máximo do event loop | 12,7 s | **1,2 s** |
| Health check acima de 5 s ou falho | 2 | **0** |
| Health check p95 / máximo | 1,5 s / 4,3 s | **0,69 s / 1,46 s** |
| Latência HTTP p95 / máxima | 3,5 s / 13,4 s | **2,0 s / 3,0 s** |
| Pedidos HTTP | 2185 | 1289 |
| Tráfego HTTP | 181 KB/s | 64 KB/s |
| Tráfego WebSocket | 4,4 KB/s | 37 KB/s (o ao vivo agora chega por aqui) |
| **Tráfego total** | **185 KB/s** | **101 KB/s** |
| Rodadas encerradas | 2 de 5 (cerca de 288 s) | **5 de 5** (cerca de 270 s) |
| Quedas do WebSocket / erros HTTP | 0 / 0 | 0 / 0 |
| Maior mensagem | `season.sync` 6,4 KB | `live.stats` 10 KB; `live.state` 7,5 KB (com a tabela) |

**Comparação A/B** com 3 salas e 12 WebSockets, rodada em seguida, nas mesmas condições: ver §5.1.

**5 salas não cabem em 0,1 CPU.** As 5 rodadas precisam de cerca de 18 a 21 s de CPU de simulação, mais do que os 9 s que o plano oferece em 90 s. O servidor continua responsivo e entrega tudo, mas as rodadas duram cerca de 4,5 min em vez de 1:35.

### 5.1 A/B com 3 salas

Executados um logo após o outro, nas mesmas condições: A é a `main` atual (`085e1e9`) com o cliente v1; B é esta branch com o cliente v2. Cenário com 3 salas, 6 técnicos e 12 WebSockets, sob cota de 10% de CPU:

| | A (antes) | B (depois) |
|---|---|---|
| Rodadas encerradas na janela de 6 min | **0 de 3** | **3 de 3** (cerca de 271 s) |
| CPU do push de frames | 23,8 s | **0,41 s** |
| CPU da simulação | 24,9 s | 22,6 s |
| Lag máximo do event loop / vezes acima de 1 s | 2,6 s / 11 | 2,0 s / 5 |
| Latência HTTP p95 / máxima | 1,59 s / 3,39 s | 1,53 s / 3,05 s |
| Pedidos HTTP | 1560 | **719** |
| Tráfego total (HTTP e WebSocket) | 136 KB/s | **54 KB/s** |
| Erros HTTP / quedas do WebSocket / health acima de 5 s | 0 / 0 / 0 | 0 / 0 / 0 |
| Memória máxima | 99 MB | 108 MB |

O que sobra de lentidão é a própria simulação, que neste computador e nessa hora custou cerca de 7,5 s de CPU por sala. Ela é a mesma nos dois lados e não foi alterada, para não mudar resultados.

### Navegador

`frontend/scripts/verify-career.cjs`, com dois técnicos (desktop e celular de 390 px): **24/24**. Inclui:
- o mesmo placar e a mesma sequência de eventos para os dois técnicos;
- tática e substituição ao vivo;
- intervalo;
- a partida de 2:00 medida em 121,8 s;
- nenhum erro de console.

## 6. Limitações do Render Free

- **0,1 CPU.** Uma rodada custa cerca de 3,5 s de CPU de desktop por sala. Cerca de 3 salas jogando ao mesmo tempo cabem no tempo; acima disso, as rodadas atrasam, sem travar o servidor.
- **1 processo e 1 instância obrigatórios.** O estado das salas é a memória do processo, então mais workers quebrariam o multiplayer. Não foi adicionado banco de dados, conforme pedido.
- **Disco efêmero e hibernação após 15 min sem tráfego.** As salas se perdem num deploy ou numa hibernação. Isso exige um disco persistente (plano pago) ou um banco externo.
- **Medições locais têm ruído.** Este computador usa o governador `powersave`, e a mesma rodada custa de 3,6 a 8 s de CPU conforme o padrão de carga. Por isso as comparações foram feitas lado a lado, nas mesmas condições.
