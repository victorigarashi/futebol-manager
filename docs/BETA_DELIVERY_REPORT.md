# Relatório final — beta polida

Entrega executada sobre o projeto existente. React/TypeScript/Vite, FastAPI/Pydantic, WebSockets, estado em memória e snapshots JSON foram preservados. Nenhum deploy, banco ou serviço pago foi adicionado.

## 1. Telas melhoradas

- Home e onboarding: identidade esportiva, títulos moderados, ações principais visíveis, perfil editável e retorno às próprias ligas.
- Lobby e escolha de clube: escudos locais, técnicos/host, bots, regras, código/cópia, status de conexão, etapas e confirmação acessível no celular.
- Mercado: cards com hierarquia, posição/OVR/potencial/valor, orçamento e reservas, propostas editáveis, erros explícitos e 24 atletas por página.
- Escolha das contratações: compromissadas preservadas por padrão, vagas, multas, saldo e genéricos na prévia do servidor; confirmação explícita.
- Review: contratação individual, comprador/técnico/escudo, autoplay, próxima/pular/rever/resumo e estado sem compras.
- Elenco 5x5/11x11: campo tático, titulares, banco, troca sem drag, OVR efetivo e estratégia validada.
- Transmissão: um campo por técnico, placar/escudos/relógio, pressão, fluxo, cartões/estatísticas, abas mobile e tabela com variação real de posição.
- Pós-jogo: último confronto próprio, gols/estatísticas, próximo adversário, classificação e replays.
- Transferências: busca, avaliação atual, anúncios, propostas/contrapropostas e confirmação estável de compra/saída.
- Playoffs/carreira: chaveamento e pênaltis, campeão/técnico humano ou bot, temporadas anteriores, premiações, extrato e evolução do próprio clube.

## 2. Fluxos corrigidos

Identidade deixa de ser substituída em erro de rede; armazenamento local bloqueado não derruba o jogo. Salas privadas/iniciadas podem ser retomadas pelo servidor. Reconexão recupera estado sem reiniciar tempo. Descoberta pública atualiza sem reload. Troca de clube não abandona a sala. Erros de salvar/cancelar/negociar têm feedback.

Ofertas continuam secretas. A confirmação financeira usa a prévia autoritativa, sem cálculo de regras no frontend. Operações preservam idempotência, reservas e integridade de elenco. Snapshots passam por validação completa antes de ativar o estado.

## 3. Bugs encontrados e 4. resolvidos

A matriz completa, prioridade/correção/evidência, está em [FINAL_UI_AUDIT.md](FINAL_UI_AUDIT.md), com detalhes por frente em BACKEND_AUDIT.md, MARKET_SQUAD_AUDIT.md e SEASON_UI_AUDIT.md.

Destaques: recriação indevida de sessão; comandos/permissões depois do início; gasto de valores reservados; vendedor aceitando a própria contraproposta; disputa concorrente por atleta; propostas antigas em outra janela; IDs inválidos após filtros; confirmação com prévia antiga; índice inválido da review; formação 5x5 incoerente; token malformado gerando 500; restauração parcial de snapshot; resumo de playoffs preso na rodada regular. Foram adicionadas regressões automatizadas para as falhas backend reproduzidas.

A inspeção visual também identificou a célula RBB da prancha original com escudo de outro clube. Ela foi substituída por uma identidade provisória explícita, sem obter recurso externo não autorizado.

## 5. Testes executados nesta entrega

| Verificação | Resultado e alcance |
|---|---|
| Baseline backend reexecutado | 62 passaram antes da ampliação |
| Backend final | **77 passaram**, 67,51 s; um warning de depreciação Starlette/httpx, sem falha |
| Frontend final | **6 passaram**, Vitest 5.1; storage, relógio/replay/pressão e URL WS |
| Ruff / ESLint / TypeScript | Aprovados |
| Build Vite | Aprovado; 107 módulos, bundle JS ~303,70 kB / ~91,59 kB gzip |
| Npm audit final | **0 alertas**, incluindo desenvolvimento, na consulta executada |
| API de carreira completa | Dois humanos, ambos modos, mercado/multas, redistribuição/review, escalação, 38 rodadas, transferências, playoffs, temporada 2 e snapshot |
| Chromium por telas | **13 telas × 7 viewports**, sem overflow horizontal ou erro JS; 9 ações/checagens reais de integração |
| Axe por telas | **26 análises** (390/1366 px), 0 violações nas regras WCAG 2A/AA e 2.1AA executadas |
| Onboarding | Sete viewports, edição/reload preservando o ID, modal; axe sem violações |
| Home em falha | Endpoint 503 com retry; nova sala pública aparece sem recarregar |
| Seleção e configurações | Sete viewports para grade e modal; confirmação mobile e Escape |
| Transmissão real | Três sessões, mesma partida para dois adversários e outra para o terceiro; reconexão/reload; dez resultados oficiais após prazo; sem erro JS |

A transmissão final foi observada em **61,28 s desde o primeiro clique**, incluindo a espera até o último técnico confirmar e a resposta da interface. O prazo compartilhado do servidor é de **60 s a partir do início comum**. Reconexão retomou aproximadamente no minuto 24, mantendo o mesmo deadline.

O ciclo de 38 rodadas usa relógio controlado no teste HTTP; não se afirma que todas as 38 transmissões foram assistidas no navegador. O navegador efetivamente executou a partida de prazo real e as telas/ações acima. Não houve teste público de carga nem teste físico em aparelhos.

## 6. Screenshots e evidências

Em [evidencias/beta](evidencias/beta): telas mobile e desktop, resultados JSON dos scripts, axe, transmissão, onboarding, recuperação e audit de dependências.

Exemplos: [home](evidencias/beta/home-1366.png), [mercado mobile](evidencias/beta/market-390.png), [elenco mobile](evidencias/beta/squad5-390.png), [campeão/playoffs](evidencias/beta/champion-1366.png), [ao vivo mobile](evidencias/beta/live-mobile.png).

Os estados de screenshot são dados sintéticos produzidos pelos motores reais em servidor de aceitação separado. A interface principal continua consumindo APIs reais; nenhum handler de produção salta fases para facilitar screenshots.

## 7. Arquivos alterados

Lista gerada comparando o ZIP da transmissão anterior: [CHANGED_FILES.md](CHANGED_FILES.md). Principais grupos: páginas React e componentes comuns; tokens/CSS; cliente API/sessão/storage; serviços/rotas/segurança/recuperação backend; testes de integração; scripts e fixtures de navegador; configuração de desenvolvimento e documentação.

## 8. Pendências

- Catálogo real autorizado, fotos licenciadas e escudo correto autorizado do Bragantino.
- Validação humana com leitor de tela, aparelhos físicos e amigos na infraestrutura escolhida.
- Medição de carga/latência pública, operação de backups e validação do proxy/HTTPS reais antes de um deploy.
- A folha CSS legada foi preservada e recebeu uma camada centralizada de tokens/estilos; uma limpeza estrutural futura pode reduzir o CSS sem mudar o produto.
- Nenhum MVP foi inventado, pois o motor não o calcula. Posição pós-jogo só mostra variação se houver baseline real observado; não inventa dados após reload.

## 9. Limitações preservadas

Uma instância e um worker; estado em memória; reinício sem snapshot perde salas; JSON não equivale a transações de banco. Identidade de convidado depende do cookie assinado, não de conta/senha recuperável. Anúncios de venda sinalizam disponibilidade; negociações continuam trocas equivalentes com compensação financeira para preservar o elenco. Não foi criado um sistema novo de venda irrestrita.

Axe não é certificação completa de acessibilidade. As evidências locais não comprovam operação de infraestrutura pública. Nenhum deploy foi feito.

## 10. Executar

```sh
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build
```

Abra `http://localhost:5174`. Para execução sem Docker, configuração entre dispositivos, testes e persistência, siga [RUNNING.md](RUNNING.md), [TESTING.md](TESTING.md) e [DEMO.md](DEMO.md). O guia de produção prepara um futuro deploy, sem executá-lo.

ZIP: `brasileirao-manager-beta-polida.zip`, com fonte, testes e evidências, sem node_modules, .venv, segredos ou arquivos de estado temporário. A integridade do arquivo é verificada antes da entrega.
