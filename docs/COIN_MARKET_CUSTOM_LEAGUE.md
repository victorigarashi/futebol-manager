# Mercado de moedas e campeonato personalizado

Esta branch introduz contratos de backend para salas configuráveis, sem alterar
o motor 2D, o deploy ou a camada de WebSocket em trabalho paralelo.

## Configuração da sala

`POST /api/v1/rooms` aceita os campos adicionais:

- `market_mode`: `TRADITIONAL` (padrão) ou `COINS`.
- `team_count`: `4`, `6`, `8`, `10`, `12`, `16` ou `20`.
- `double_round_robin`: `true` para ida e volta, `false` para turno único.

Uma sala de moedas inicia cada clube com exatamente `100` unidades inteiras.
Os campos legados terminados em `_cents` permanecem nos endpoints para não
quebrar clientes existentes, mas representam moedas quando `market_mode` é
`COINS`. As respostas de mercado incluem `market_mode: "COINS"` e
`currency: "COINS"` para a interface formatar os valores corretamente.

## Mercado secreto

O backend continua sendo a fonte de verdade. Propostas são privadas por clube,
protegidas por lock da sala e por chave de idempotência. Em moedas:

- não há preço-base nem floats;
- saldo reservado é atualizado apenas pela diferença ao editar uma proposta;
- cancelar libera toda a reserva;
- a ordem de resolução é maior oferta, depois a primeira sequência registrada;
- derrotados liberam a reserva; o vencedor só paga sua oferta confirmada;
- prêmios monetários de temporada não são aplicados a ligas de moedas.

`POST /rooms/{id}/market/offers`, `PUT` e `DELETE` das ofertas existentes são
reutilizados; eles nunca retornam propostas dos adversários.

## Bots

Antes do início, apenas o anfitrião pode usar:

- `POST /api/v1/rooms/{room_id}/bots` (`{"club_code":"FLA"}` é opcional);
- `DELETE /api/v1/rooms/{room_id}/bots/{club_code}`.

Bots ocupam exclusivamente um clube livre, usam o mesmo saldo e fazem lances
determinísticos e conservadores no mercado inicial. A confirmação automática e
a montagem de escalação seguem o mesmo fluxo já usado pelos bots existentes.

## Calendário

O método de círculo agora aceita todas as quantidades pares suportadas. Cada
clube joga uma vez por rodada. No turno único há `n - 1` rodadas; na ida e
volta há `2 * (n - 1)`, com mando invertido no segundo turno. Para 4 ou 6
clubes a temporada termina na tabela, pois não existe chave de oito clubes.

## Integração de interface pendente

Esta branch deliberadamente não altera os componentes React em refatoração
paralela. A tela de criação deve enviar os três campos acima, exibir
`participant_count`, `bot_count`, `available_slots`, e usar os endpoints de
bots. Em moeda, deve rotular todos os valores como moedas e não como reais.

## Correções de integração (15/11/2026)

Encontradas com um teste ponta a ponta via HTTP (liga de 4 clubes em moedas e de 8 clubes tradicional; bots, mercado, temporada e reinício):

- **Reinício do servidor.**
  - `restore_room` exigia 20 clubes, 380 jogos, 38 rodadas e 10 partidas por rodada.
  - `recovery.py` exigia o mercado com os 20 clubes.
  - Com qualquer liga personalizada salva, o snapshot era recusado no boot e **a API não subia**.
  - Agora a validação usa a quantidade de clubes do calendário (4 a 20) e o formato salvo.
- **Formato perdido.**
  - `SeasonService.create` não guardava `double_round_robin` (ficava `True`), então a temporada seguinte virava ida e volta.
  - O formato também não ia para o snapshot. Agora é guardado e exportado.
- **Bots ocupando vaga de humano.** `join` contava os bots no limite de humanos: com os bots adicionados primeiro, os amigos recebiam "sala cheia". Agora só pessoas contam nesse limite, e o total fica limitado ao número de clubes.
- **Rotas que contavam bots como humanos.**
  - O READY, o prazo e o pré-jogo esperavam confirmação dos bots participantes.
  - O resultado era a rodada presa em "aguardando confirmação".
  - Agora os participantes com papel `BOT` são excluídos.
- **Interface.**
  - Não havia como adicionar bots, então ligas com menos de 20 clubes não conseguiam começar.
  - O lobby ganhou o painel **Vagas do campeonato**, com técnicos, bots, vagas livres e clubes, e os botões "+ Adicionar bot", "Completar com bots" e "Remover".
  - O botão de início explica quantas vagas faltam.
