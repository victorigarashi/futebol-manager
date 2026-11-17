# Modo Carreira completo — entrega

Data: 17/11/2026. A carreira e a narrativa foram integradas em `4e3e7a5` (sobre `eb900f0`); a versão final fica sobre `31e12ce` (Draft e catálogo mundial). Visão geral da entrega V2: `docs/ENTREGA_V2.md`.

Duas sessões trabalharam em paralelo e dividiram o trabalho:

- **Sessão do Draft** (ver `docs/AUDITORIA_V2.md`): regras da sala V2, partida de 60 s, estilo Realista/Emocionante no motor, entrosamento e instruções individuais, bots por dificuldade, mata-mata ao vivo (playoffs e Copa do Brasil) e mercado avançado (compra, empréstimo, prazos, propostas de bots).
- **Esta entrega:** a camada de carreira e narrativa, o frontend inteiro da carreira e a câmera híbrida. A integração usa os nomes de regras e o modelo de mata-mata da outra sessão. Nada foi duplicado.

O Draft, o catálogo mundial e o painel de táticas e entrosamento foram feitos pela outra sessão (ver `docs/ENTREGA_V2.md`).

## 1. O que foi entregue

| Fase | Conteúdo | Onde |
|---|---|---|
| 0–1 | Auditoria; gols contra (não reproduzidos: 0 problemas em 506 gols, agora há teste de regressão); progressão realista e cumulativa | `docs/AUDITORIA_CARREIRA.md`, `domain/progression.py`, `test_goal_integrity.py`, `test_progression.py` |
| 2–4 | Feitas pela outra sessão (ver acima) | `docs/AUDITORIA_V2.md` |
| 5. Carreira | Moral e condicionamento opcionais; clássicos e retrospecto; eventos especiais no pré-jogo; central de notícias; estatísticas; Sala de Troféus; troca de clube entre temporadas | `services/career_service.py`, `season_service.py`, `api/routes.py` |
| Frontend | Criação da liga em duas seções com resumo; pré-jogo de mata-mata e Copa; cerimônia do sorteio; chave com agregado e pênaltis; página da Copa; Notícias, Estatísticas e Troféus; propostas de bots com prazo; seletor Troca/Compra/Empréstimo; câmera híbrida | `features/career/*`, `components/LeagueSettingsDialog.tsx`, `features/season/TransferHub.tsx`, `live/PitchCanvas.tsx` |

### Regras importantes

- **Fonte dos dados.** Tudo é calculado de partidas **já oficializadas**: eventos, escalações, notas, tabela, chaves e propostas. Uma rodada ao vivo nunca entra em estatísticas ou notícias, então nada é contado duas vezes nem antecipado.
- **Notícias.** Vêm só de templates locais sobre fatos reais: liderança, briga pela 8ª vaga, clássicos, goleadas, hat-tricks, mata-mata, títulos, transferências concluídas e evolução de overall. Os rumores apenas indicam uma proposta real de bot em aberto, **sem nenhum valor**.
- **Moral e condicionamento** (regra `morale_enabled`, desligada por padrão):
  - Fadiga: +0,10 por 90 minutos jogados, −0,08 por rodada sem jogar, teto de 0,3.
  - Moral do clube: de −3 a +3, conforme os resultados. Clássico vale o dobro; vitória por 3 gols ou mais soma +1.
  - Efeito no overall de cada jogador na próxima partida: de −3 a +1. Com a regra desligada o efeito é exatamente 0 (há teste).
  - Na pré-temporada a fadiga zera e a moral cai pela metade.
- **Troca de clube** (regra `coach_moves_enabled`):
  - Só entre temporadas: na janela da pré-temporada, antes da rodada 1.
  - O técnico só pode assumir um clube sem técnico humano. O bot daquele clube sai, e o clube antigo fica com treinador virtual.
  - Elenco e dinheiro ficam com os clubes. Os troféus registram o clube e o técnico da época.
- **Câmera híbrida:**
  - Por padrão mostra o campo inteiro.
  - Faz um zoom suave e moderado (até 1,32×) quando a bola entra no terço final ou há chute, defesa ou gol.
  - O botão "Câmera: dinâmica / campo inteiro" alterna o modo, e a escolha fica salva no navegador.
  - Com "reduzir movimento" o zoom fica desligado. O clique para selecionar jogador continua preciso, porque a transformação da câmera é desfeita no clique.

## 2. Testes executados (resultados reais)

| Suíte | Resultado |
|---|---|
| `test_career_narrative.py` (8 testes novos) | 8/8 |
| Ruff | limpo |
| Frontend `vitest` | 39/39 (1 novo: `competition.test.ts`) |
| TypeScript (`tsc -b`) e ESLint | limpos, sem avisos |
| Navegador real (`frontend/scripts/verify-career.cjs`, dois técnicos, desktop e celular de 390 px) | **27/27** (inclui as novas verificações de Notícias, Estatísticas e Troféus; partida de 2:00 medida em 118,9 s; mesmo placar nos dois clientes; nenhum erro de console) |

A suíte completa do backend, o `verify-draft.cjs` e a rodada final de todos os testes sobre a árvore integrada estão registrados em `docs/ENTREGA_V2.md`.

## 3. Como rodar (Ubuntu)

```bash
# backend
cd backend && python3 -m venv ../.venv && ../.venv/bin/pip install -r requirements-lock.txt
PLAYER_CATALOG_PATH=../data/catalogs/players.json ../.venv/bin/python -m uvicorn app.main:app --port 8000
# frontend
cd frontend && npm ci && VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npx vite --port 5173
# testes
cd backend && PLAYER_CATALOG_PATH=../data/catalogs/players.json ../.venv/bin/python -m pytest -q
cd frontend && npx tsc -b && npx eslint src && npx vitest run
```

Para o teste de navegador, ver `docs/MODO_CARREIRA.md` §4. A duração padrão esperada agora é 1:00.

## 4. Render

Sem mudanças na infraestrutura (`render.yaml`):

- um processo e um worker;
- Render Free;
- sem banco de dados;
- deploy automático a partir de `main`.

As novas rotas são `GET /rooms/{id}/career/stats|trophies|news` e `POST /rooms/{id}/coach/change`.

## 5. Limitações conhecidas

- **Salas efêmeras.** As salas continuam se perdendo num deploy ou na hibernação do Render Free, porque não há banco, por exigência do projeto. O histórico de temporadas, as estatísticas e os troféus vivem na memória e no snapshot local.
- **Notas no início da temporada.** "Melhores notas" e "Goleiros" só aparecem a partir de 3 jogos; a seleção da temporada também exige 3 jogos.
- **Ex-clube.** O evento "reencontra o ex-clube" usa o clube de origem do atleta no catálogo, não um histórico de transferências.
- **Câmera.** O zoom segue a bola do quadro anterior, uma diferença de um quadro, imperceptível.
