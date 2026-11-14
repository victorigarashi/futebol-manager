# Auditoria de mercado, elenco e transferências

Escopo: `frontend/src/features/market`, `frontend/src/features/squad`, `frontend/src/features/season/TransferHub.tsx`.

## Problemas e correções implementadas

| Prioridade | Problema encontrado | Correção |
| --- | --- | --- |
| Alta | Catálogo de 400 atletas gerava centenas de cards e uma página mobile excessivamente longa. | Paginação local de 24 atletas por página, contagem e navegação acessível; alteração de filtro retorna logicamente à primeira página sem efeito adicional. Cache de nomes continua incluindo os resultados completos. |
| Alta | Campo de proposta inicial recebia centavos sem informar unidade. | Entrada explicitamente em reais, conversão única para centavos e valor mínimo visível; validação autoritativa continua no backend. |
| Alta | Endpoint de alteração de proposta existia sem ação na interface. | Botão **Alterar valor**, edição da reserva existente e envio pelo PUT real. |
| Alta | Identificador idempotente era regenerado a cada tentativa. | Chaves mantidas durante uma tentativa e renovadas após sucesso em proposta e transferência. |
| Média | Nome de oferta desaparecia ao filtrar atletas. | Cache local de jogadores já recebidos e recuperação individual pela API quando necessário. |
| Alta | Cancelamentos, falhas de busca e algumas falhas de consulta não tinham feedback. | Estados de erro com `role=alert`, retorno de sucesso com `role=status`, repetição de consulta quando aplicável e bloqueio durante comandos. |
| Alta | Modal de oferta não controlava foco, Escape ou retorno ao acionador. | Uso do Modal compartilhado acessível, com título associado, foco contido e fechamento seguro. |
| Alta | Tela de seleção iniciava sem marcações, podendo levar à recusa involuntária de compromissadas e multas. | Contratações compromissadas pré-selecionadas. Toda desistência fica explícita com prévia do servidor. |
| Alta | Confirmação podia usar uma prévia ainda em atualização. | Confirmação bloqueada enquanto busca/erro de prévia; revisão final exibe compra, multas e saldo; nenhum débito no cliente. |
| Média | Review sem entradas podia produzir índice negativo; resumo era exibido desde o começo. | Controles limitados, reprodução termina no resumo, pular/rever funcionais e estados vazios explícitos. |
| Média | Review não destacava comprador ou técnico. | Escudo do comprador, identidade do técnico, OVR, posição, origem, destino e valor real da contratação. Nenhuma oferta perdedora exibida. |
| Alta | Escalação era editável apenas por controles pequenos dentro do campo. | Campo visual preservado e lista de titulares com selects acessíveis, utilizáveis por teclado/toque. Selecionar outro titular troca suas vagas sem duplicidade. |
| Média | Titulares/reservas e avaliação de improvisação não eram claros. | Banco de reservas separado, elenco completo com status e OVR efetivo calculado pelo servidor após salvar. Alteração não salva é sinalizada. |
| Alta | Selecionar outro alvo na transferência podia manter atleta de saída incompatível e enviar IDs incorretos. | Cada ID de saída é derivado de opções válidas da posição atual; seleção antiga inválida não é enviada. |
| Alta | Uma contraproposta digitada era compartilhada entre todas as ofertas. | Valor de contraproposta associado ao ID da negociação. |
| Alta | Compra de atleta livre liberava substituído sem revisão clara. | Modal confirma nomes, preço e saída sem receita; intenção congelada enquanto o modal está aberto, mesmo se outras consultas atualizarem. |
| Média | Transferências não tinham busca nem anúncio de disponibilidade. | Busca nome/posição, anúncio/remoção usando endpoint real e indicação de atletas à venda. |
| Média | Valores atuais após evolução não apareciam. | Apresentação de `internal_market_value_cents`, OVR atual e delta quando informados pelo servidor. |
| Média | Queries com erro podiam exibir carregamento indefinidamente. | Diferenciação entre carga inicial, falha, ausência de resultado e atualização. |
| Média | MarketPage/MarketProgressPage criavam landmarks `<main>` aninhados no lobby. | Wrappers internos convertidos para `<section>`. |

## Contratos integrados

- PUT de alteração de proposta inicial já existente.
- GET de jogador individual já existente.
- `GET /rooms/{room_id}/career`, somente dados do clube autenticado.
- `PUT /rooms/{room_id}/transfers/listings`, anuncio de disponibilidade sem executar venda.
- `for_sale`, OVR atual e valor interno do atleta vindos do backend.
- Compra/troca permanece condicionada ao backend: posição preservada, saldo, propriedade e validação da escalação.

## Validação

- TypeScript/Vite build executado após integração dos contratos: aprovado.
- ESLint executado após alteração dos quatro fluxos: aprovado.
- A auditoria visual e os cenários automatizados de navegador são consolidados pela execução QA principal em `FINAL_UI_AUDIT.md` / relatório final. Este documento não afirma aprovação de navegador por inspeção de código.

## Limites preservados

- Fotos de atletas não foram inventadas nem obtidas por scraping. Sem foto autorizada, há monograma visual; os escudos usam o recurso local existente.
- Não existe venda avulsa que esvazie posições: anunciar só sinaliza disponibilidade e as operações concretas são trocas/substituições validadas.
- Não foi introduzido motor financeiro no frontend. Aritmética de entrada serve apenas à unidade monetária; reservas, prévias, débitos e saldos confirmados vêm do backend.
- Prioridade exibida significa ordem de envio das propostas, sem fingir controle de ordenação que não existe na API.


Consolidação: a execução final de integração e navegador está registrada em `BETA_DELIVERY_REPORT.md`, que deve ser usada para os resultados finais desta entrega.
