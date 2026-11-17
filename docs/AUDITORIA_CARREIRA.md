# Auditoria do Modo Carreira (Fase 0)

Data: 17/11/2026. Base: `main` em `14ac85d`. Esta auditoria inspeciona o código real. Onde algo foi medido, o comando está indicado.

## 1. O que já existe e funciona

| Área | Situação | Onde |
|---|---|---|
| Multiplayer (sala, código, WebSocket, servidor autoritativo, locks) | Funciona. Estado sequenciado (`live.state`), backpressure, recuperação em fatias após reinício. | `services/realtime.py`, `services/season_service.py`, `api/routes.py` |
| 20 clubes, 5×5 e 11×11, bots nos clubes livres | Funciona. Também há ligas personalizadas de 4 a 20 clubes, em turno único ou ida e volta. | `domain/season.py`, `domain/rooms.py` |
| Catálogo | 320 atletas reais (FCM 27) com foto; os genéricos só completam elenco. | `data/catalogs/players.json` |
| Mercado inicial (lances secretos, reservas, desempate, idempotência; dinheiro ou moedas) | Funciona e tem testes. | `domain/market.py`, `services/market_service.py` |
| Janela de transferências após a rodada 19 | Existe: troca entre clubes, venda anunciada, contraproposta (`counter_cents`), compra de atleta livre. | `services/transfer_service.py` |
| Partida ao vivo 2D (transmissão condensada de 1:30, 2:00 ou 3:00; táticas e substituições ao vivo; bots táticos) | Funciona. Resultados idênticos com mesma semente. | `domain/match_engine.py`, `domain/broadcast.py`, `domain/bot_coach.py` |
| Playoffs (8 primeiros, jogo único, pênaltis) | Existem, com limitações (ver §3). | `domain/playoffs.py`, `_advance_playoffs` |
| Premiações | Pagas uma única vez por id de operação (idempotente). Os valores diferem do pedido (ver §3). | `_pay_award` |
| Progressão de jogadores | Existe, mas é tímida e tem bugs (ver §2). | `domain/progression.py`, `_apply_progression` |
| Nova temporada | Mantém elencos, saldos e overall; exige campeão e progressão aplicada. | `create_next_season` |
| Snapshots JSON | Incrementais e gravados fora do event loop. **Não são duráveis no Render Free.** | `services/snapshot_store.py` |

## 2. Bugs e defeitos confirmados

### 2.1 Gols contra excessivos: não reproduzido no código atual

**Medição:** 100 partidas com sementes fixas (60 em 11×11 e 40 em 5×5, 506 gols), com o script de auditoria transformado em teste (`test_goal_integrity.py`).

| Verificação | Problemas |
|---|---|
| Autor do gol pertence ao time creditado | 0 |
| Assistência do mesmo time | 0 |
| Finalização anterior do mesmo time e do mesmo jogador | 0 |
| Gol no gol que o time ataca (evento e frame 2D) | 0 |
| Placar igual aos eventos | 0 |
| Orientação do campo (desktop: mandante → direita; celular: mandante → cima) igual à legenda | correta |

**Conclusão:** o motor **não gera gols contra** (não existe esse tipo de evento) e não houve nenhuma atribuição invertida.

O relato provavelmente vem de versões anteriores, quando a transmissão travava e reiniciava, ou de uma leitura visual que não conseguimos reproduzir.

O que foi feito:
- as invariantes viraram **teste de regressão**;
- se a mesma impressão voltar a aparecer, é preciso um print ou o id da partida para investigar;
- nenhuma probabilidade foi alterada sem medição;
- gols contra raros e plausíveis podem entrar como mecânica nova, mas isso é uma decisão de design e não está nesta fase.

### 2.2 Placar ao vivo: corrigido nas entregas recentes, verificado

O placar mostrado vem dos eventos já exibidos na tela. Há uma única fonte (`engine.events` até o tick em exibição) para HTTP, `live.state` e transmissão.

O defeito relatado ("placar só certo no final") batia com o período em que o servidor travava (simulação no event loop, reinícios). Isso foi resolvido em `docs/ESTABILIDADE_MULTIPLAYER.md`.

Os testes `test_live_state_is_incremental_sequenced_and_never_reveals_the_future` e `test_goal_integrity.py` cobrem:
- o placar a cada instante;
- a sequência de eventos;
- a ausência de vazamento do futuro.

No navegador, os dois técnicos veem o mesmo placar e a mesma sequência (24/24).

### 2.3 Progressão de jogadores: bugs confirmados (corrigidos na Fase 1)

1. **Gols nunca contavam.** Em `_apply_progression`, o `continue` depois de ler os minutos por jogador pulava a contagem de gols.
2. **Valor não acumulava.** O valor era recalculado como "valor original × depois/antes da temporada atual", então a valorização de uma temporada sumia na seguinte.
3. **Progressão quase inexistente.**
   - No máximo ±1 de overall por temporada.
   - Atletas de 24 a 29 anos com minutos **nunca** mudavam.
   - Desempenho (nota média, gols, assistências) não influenciava.
4. **Fora do recorte desta fase.** Os atributos acompanham o overall em bloco (o motor desloca todos pelo mesmo delta). Isso é coerente, mas não diferencia perfis.

### 2.4 Outros defeitos e lacunas

- **Playoffs simulados instantaneamente.** O anfitrião clica e quartas, semis e final são calculadas sem transmissão 2D nem controle tático. O pedido exige partidas jogadas ao vivo.
- **Chaveamento fixo** (1×8, 2×7…), sem sorteio por potes, e só em jogo único.
- **Premiações** de R$ 10 mi (quartas), R$ 20 mi (semis) e R$ 50 mi (título), sem prêmio de vice. O pedido é R$ 50 mi, +100, +150 e +200 acumulativos.
- **Orçamentos:** só R$ 50, 100, 150 e 200 mi.
- **Não existem:** dificuldade de bots, estilo Realista/Emocionante, janela entre temporadas, ofertas iniciadas por bots, moral e condicionamento, Copa do Brasil, clássicos, central de notícias (há só notícias resumidas na central do clube), estatísticas avançadas, Sala de Troféus e mercado de técnicos.
- **Duração das partidas.** O pedido diz "continuam durando 60 segundos", mas o jogo oferece **1:30, 2:00 e 3:00** (padrão 1:30), conforme pedido anterior. Para não mudar uma regra sem confirmação, **60 s não foi adicionado**. É uma decisão pendente do dono do projeto.

## 3. Riscos

- **Concorrência.** As operações sensíveis estão sob o lock da sala, com idempotência por id. Novos fluxos (ofertas de bots, trocas, sorteio, premiações por fase) devem seguir o mesmo padrão.
- **Desempenho no Render Free (0,1 CPU).** Cada rodada de 10 jogos custa cerca de 3,5 s de CPU de desktop. Playoffs ao vivo e Copa do Brasil acrescentam rodadas, não carga simultânea. Cerca de 3 salas jogando juntas é o limite medido.
- **Durabilidade.** Sem banco (por exigência), as salas se perdem num deploy ou na hibernação do Render Free. Os snapshots ajudam só em reinícios na mesma instância.

## 4. Testes atuais

- **Backend:** 158 testes (pytest), Ruff limpo e pipeline do catálogo.
- **Frontend:** 38 testes (vitest), typecheck, lint e build.
- **Navegador:** `frontend/scripts/verify-career.cjs`, com 24 verificações e dois técnicos.
- **Carga:** `backend/tools/load_test.py`, com cota de 10% de CPU.

## 5. Plano de execução por fases

| Fase | Conteúdo | Estado |
|---|---|---|
| 1. Núcleo | Teste de integridade de gols; progressão corrigida e realista (idade, minutos, nota, gols e assistências, teto de potencial, valor cumulativo, idempotência); continuidade entre temporadas testada. | **Em andamento** |
| 2. Simulação e 2D | Câmera híbrida; leitura das jogadas (passes, chutes, goleiro); estilos Realista/Emocionante. | Pendente |
| 3. Economia, bots e mercado | Orçamentos até R$ 1 bi; dificuldade dos bots (qualidade de decisão, sem trapaça); ofertas de bots; trocas; janela entre temporadas; preços dinâmicos. | Pendente |
| 4. Competições | Sorteio por potes, único; playoffs ao vivo, em jogo único ou ida e volta, com agregado e pênaltis; premiações acumulativas; Copa do Brasil opcional. | Pendente |
| 5. Carreira e narrativa | Moral e condicionamento opcionais; clássicos; eventos especiais; notícias; estatísticas; troféus; mercado de técnicos. | Pendente |
| 6. Redesign visual | Telas revisadas sobre fluxos já validados. | Pendente |
| 7. QA | Ciclo completo: temporada, playoffs e nova temporada; carga; navegador. | Pendente |
