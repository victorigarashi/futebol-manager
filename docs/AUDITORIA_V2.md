# Auditoria do Prompt Master V2

Data: 17/11/2026. Base: `main` em `68c040a` (Fases 0 e 1 da carreira já entregues).

Esta auditoria complementa a [Auditoria do Modo Carreira](AUDITORIA_CARREIRA.md). Ela não a substitui: o que já foi medido lá não foi refeito, só referenciado.

Legenda: ✅ existe e funciona · 🟡 existe, mas incompleto ou divergente do V2 · ❌ não existe · 🐞 bug relatado.

## 1. Matriz de funcionalidades

### Base e arquitetura (§2)

| Item | Estado | Evidência |
|---|---|---|
| FastAPI + Pydantic, React + TS + Vite, WebSocket | ✅ | `backend/app`, `frontend/src` |
| Estado em memória, lock por sala, idempotência | ✅ | `services/season_service.py`, `services/market_service.py` |
| Simulação determinística por semente | ✅ | `domain/match_engine.py`, `test_match_engine.py` |
| Sem banco; snapshots JSON (não duráveis no Render Free) | ✅ | `services/snapshot_store.py` |
| 20 clubes, humanos + bots, 5×5 e 11×11, 38 rodadas | ✅ | `domain/season.py`, `domain/rooms.py` |

### Simulação e transmissão (§11, §12)

| Item | Estado | Evidência / observação |
|---|---|---|
| Gols contra excessivos | 🐞 não reproduzido | O motor não tem evento de gol contra. Em 100 partidas (506 gols), houve 0 autorias invertidas (`test_goal_integrity.py`). Falta um print ou o id da partida para investigar. Gol contra raro e plausível pode entrar como mecânica nova. |
| Placar ao vivo | ✅ corrigido | Fonte única de eventos; teste de não vazamento do futuro. |
| **Partida de 60 s** | ✅ | Adicionada como padrão (perfil próprio em `broadcast.PROFILES[60]`). Resolve a pendência da Fase 0. |
| Estilos Realista/Emocionante | ❌ | — |
| Câmera híbrida | ❌ | `PitchCanvas.tsx` só mostra o campo inteiro. |
| Qualidade das jogadas 2D | 🟡 | Passes, através e cruzamentos existem no motor; faltam tabelas, recomposição e goleiro mais crível. |

### Táticas (§6, §7, §8)

| Item | Estado | Evidência / observação |
|---|---|---|
| Estilos | ✅ | `POSSESSION`, `COUNTER`, `DIRECT`, `SHORT_BUILDUP`, `WIDE`; mais pressão `LOW`, `MEDIUM`, `HIGH` (`domain/tactics.py`). "Pressão alta" é um eixo próprio, não um estilo; "Defesa compacta" não existe e equivale a mentalidade defensiva + pressão baixa. **Será reaproveitado, não recriado.** |
| Mentalidade ao vivo, formação, substituições | ✅ | 5 níveis (o V2 cita 3; os 5 atuais incluem esses 3). |
| Compatibilidade tática | ❌ | — |
| Familiaridade tática | ❌ | — |
| Instruções individuais | ❌ | — |
| **Limite de dados** | ⚠️ | Só **116 de 320** atletas têm atributos detalhados. Os outros 204 usam um perfil derivado do overall por posição (`derived_attributes`). Para eles, a compatibilidade será **marcada como estimada** e não terá dados inventados. |

### Economia, mercado e bots (§9, §10, §13, §14)

| Item | Estado | Evidência / observação |
|---|---|---|
| Orçamentos de R$ 50 a 200 mi | ✅ | Valores em centavos inteiros. |
| Orçamentos de R$ 300 mi, 400 mi, 500 mi e 1 bi | ❌ | — |
| Mercado inicial secreto | ✅ | `domain/market.py` |
| Janela após a rodada 19 (troca, venda, contraproposta) | ✅ | `services/transfer_service.py` |
| Bots propondo aos humanos, disputas, prazos, valorização dinâmica | ❌ | — |
| Jogador + dinheiro numa mesma proposta | 🟡 | Troca existe; falta verificar a combinação com dinheiro. |
| Janela entre temporadas | ❌ | — |
| Empréstimos | ❌ | — |
| Dificuldade dos bots (Casual, Competitivo, Lendário) | ❌ | `domain/bot_coach.py` tem um único nível. |

### Progressão e carreira (§15, §16, §19 a §24)

| Item | Estado | Evidência / observação |
|---|---|---|
| Evolução e regressão | ✅ corrigido na Fase 1 | Usa idade, minutos, nota, gols e assistências, com teto no potencial, valor cumulativo e idempotência. **Lacuna:** os atributos ainda acompanham o overall em bloco. |
| Moral e condicionamento | ❌ | — |
| Clássicos, eventos especiais, notícias completas, estatísticas avançadas, Sala de Troféus, mudança de técnico | ❌ | Hoje só há notícias resumidas no `ClubHub`. |

### Competições (§17, §18)

| Item | Estado | Evidência / observação |
|---|---|---|
| Playoffs com 8 clubes | 🟡 | Simulados instantaneamente; chave fixa 1×8; só jogo único. |
| Sorteio por potes + cerimônia | ❌ | — |
| Ida e volta + agregado | ❌ | — |
| Premiações acumulativas | 🟡 | Hoje: R$ 10, 20 e 50 mi (`season_service.py:831-845`). Pedido: 50, +100, +150 e +200. |
| Copa do Brasil | ❌ | — |

### Draft (§4.2, §5, §31)

| Item | Estado | Evidência / observação |
|---|---|---|
| Modo Draft completo | ❌ | Não existe. O modelo atual liga atleta a clube por id de catálogo (exclusividade). O Draft precisa de **instâncias** (`instance_id` ≠ `catalog_id`). |
| Catálogo Brasileirão | ✅ | 320 atletas FCM 27. Todos `SUPPLIED_SQUAD_LIST`; 40 GK, 138 DF, 82 MF, 60 ST; overall de 63 a 84. |
| Catálogo Mundial | 🟡 | A pesquisa já existe. `data/importers/eafc26_importer.py` usa o EAFC26-DataHub / Kaggle (**CC BY 4.0**, 18.405 atletas, 110 colunas). Ressalva já documentada em `CATALOG_SOURCES.md`: a licença do dataset não cobre marcas, imagem nem direitos de personalidade. **Sem fotos.** Falta o catálogo `world` promovido e integrado. |
| Filtro de overall mínimo | ❌ | Com o catálogo nacional e 11×11, um mínimo alto deixa poucos GK: só 40 no total. A viabilidade precisa ser validada. |

### Visual (§3) e performance (§28)

| Item | Estado | Evidência / observação |
|---|---|---|
| Design system com tokens | ✅ | `docs/DESIGN_SYSTEM.md` |
| Redesign premium | ❌ | — |
| Backpressure, frames descartáveis, reconexão | ✅ | `docs/ESTABILIDADE_MULTIPLAYER.md` |
| Limite medido | — | Cerca de 3 salas simultâneas no Render Free. |

## 2. Problemas confirmados vs. relatados

1. **Gol contra:** relatado, não reproduzido. Já há teste de regressão. Ação: pedir uma evidência ao usuário; não "corrigir no texto".
2. **Placar ao vivo:** corrigido e testado.
3. **Progressão:** corrigida na Fase 1. A diferenciação por atributo fica para a Fase 3, junto com o entrosamento.
4. **Duração de 60 s:** ausente. Agora está aprovada.
5. **Premiações e chave dos playoffs:** divergentes do pedido.
6. **Atributos parciais no catálogo:** 204 de 320 atletas sem detalhamento. Isso limita a precisão do entrosamento.

## 3. Plano de fases (numeração do V2)

| Fase | Conteúdo | Estado |
|---|---|---|
| 0. Auditoria | Este documento + `AUDITORIA_CARREIRA.md` | ✅ |
| 1. Bugs críticos | Integridade de gols, placar, progressão, transição de temporada; **partida de 60 s** (novo padrão; 1:30, 2:00 e 3:00 continuam como opção; snapshots antigos mantêm 1:30) | ✅ |
| 2. Simulação e 2D | Realista/Emocionante, formação ao vivo, instruções no movimento; câmera híbrida (sessão da carreira) | 🟡 motor de passes/goleiro não reescrito |
| 3. Táticas e entrosamento | Compatibilidade, familiaridade, instruções, efeito calibrado, bots | ✅ |
| 4. Mercado e economia | Orçamentos até 1 bi, bots por dificuldade, compra, troca, empréstimo, prazos, disputas, janela entre temporadas | ✅ |
| 5. Draft | Instâncias, 3 cartas, sorteio equilibrado, reservas livres, overall mínimo, bots, telas | ✅ |
| 6. Catálogo mundial | Identidade CC0 + avaliação editorial própria; sem dados da EA | ✅ |
| 7. Competições e carreira | Playoffs e Copa ao vivo (esta branch); moral, clássicos, notícias, estatísticas, troféus, troca de técnico (sessão da carreira) | ✅ |
| 8. Redesign visual | Telas novas de Draft, entrosamento e carreira; tela inicial e mercado inicial mantidos | 🟡 |
| 9. QA completo | pytest, ruff, tsc, eslint, vitest, build, navegador (Draft 15/15, carreira 27/27) | ✅ |

Fica fora até nova aprovação: pênaltis interativos, olheiros, química por liga ou nacionalidade, e tudo o que está listado em §25.

Resultado final: [ENTREGA_V2.md](ENTREGA_V2.md).
