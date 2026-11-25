# Relatório final — Resenha jogável (engine própria) e estado da integração PES 2013

**Data:** 24/11/2026.
**Branch:** `feature/pes-match-adapter`.

## Resumo

- **A integração com o PES 2013 Web NÃO está concluída e continua desligada.** Nenhum arquivo do runtime existe nesta máquina: worker, `.wasm`, `manifest.json`, saves, relay. Sem eles não há como comprovar carga de elenco, seleção de times, leitura de placar nem multiplayer. Ver `01-fase2-diagnostico.md`.
- O que foi entregue e testado com partidas reais usa a **engine própria do Resenha**, nunca apresentada como PES:
  - Corinthians × São Paulo iniciado pelo Resenha, sem escolher times;
  - controle completo por **teclado**;
  - **jogadores personalizados**, e jogadores comprados que jogam pelo clube novo;
  - **dois navegadores independentes** na mesma partida, com estado sincronizado pelo servidor;
  - resultado único registrado na competição e próxima fase liberada.

## 1. Funcionalidades realmente implementadas (com teste real)

| Funcionalidade | Evidência |
|---|---|
| Corinthians × São Paulo iniciado pela interface (Central → Próxima partida → Confirmar equipe), clubes definidos pelo Resenha | `docs/evidencias/pes-integration/cor-sao-*/run.log` |
| Jogo **todo por teclado**: ←/→ mira, ↑/↓ força, Tab escolhe companheiro (força calculada pela física), 1–5 tipo, Enter/Espaço executa, Esc cancela | `keyboardAim.test.ts` (5 testes); `scripts/keyboard-play.cjs` no Lab em 2D e 3D; partida multiplayer só com teclado, 25/25 |
| Jogadores personalizados: nome, posição, atributos (30–90), ID estável `CUS-…`, overall calculado pelos atributos (teto 80), até 3 por clube; entram no lugar de um atleta da mesma posição | `test_custom_players.py` (7 testes); tela "Elenco → Criar jogador" usada num navegador real (`criar-jogador/`) |
| Jogador comprado do São Paulo joga pelo Corinthians | verificação "player bought from SAO plays for COR" nas duas partidas |
| Atributos estimados por regra determinística (overall + posição), **a mesma do motor**, listados em `estimated_keys` | `test_match_contract.py` |
| Atributos mudam o jogo: força do time e velocidade máxima de cada atleta vêm deles | `test_attributes_change_how_the_team_plays` |
| Snapshot congelado no início da rodada; contrato (`MatchPayload` v1) com checksum SHA-256; o Zé da Resenha aparece como titular `CUSTOM` com os próprios atributos | `contrato-partida.json` das duas partidas |
| Multiplayer em dois navegadores independentes: mesma partida, placar idêntico, eventos registrados uma vez, ações duplicadas recusadas, reconexão após gol, técnico desconectado e de volta, troca 2D/3D no meio da partida, apito final nas duas telas | 27/27 (mouse, 2D × 3D, troca e desconexão) e 25/25 (só teclado, 2D × 3D) |
| Resultado gravado na competição e próxima fase liberada (final sorteada), volta à Central | idem |
| Duração competitiva respeitada (2:00 e 3:00) | idem (`competitive duration ... enforced`) |

## 2. Funcionalidades ainda bloqueadas

| Item | Bloqueio |
|---|---|
| PES 2013 Web: carga de elenco, seleção automática, início automático, placar, rede | Faltam os arquivos do runtime e a confirmação do direito de uso (lista exata em `01-fase2-diagnostico.md`, seção 3) |
| Escrita de `EDIT.bin` | Formato desconhecido; não será escrito sem a prova do experimento E3 |
| Multiplayer validado em **dois computadores físicos** | Os testes usam dois navegadores independentes na mesma máquina, sem nada compartilhado além do servidor. A sincronização é feita pelo servidor, então dois PCs se comportam igual, mas um teste com duas máquinas físicas ainda não foi feito |
| Controle contínuo do jogador (estilo PES) | A engine própria joga **momentos decisivos**: o técnico decide cada ação do portador da bola e a física e a IA executam. Não é controle contínuo de um atleta em tempo real |

## 3. Limitações conhecidas

- **Concordância ≠ autenticidade:** o livro de resultados externos exige que os dois técnicos relatem o mesmo placar, mas dois técnicos combinados confirmariam um placar falso. Na engine própria isso não se aplica: o servidor calcula o placar.
- Jogador personalizado só pode ser criado na pré-temporada ou com a janela aberta, e sempre substitui um atleta da mesma posição.
- O FPS medido nas capturas é de renderização por software (SwiftShader), não de hardware real.
- O teste `test_live_round` é sensível a tempo e falha às vezes com a máquina carregada; nas mesmas condições ele se comporta igual no `main` (ver `STATUS.md`).

## 4. Próximos passos

1. Fornecer os arquivos do PES Web e confirmar o direito de uso; então executar os experimentos E1–E7.
2. Um teste manual com dois computadores físicos na versão publicada.
3. Decidir se a engine própria deve ganhar controle contínuo de atleta.
