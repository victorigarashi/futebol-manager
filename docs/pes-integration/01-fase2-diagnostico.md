# Fase 2 — Diagnóstico do runtime PES 2013 Web

**Data:** 24/11/2026.
**Branch:** `feature/pes-match-adapter`, local, sem push e sem deploy.

**Resumo:** nada sobre o runtime pôde ser verificado, porque nenhum arquivo dele existe nesta máquina. Procurei `worker-DBuE8yY4.js` e `EDIT*.bin` no disco inteiro e não encontrei nada. Esta fase entrega:

- a **ponte isolada**;
- a **ferramenta de investigação**;
- a **lista exata de arquivos** necessários;
- o **plano de experimentos e de testes**.

O adaptador PES continua desligado, com todas as capacidades `False`.

## 1. O que se sabe e com que grau de certeza

| Informação | Origem | Estado |
|---|---|---|
| O runtime usa WebAssembly e um Web Worker (`worker-DBuE8yY4.js`) | análise anterior, relatada por você | **RELATADO, não verificado aqui** |
| O teclado vai ao worker em mensagens `input` com `keydown`/`keyup` | idem | RELATADO |
| Existe uma ponte Winsock/WebSocket com `open`, `bind`, `send` e `close` | idem | RELATADO |
| O relay só aceita `ws://localhost` ou `ws://127.0.0.1` | idem | RELATADO |
| Elenco personalizado, seleção automática de clubes, leitura do placar, multiplayer | — | **NÃO COMPROVADO** |
| O PES 2013 tem 5×5 | — | **NÃO** até prova em contrário. O modo 5×5 do Resenha teria de usar a engine atual. |

## 2. Arquitetura da integração (decidida, sem depender do runtime)

```
Brasileirão Manager (origem do jogo)                Máquina do usuário (outra origem)
┌───────────────────────────────────────┐        ┌───────────────────────────────────┐
│ MatchPayload v1 (backend, checksum)   │        │ página-anfitriã do runtime        │
│        │                              │        │   (escrita por nós, sem binários) │
│ PESRuntimeBridge ── postMessage v1 ───┼──────► │   └─ runtime PES do usuário       │
│  (origem conferida, mensagens         │ ◄──────┼──── (worker, wasm, dados)         │
│   validadas, capacidades só do        │        │ servidor local 127.0.0.1:porta    │
│   servidor)                           │        └───────────────────────────────────┘
│        │ resultado (se comprovado)    │
│ ExternalResultLedger (os dois técnicos│
│   confirmam o mesmo placar)           │
└───────────────────────────────────────┘
```

**Por que um iframe em outra origem, e não `new Worker(url)` dentro do jogo:** o runtime é código de terceiros. Na origem do jogo, ele teria acesso ao token de sessão no `localStorage` e a todo o app. Isolado:

- ele não lê nada do jogo;
- o jogo só aceita mensagens da origem esperada e no formato esperado;
- os binários ficam na máquina do usuário e **nunca entram no repositório nem no deploy**.

**Teclado.** Enquanto se joga, o iframe tem o foco e recebe o teclado diretamente; o app não repassa teclas. Repassar teclas entre dois PCs é transporte de entrada, não sincronização de partida.

**Código entregue nesta fase:**

- `frontend/src/features/external-engines/pes/protocol.ts`:
  - protocolo v1;
  - `validateRuntimeOrigin`: só `localhost`/`127.0.0.1`, com porta, em origem diferente da do jogo e sem credenciais;
  - `parseHostMessage`: descarta mensagens de outra origem, de outra versão ou de formato desconhecido, e exige resultado com o checksum do contrato e gols inteiros;
- `frontend/src/features/external-engines/pes/bridge.ts`:
  - a interface `PESRuntimeBridge`, com o ciclo UNAVAILABLE / IDLE → CONNECTING → READY → PREPARING → IN_MATCH → FINISHED, ou FAILED;
  - `assertCanPrepare`: não entrega uma partida sem elenco, seleção de times e modo comprovados;
  - a única implementação, `UnavailablePESRuntimeBridge`, que recusa tudo;
- `backend/tools/pes_runtime_inventory.py`: inventário **estático** (lê bytes, não executa nada) dos arquivos que você fornecer. Para cada pergunta abaixo, aponta arquivo, posição e trecho;
- testes: `bridge.test.ts` (5) e `test_pes_runtime_inventory.py` (2, com arquivos sintéticos).

A implementação real da ponte, com o iframe e a página-anfitriã, **só será escrita depois** que os experimentos da seção 4 mostrarem o que o runtime aceita.

## 3. Arquivos de que preciso, exatamente

Antes de tudo, **confirme que você tem o direito de usar esse runtime** (licença do port e do jogo). O PES 2013 é software comercial da Konami. Nada disso entra no repositório: ficará numa pasta fora dele, por exemplo `~/pes-runtime/`, e eu só leio.

| # | Arquivo | Para quê | Obrigatório |
|---|---|---|---|
| 1 | **A pasta completa do PES 2013 Web, como é servida no navegador**: `index.html`, o JS principal (`index-*.js`/`main-*.js`), `worker-DBuE8yY4.js`, os `.wasm`, o `manifest.json` e os pacotes de dados | Ver como o worker é criado, que mensagens recebe, que arquivos monta e de onde | **Sim** |
| 2 | Se a pasta for grande demais: os itens de texto (`index.html`, todos os `.js`, `manifest.json`) mais a **lista** dos binários com nome e tamanho (`find . -type f -printf '%s %p\n'`) | Começar a análise sem copiar gigabytes | Alternativa ao 1 |
| 3 | **Documentação do port**: README, licença, página do projeto, parâmetros de URL (`netRelay` e outros) | Saber se há configuração oficial de times, saves ou rede antes de investigar binário | Sim, se existir |
| 4 | **Dados salvos pelo runtime**, em dois momentos: depois de abrir o jogo pela primeira vez, e depois de **editar um único jogador** dentro do jogo (por exemplo, trocar o nome e a velocidade) e salvar. Exportar do navegador: DevTools → Application → IndexedDB / Local Storage / Storage | Descobrir onde e em que formato o jogo guarda a edição. É o único caminho seguro para entender o formato do elenco: o próprio jogo grava, e comparamos antes e depois | **Sim**, para a carga de elenco |
| 5 | O **MVP do relay** (FastAPI e o bridge Python) da análise anterior | Revisar segurança e protocolo antes de qualquer teste de rede | Só para a Fase 4 |
| 6 | Uma **gravação de tela** ou anotação do caminho no menu até uma partida amistosa entre dois times, com a versão do jogo visível | Saber o que teria de ser automatizado se não houver API de seleção | Recomendado |

Com o item 1 ou 2, rode:

```bash
cd backend && ../.venv/bin/python -I tools/pes_runtime_inventory.py ~/pes-runtime > ~/pes-inventario.json
```

## 4. Experimentos, em ordem, com critério de aprovação

Cada capacidade só passa a `True` em `Pes2013Adapter.capabilities` com evidência registrada aqui: comando, captura e resultado.

| # | Pergunta | Experimento | Aprovado quando |
|---|---|---|---|
| E1 | O runtime roda isolado em outra origem? | Servir a pasta em `127.0.0.1:8765` e abrir num iframe a partir do jogo | Partida amistosa manual jogável dentro do iframe, com o teclado funcionando |
| E2 | Onde ficam os dados de elenco? | Inventário (seção 3) mais a comparação antes/depois do item 4 | Arquivo e região alterados identificados, com explicação de como a edição feita no jogo mudou os bytes |
| E3 | O runtime lê um elenco modificado por fora? | Alterar **só** o nome de um jogador fictício no arquivo salvo (round-trip byte a byte do que o próprio jogo gravou) e recarregar | O nome alterado aparece no jogo. Se o arquivo tiver checksum, ele precisa estar documentado antes. **Sem isso, nada de escritor de `EDIT.bin`.** |
| E4 | É possível mapear atributos? | Repetir o E3 com um atributo (velocidade) e medir os limites aceitos | Valor aceito e exibido; limites documentados → `PlayerStatMapper` com tabela explícita |
| E5 | É possível escolher mandante e visitante sem clicar? | Procurar parâmetros de inicialização, estado salvo de "último confronto" ou mensagens do worker | Partida iniciada com os dois times certos, sem clique. Senão, `can_select_teams` e `can_auto_start_match` ficam `False` |
| E6 | É possível ler o placar final? | Procurar o placar no estado salvo, nas mensagens do worker ou na memória exposta | Placar lido em 5 partidas, igual ao da tela em todas. Senão, `can_read_result` fica `False`, e um resultado digitado pelos técnicos precisaria da confirmação dupla do `ExternalResultLedger` |
| E7 | Multiplayer (Fase 4) | Só depois do E1, com tráfego observável no relay local e depois em dois PCs autorizados | Os dois clientes jogam a **mesma** partida e terminam com o **mesmo** placar. Trocar pacotes não basta |

## 5. Plano de testes — Corinthians × São Paulo

**Dados reais do catálogo** (`brasileirao-fcm27-2026-11-15`):

- **Corinthians (COR):** 16 jogadores (2 GK, 7 DF, 4 MF, 3 ST). **Só 7 têm atributos.** Por exemplo, Hugo Souza (GK 79) e Yuri Alberto (ST 78) têm; Rodrigo Garro (MF 78) e Memphis Depay (ST 78) **não têm**.
- **São Paulo (SAO):** 16 jogadores (2 GK, 6 DF, 5 MF, 3 ST). **Só 7 têm atributos.** Marcos Antônio (MF 78) e Lucas Moura (MF 77) têm; Calleri (ST 77) **não tem**.

**Jogadores personalizados:** o projeto **não tem** essa funcionalidade (ver a auditoria). Os casos com "personalizados" abaixo ficam **bloqueados** até você decidir criá-la no produto. Nada será simulado com dados inventados.

### A. Sem o runtime (automatizáveis já, com a engine atual como referência)

| ID | Caso | Verificação |
|---|---|---|
| A1 | Rodada com COR (mandante) × SAO | `MatchPayload` com `home.club_code == "COR"` e `away.club_code == "SAO"`, 11 titulares cada, 1 GK cada |
| A2 | Jogador comprado (ex.: um titular do SAO vendido ao COR antes da rodada) | Ele aparece no COR e não no SAO |
| A3 | Mercado muda depois do início | Mesmo checksum |
| A4 | Garro, Memphis e Calleri (sem atributos) | `provenance = OVERALL_ONLY` e `attributes = {}`. Nenhum valor inventado; a regra para o PES fica pendente da sua decisão |
| A5 | Contrato adulterado | Recusado pelo adaptador e pela ponte (checksum) |
| A6 | Engine PES pedida | `prepare/PES2013_WEB` recusa; a partida acontece na engine do Resenha |
| A7 | Resultado informado pelos dois técnicos | COR 2×1 SAO nos dois relatos → confirmado e gravado uma vez; relatos divergentes → disputado, nada gravado |

### B. Com o runtime (cada um depende do experimento indicado)

| ID | Depende de | Caso | Aprovado quando |
|---|---|---|---|
| B1 | E1 | PES abre isolado no jogo, amistoso manual | Partida jogável; o jogo não perde a sessão; nenhum erro de origem |
| B2 | E3/E4 | Elenco do COR e do SAO exportado do contrato | No jogo, os 11 titulares de cada lado com nome, posição e atributos iguais ao contrato, conferidos um a um |
| B3 | E3/E4 | Jogador comprado (A2) | No PES ele veste a camisa do COR |
| B4 | E4 + sua decisão | Jogadores sem atributos | Aplicam a regra decidida por você, documentada. Nunca um valor "chutado" |
| B5 | E5 | "Jogar partida" | COR mandante e SAO visitante, sem seleção manual |
| B6 | E5 | Dois cliques em "Jogar partida" | Uma única partida |
| B7 | E6 | Fim de jogo | Placar lido igual ao da tela; vai ao `ExternalResultLedger` com o checksum; a tabela é atualizada uma vez |
| B8 | E6 | Runtime fecha ou trava no meio | Estado FAILED com mensagem, sem resultado; a partida pode ser jogada na engine atual |
| B9 | personalizados | Atleta criado pelo usuário no COR | **Bloqueado**: a funcionalidade não existe no produto |
| B10 | E7 | Dois PCs, um técnico por clube | Mesma partida e mesmo placar nas duas telas; desconexão e reconexão testadas |

## 6. O que não será feito sem evidência

- Escrever `EDIT.bin` (regra 5). Só depois do E3, com formato documentado (offsets, codificação e checksum) e round-trip validado.
- Habilitar o adaptador PES (regra 6). Ele só fica disponível quando B1, B2, B5 e B7 passarem numa partida real.
- Automatizar cliques no menu como solução definitiva. Se for o único caminho, ela será documentada como frágil e aparecerá como experimental.
