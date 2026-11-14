# API e tempo real

Contrato detalhado gerado do FastAPI em [openapi.json](openapi.json). Com o servidor em execução, consulte `/docs` ou `/openapi.json`.

Todas as rotas de jogo usam prefixo `/api/v1`, cookie assinado HttpOnly `bm_session` e respostas `{data, meta}`. Dinheiro usa centavos inteiros; somente a interface formata reais. Um conflito de estado/regra retorna 409, identidade inválida 401, falta de permissão 403, validação de entrada 422 e limitação 429. A ausência de catálogo autorizado não é substituída por dados reais inventados.

| Fluxo | Endpoints principais |
|---|---|
| Identidade | `POST /auth/guest`, `GET /me`, `PUT /me` |
| Salas | `GET/POST /rooms`, `GET /rooms/mine`, `POST /rooms/join`, `POST /rooms/{id}/join`, `GET /rooms/{id}/state`, `PUT /rooms/{id}` |
| Clube | `GET /clubs`, `PUT /rooms/{id}/participants/me/club` |
| Mercado | `POST /rooms/{id}/start`, `GET /rooms/{id}/market`, `GET /rooms/{id}/market/players`, `GET /rooms/{id}/market/players/{player}` |
| Ofertas privadas | `POST /rooms/{id}/market/offers`, `PUT/DELETE /rooms/{id}/market/offers/{offer}` |
| Confirmação | `GET /rooms/{id}/market/selection`, `POST /rooms/{id}/market/selection/preview`, `POST /rooms/{id}/market/selection/confirm` |
| Redistribuição/review | `GET /rooms/{id}/market/reassignment`, `POST /rooms/{id}/market/reassignment/{offer}`, `GET /rooms/{id}/market/review`, `POST /rooms/{id}/market/review/complete` |
| Elenco | `GET /rooms/{id}/squad`, `PUT /rooms/{id}/squad/lineup`, `PUT /rooms/{id}/squad/strategy` |
| Temporada | `POST /rooms/{id}/season/start`, `GET /rooms/{id}/season`, `POST /rooms/{id}/season/ready`, `POST /rooms/{id}/season/advance` |
| Transmissão | `GET /rooms/{id}/season/live`, `GET /rooms/{id}/matches/{match}` |
| Transferências | `GET /rooms/{id}/transfers`, `/transfers/available`, `/transfers/clubs`; `POST /transfers/buy`, `/transfers/offers`, `/transfers/offers/{offer}/accept`, `/reject`, `/counter`, `/cancel`; `PUT /transfers/listings` |
| Carreira | `GET /rooms/{id}/career`, `POST /rooms/{id}/season/next`, `POST /rooms/{id}/season/transfer-window/close` |

O clube é derivado da identidade e da sala pelo backend. Não aceite clube, orçamento ou estatísticas autoritativas do navegador. Ofertas perdedoras e valores de outros técnicos não são publicados durante a fase secreta.

## WebSocket

`/api/v1/ws/rooms/{id}` autentica o mesmo cookie e valida associação e Origin. Após abrir/reabrir, o cliente deve reconsultar o estado autoritativo. `season.sync` contém a visão personalizada da transmissão. Notificações incluem mudanças de sala/mercado, `season.round_started`, `season.tick` e `season.round_completed`.

As notificações são invalidações, não um log garantido de entrega. A interface reconsulta e usa polling de recuperação. O relógio tem `started_at`, `ends_at` e `server_now` em segundos Unix. Durante 60 segundos reais o replay avança 90.000 ms; só o prefixo de eventos liberado é público. Todos os resultados oficiais entram juntos no encerramento.

## Novos contratos da beta

`GET /rooms/mine` retorna somente as salas do próprio usuário, incluindo privadas/iniciadas. A lista pública mostra salas que ainda aceitam entrada. Reentrar numa sala própria é permitido; trocar clube ou adicionar novos participantes depois do início é proibido.

`GET /rooms/{id}/career` retorna saldo, reservas de transferência, disponível, extrato, propostas próprias, histórico de temporadas e desenvolvimento de atletas do elenco. `internal_market_value_cents` é uma avaliação interna calculada pela carreira, distinta da avaliação original do catálogo.

`PUT /rooms/{id}/transfers/listings` recebe `{player_id, listed}`. É um anúncio sem débito, não uma venda automática. Negociações preservam a posição e o tamanho dos elencos.
