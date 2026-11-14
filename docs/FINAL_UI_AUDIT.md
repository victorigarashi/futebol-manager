# Auditoria final da beta — Brasileirão Manager, Edição Resenha

Auditoria executada sobre o projeto completo recuperado e a implementação real de transmissão de 60 segundos. Nenhum sistema foi substituído por mock e nenhum banco foi adicionado. As fábricas de estado em `backend/tools` são entradas explícitas de teste, não rotas da aplicação de produção.

Prioridades: P0 compromete identidade, integridade ou sigilo; P1 bloqueia fluxo ou uso acessível; P2 reduz clareza, consistência ou acabamento.

| Área / prioridade | Problema observado no código ou reproduzido | Correção aplicada | Evidência |
|---|---|---|---|
| Sessão / P0 | Qualquer erro de `/me` criava outro convidado, inclusive falha de rede | Criar identidade somente em 401; deduplicar consulta e oferecer retry | Browser injeta 503 e verifica ausência de POST guest |
| Persistência local / P1 | `localStorage` sem proteção podia derrubar toda a aplicação | Adaptador tolerante a bloqueio/quota; cookie e `/rooms/mine` preservam vínculo | Teste unitário e browser com armazenamento bloqueado |
| Retomada / P1 | Só o ID local permitia voltar a salas privadas/iniciadas | Lista de ligas do próprio usuário no servidor e recuperação ao recarregar | API + navegação Chromium |
| Conexão / P1 | Socket reiniciado ao atualizar objeto da sala; parse sem proteção; sem recuperação ao voltar da suspensão | Dependência do ID, backoff, refresh em open/online/visibility, polling de recuperação | Reconexão e reload no browser; teste WS |
| Navegação / P1 | Links de home levavam a âncoras inexistentes dentro da temporada; “trocar clube” saía da sala | Cabeçalho contextual, toolbar com código/etapa/conexão, ação de troca preservando sala | Browser lobby e navegação |
| Seleção de clube / P1 | No celular a confirmação ficava depois de 20 cards; painel vazio fixo podia cobrir cards no desktop | Confirmação em modal com escudo e ação explícita | Browser de seleção e foco |
| Lobby / P1 | Entrada/troca de clube após início podia alterar clube associado a elenco | Bloquear novos membros/troca após início, permitir reentrada de membro | Regressões HTTP |
| Início / P0 | Podia criar mercado e timer antes de validar técnicos sem clube | Validar estado antes de criar mercado; exigir clubes de todos | Regressões API |
| Lobby / P2 | Faltavam bots, prazos e contexto da fase em todas as telas | Resumo de regras, contagem real, convite e progresso de etapas | Screenshots e API |
| Convite / P1 | Erro do clipboard era promessa rejeitada sem feedback | Mensagem acessível e seleção manual do código como alternativa | Browser e revisão de handlers |
| Modais / P1 | Faltavam trap, Escape, retorno de foco e limite de altura | Modal compartilhado; bloqueio durante gravações; scroll interno | Teclado e axe |
| Tipografia / P2 | Títulos enormes, fontes e cores inconsistentes, fontes minúsculas | Tokens de design centralizados, títulos moderados, corpo legível, hierarquia esportiva | Sete viewports + screenshots |
| Estados / P1 | Falhas de busca/salvar/cancelar silenciosas e telas sem saída | Mensagens, retry, loading/skeleton, limite de renderização de erro | Testes de erro e navegação |
| Mercado / P0 | Campo financeiro em centavos sem indicação clara | Reais na interface, conversão inteira para centavos; servidor autoritativo | Edição via UI e inspeção API |
| Mercado / P1 | Não era possível editar oferta na tela embora API existisse | Editar e atualizar reserva; idempotência estável em tentativas | Browser e testes financeiros |
| Mercado / P2 | Nomes das ofertas desapareciam após filtros; lista longa de centenas de cards | Recuperar atleta individual e manter nomes; paginação de catálogo | Browser e revisão de fluxo |
| Confirmação / P0 | Seleção inicial vazia podia induzir multa involuntária | Compromissadas selecionadas por padrão; prévia do servidor e confirmação de saldo/multas | Fluxo HTTP 5x5/11x11 + browser |
| Confirmação / P1 | Prévia antiga podia permanecer disponível durante atualização | Bloquear confirmação durante fetch/erro e apresentar diálogo explícito | Integração API e UI |
| Review / P1 | Sem compras, “próxima” podia produzir índice negativo; autoplay não encerrava corretamente | Estado vazio, resumo final, pular, rever e reprodução até resumo | API review + browser |
| Review / P2 | Contratações sem destaque de clube/técnico/OVR | Apresentação com escudo existente e somente compras confirmadas | Screenshot review |
| Elenco / P1 | Titulares/reservas e impacto de improvisação pouco claros | Banco separado, lista acessível sem drag, OVR efetivo e formação real | UI salvar escalação + API |
| Formação / P1 | Padrão 5x5 divergente de 2 DF + 1 MF do elenco | Padrão `2-1-1` e validação preservada das demais formações | Testes 5x5 |
| Ao vivo / P1 | Faltavam navegação mobile e contexto de variação de posição | Abas Fluxo/Estatísticas/Classificação; tabela semântica completa e baseline oficial | Browser com um canvas, sete viewports |
| Ao vivo / P0 | Comandos táticos podiam ser alterados durante transmissão | Congelar comandos pelo servidor durante live | Regressões API |
| Pós-jogo / P2 | Sem resumo dedicado, próximo adversário ou resultado esportivo claro | Resumo dos gols e estatísticas reais; próximo adversário, tabela e replays próprios | API + screenshot pós-jogo |
| Classificação / P1 | Divs sem cabeçalhos semânticos e ausência de E/D/escudos | Tabela acessível completa com G8 e deslocamento de posição | Axe e sete viewports |
| Playoffs / P2 | Campeão e vencedor sem acabamento/contexto | Chaveamento com escudos, pênaltis, campeão e técnico real quando humano | 38 rodadas e playoffs via API; screenshot campeão |
| Transferências / P0 | Valores reservados podiam ser gastos em compra livre | Reserva validada em todas as operações | Regressões financeiras |
| Transferências / P0 | Vendedor podia aceitar a própria contraproposta | Aceitação validada pelo lado correto | Teste de permissão |
| Transferências / P0 | IDs escolhidos podiam ficar incompatíveis após mudar filtros/atletas | Seleção derivada de opções válidas; intenção de compra congelada no diálogo | UI + regressões API |
| Transferências / P1 | Propostas pendentes atravessavam fechamento da janela | Expirar/cancelar pendências e anúncios no encerramento | Teste de janela e snapshot |
| Transferências / P2 | Faltava anúncio e avaliação atual de carreira | Listing de disponibilidade, valores internos reais e evolução | API + UI |
| Carreira / P2 | Saldos e evolução não tinham histórico consultável do próprio clube | Extrato e negociações próprias, elenco e evolução em painel sob demanda | API career + browser |
| Produção / P0 | Segredo padrão e cookies inseguros podiam iniciar como produção | Validar segredo, HTTPS, Secure e CORS na configuração de produção | Testes de Settings |
| Endpoints / P1 | Token Unicode e consulta pré-fase podiam retornar 500 | Validação robusta e conflitos de domínio 409 | Regressões reproduzidas |
| Recuperação / P0 | Snapshot inválido podia restaurar parte do estado antes de falhar | Preflight de todos os estados, calendário completo e ativação posterior | Teste sem contaminação parcial |
| Proteção / P1 | Sem limites HTTP/WS e validação de Origin | Limites locais configuráveis, corpo limitado, Origin e limpeza de WS | Testes HTTP e WS |

## Achados da inspeção de evidências

A revisão dos screenshots identificou um escudo de outro clube na célula RBB da prancha originalmente fornecida. O componente agora usa fallback explícito para Bragantino, sem baixar marca externa nem apresentar o recurso errado como oficial. A inspeção também levou à correção do resumo pós-playoff: ele consulta o último confronto próprio, em vez de permanecer no último jogo da temporada regular.

A lista pública de ligas agora se atualiza a cada cinco segundos na home e apresenta erro com retry, sem manter polling de descoberta durante a partida. Falhas de atualização da sala também aparecem na interface, preservando a associação existente.

## Limites explícitos

- A existência de um botão/handler não é prova de fluxo validado. O relatório de testes separa API, navegador e revisão estática.
- Não há MVP calculado pelo motor: a interface não inventa um melhor jogador.
- Vendas são anúncios e trocas de posição equivalente com compensação financeira; uma venda irrestrita não foi criada porque quebraria a regra atual de integridade do elenco.
- Movimentos de posição pós-jogo exigem baseline observado na sessão; após recarregar, a interface não inventa posição anterior. Na transmissão, a comparação usa a classificação oficial recebida.
- Fotos de atletas licenciados e catálogo real autorizado seguem ausentes. Fallback visual usa silhueta/iniciais/posição e dados sintéticos identificados em demo, sem falsa fotografia.
- Não houve deploy nem teste de carga com usuários reais. Cookies de convidado não são contas com recuperação de senha.
- Estado em memória e JSON continuam exigindo uma instância; os testes automatizados não eliminam riscos de disco/rede/infraestrutura de um deploy futuro.
