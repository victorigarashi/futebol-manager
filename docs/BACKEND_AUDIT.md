# Auditoria e estabilização do backend — beta

Esta revisão preserva FastAPI/Pydantic, WebSockets, estado em memória, snapshots JSON e uma única instância/processo. Nenhum banco ou serviço pago foi adicionado.

## Achados e correções

| Prioridade | Problema encontrado | Correção aplicada |
| --- | --- | --- |
| P0 | Um técnico podia mudar de clube depois do início e assumir a visão/elenco de outro time. Novos humanos podiam entrar em temporadas já iniciadas sem um clube preparado. | `RoomManager.select_club` congela a seleção após WAITING; repetir o mesmo clube permanece idempotente. `join` permite retorno de membros existentes, mas bloqueia novos membros após o início. |
| P0 | Era possível iniciar o mercado com participantes humanos ainda sem clube; validar apenas depois de criar o mercado deixaria uma task órfã. | Validação de todos os clubes na rota **antes** da criação da sessão/timer e também na autoridade de domínio. |
| P0 | Tokens Unicode ou payloads malformados podiam gerar erro 500 antes da validação da assinatura. | Parsing limitado, assinatura e validação de estrutura num único bloco protegido; identidade inválida retorna 401. Cookies HttpOnly/SameSite preservados, agora persistentes por um ano. |
| P0 | Compra de jogador livre desconsiderava dinheiro reservado em outras propostas de transferência. | A compra usa a mesma verificação de reservas das negociações. Identificadores de operação são escopados por clube, evitando colisões entre compradores. |
| P0 | O vendedor conseguia aceitar a contraproposta que ele próprio havia feito. | O destinatário autorizado depende do estado: vendedor em PENDING, comprador em COUNTERED; repetição de ACCEPTED por participantes não repete o débito. |
| P0 | Produção podia iniciar com segredo público de desenvolvimento e cookie inseguro. | `APP_ENVIRONMENT` padrão é development. Quando definido como production, exige segredo exclusivo de ao menos 32 caracteres, cookie Secure e CORS HTTPS explícito. Demo continua proibido em produção. |
| P1 | Propostas pendentes de uma janela anterior continuavam reservando saldo em outra temporada. | Fechamento da janela cancela PENDING/COUNTERED e limpa anúncios, preservando o histórico. |
| P1 | Bots podiam fazer contrapropostas incompatíveis com o saldo do técnico. | A decisão do bot valida a contraproposta antes de reservá-la; se não couber, a proposta é recusada. |
| P1 | Valores e overall de carreira exibidos/avaliados podiam continuar usando o catálogo inicial após evolução. | Endpoints de elenco/carreira expõem overall atual, base, variação e avaliação interna. Compra mínima e decisões dos bots usam a avaliação interna atual; a escalação recalcula overall efetivo com os atributos atuais. O catálogo autorizado permanece inalterado. |
| P1 | Formação padrão 5x5 do replay usava 1-2-1, embora o elenco mínimo fosse GK1/DF2/MF1/ST1. | Formação 2-1-1 adicionada e adotada no fallback; todas as formações anteriores permanecem disponíveis. |
| P1 | Comandos de escalação/estratégia ainda eram aceitos durante transmissão. | Rotas retornam 409 até terminar a rodada. O fluxo de eventos e as formações congeladas permanecem consistentes. |
| P1 | Um snapshot com várias salas podia hidratar a primeira antes de detectar corrupção semântica na seguinte. | Recuperação executa preflight em serviços isolados sem timers antes de publicar qualquer sala. Calendário verifica 20 clubes, 38 rodadas, 380 pares e presença única por rodada; placares negativos são rejeitados. |
| P1 | Perder/bloquear localStorage removia a única referência à sala, mesmo com cookie válido. | `GET /rooms/mine` retorna somente salas do usuário, incluindo privadas e iniciadas; o cliente pode retomar usando a identidade assinada. Salas públicas para novos participantes são somente WAITING. |
| P1 | Não havia limites de requisição/corpo, e a origem WebSocket não era verificada. | Middleware em memória com janelas por identidade/IP, limite de corpo e verificação Origin em mutações. WebSocket verifica a mesma lista de origens, limita mensagens de controle a 4 KB e sempre remove conexões encerradas. |
| P1 | Cliente WebSocket lento podia atrasar notificações dos demais. | Entrega concorrente com timeout de 500 ms por conexão e remoção de conexões falhas. |
| P2 | Consulta de redistribuição antes do mercado gerava 500; catálogo malformado também podia estourar a rota de início. | Erros claros 409; fallback global de conflitos de domínio mantém envelope de erro consistente. |
| P2 | Contagem de bots considerava um humano sem clube como equipe já assumida. | Contagem usa clubes efetivamente selecionados. |
| P2 | Timers de mercado podiam permanecer ativos após encerrar a aplicação de teste. | Lifespan cancela timers de mercado e rodada pertencentes ao loop atual, preservando testes com clientes/loops isolados. |

## APIs adicionais pequenas

Todas seguem o envelope existente `{ data, meta }`, exigem sessão e verificam participação/clube.

- `GET /api/v1/rooms/mine`: salas em que a identidade já participa; inclui salas privadas e em andamento.
- `GET /api/v1/rooms/{id}/career`: saldo, reserva em transferências, disponível, extrato financeiro, negociações próprias, evolução dos atletas do elenco, temporadas anteriores e elenco atual.
- `PUT /api/v1/rooms/{id}/transfers/listings`: `{ "player_id": "...", "listed": true }`; marca/desmarca atleta próprio na vitrine durante a janela, sem debitar valores.

Os jogadores dos endpoints de elenco, carreira e transferências acrescentam `base_overall`, `overall_delta`, `internal_market_value_cents` e `for_sale`. O campo `overall` desses endpoints representa a carreira atual. `market_value_cents` continua identificando a avaliação original do catálogo; a avaliação de carreira é um cálculo interno do motor, não uma cotação externa inventada.

Anunciar não gera uma venda automática. O motor de negociação existente continua exigindo troca de atletas da mesma posição com complemento financeiro, garantindo a integridade dos dois elencos. Não foi criado um sistema novo de venda irrestrita ou um mercado especulativo.

## Configuração dos limites

- `REQUEST_LIMIT_PER_MINUTE`: 600 por identidade válida (IP para requisições sem identidade).
- `AUTH_LIMIT_PER_MINUTE`: 120 criações de identidade por IP.
- `MAX_REQUEST_BODY_BYTES`: 1048576.

Limites usam memória local e reiniciam com o processo. O reverse proxy de produção ainda deve fornecer limites globais, TLS, tamanho de cabeçalhos e `--ws-max-size` apropriado. Não há confiança automática em X-Forwarded-For enviado pelo cliente.

## Evidências e limites da validação

A execução intermediária desta frente passou em 71 testes backend e Ruff. A frente QA acrescentou testes posteriores de integração; o relatório final da entrega registra a suíte completa após a integração. Foram exercitados os dois modos via API, incluindo mercado, multas, escalação, temporada, playoffs e segunda temporada. Os testes também cobrem origem, token malformado, reservas, listagens e recuperação atômica do snapshot.

Não houve deploy. O catálogo real autorizado continua ausente; a demonstração identifica seus atletas como sintéticos e usa snapshot separado. Uma única instância é obrigatória: não executar múltiplos workers/réplicas. Reiniciar sem snapshots perde o estado. JSON atômico com checksum não equivale a transações de banco; falha de disco durante uma operação pode deixar a memória atualizada sem novo snapshot persistido. Cookies assinados são identidades de convidado, não contas com senha, e trocar APP_SECRET invalida sessões existentes.


Consolidação: a execução final de integração e navegador está registrada em `BETA_DELIVERY_REPORT.md`, que deve ser usada para os resultados finais desta entrega.
