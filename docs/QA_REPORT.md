# QA — beta polida

## Escopo e método

Execução nova sobre a cópia completa recebida em `recuperacao-brasileirao.zip`, incluindo a implementação de transmissão ao vivo da entrega anterior. Os resultados anteriores foram usados apenas como referência: a suíte foi executada novamente antes das mudanças.

Os testes HTTP novos usam o router de produção, autenticação real por cookie, validação Pydantic, serviços financeiros reais, motor determinístico e estado em memória isolado. O relógio é controlado nos testes longos de temporada; nenhuma regra financeira ou resultado é substituído por mock. O catálogo de demonstração e os registros de teste são sintéticos e identificados como tais.

## Execuções comprovadas

| Execução | Resultado observado |
| --- | --- |
| Baseline backend anterior às correções desta missão | 62 aprovados, 25,64 s |
| Dois fluxos HTTP completos, 5x5 e 11x11 | 2 aprovados, 39,43 s |
| Regressões de sala, perfil e token | 3 aprovados |
| Regressões financeiras e listagens iniciais | 4 aprovados |
| Segurança HTTP, produção e recuperação atômica | 4 aprovados |
| Primeira execução global ampliada | 75 aprovados, 88,08 s |
| Regressões finais rápidas (incluindo 2 casos adicionais) | 9 aprovados, 2 casos longos desmarcados, 0,92 s |
| Execução global final (77 casos) | 77 aprovados, 67,51 s |
| Ruff dos arquivos de testes | Aprovado |

O aviso observado no pytest é uma depreciação da integração `starlette.testclient` com `httpx`, emitida pela dependência; não representa falha nos testes nem erro da aplicação.

## Fluxo HTTP integral validado nos dois modos

1. Criar identidades, criar sala privada e entrar com segundo técnico pelo código.
2. Selecionar clubes distintos e recusar início por não anfitrião.
3. Iniciar o mercado com catálogo demo isolado.
4. Fazer propostas concorrentes pelo mesmo atleta, manter ofertas do rival secretas e impedir alteração da proposta de outro técnico.
5. Repetir envio idempotente sem gerar nova reserva.
6. Impedir confirmação e review antecipadas.
7. Apurar propostas, obter prévia financeira do backend e verificar que a prévia não debita o saldo.
8. Confirmar seleção com desistência voluntária e multa de 10%, sem dupla cobrança em repetição.
9. Redistribuir o atleta ao técnico da segunda oportunidade; impedir outro clube de aceitar essa oportunidade.
10. Exibir review somente das contratações realizadas e permitir conclusão apenas pelo anfitrião.
11. Obter elencos de 8 e 16 jogadores; salvar 5 e 11 titulares; rejeitar jogador repetido; salvar estratégia.
12. Confirmar que os vinte elencos mantêm exclusividade de atletas.
13. Iniciar 38 rodadas via HTTP, com confirmação de dois técnicos, dez fluxos por rodada e nenhum resultado oficial antes do prazo.
14. Recusar alteração de estratégia durante a transmissão.
15. Abrir a janela após a rodada 19, negociar entre humanos, contrapropor, aceitar, validar mudança de elenco e histórico financeiro privado e encerrar a janela.
16. Executar quartas, semifinais e final, reconhecer campeão real e aplicar evolução.
17. Restaurar o snapshot da temporada concluída e conservar o campeão.
18. Iniciar a segunda temporada, conservando histórico, evolução dos jogadores e eliminando partidas da temporada anterior do calendário ativo.

## Regressões adicionais

- A edição do nome preserva o ID e atualiza o participante na sala.
- `/rooms/mine` recupera sala privada do membro; outro usuário não recebe essa sala.
- Um membro existente pode retornar à sala iniciada; novos técnicos e troca de clube após o início são rejeitados.
- O anfitrião não pode iniciar com participante sem clube, e a tentativa não cria uma sessão de mercado órfã.
- Tokens ausentes, inválidos, Unicode ou assinados com estrutura inválida devolvem 401.
- As reservas de propostas de transferência impedem que compra de agente livre comprometa o mesmo saldo.
- Somente o comprador aceita a contraproposta do vendedor; novas tentativas após a aceitação não debitam novamente.
- Um terceiro clube não pode aceitar a negociação, mesmo após ela ter sido concluída.
- Colocar à venda exige propriedade do atleta, preserva o elenco e sobrevive ao snapshot.
- O encerramento da janela cancela compromissos pendentes e limpa listagens.
- Duas aceitações simultâneas oferecendo o mesmo jogador concluem somente uma troca, com um único débito e atletas exclusivos.
- Origens não autorizadas são bloqueadas em mutações; respostas incluem cabeçalhos de segurança.
- Limites de autenticação e de tamanho do corpo retornam 429/413 antes do handler.
- Produção exige segredo forte, cookie seguro, HTTPS, CORS explícito e recusa o catálogo demo.
- Um erro financeiro na segunda sala de um snapshot não deixa a primeira sala parcialmente restaurada.
- Consultas a telas antes de seus estados existirem retornam conflito 409, sem erro interno 500.

## Bugs encontrados durante a auditoria

| Prioridade | Problema | Evidência e resolução |
| --- | --- | --- |
| Alta | Início permitia participante humano sem clube; tentativa inválida podia criar mercado antes da validação | Guard no domínio e antes de criar a sessão; regressão HTTP valida nenhum efeito parcial. |
| Alta | Sessão podia permitir ingresso tardio e troca de clube depois do início | Regressão HTTP cobre retorno idempotente de membro e rejeição de alteração tardia. |
| Alta | Reserva de transferência podia ser ignorada na compra de agente livre | Teste reserva 700 de saldo 1000 e rejeita compra de 400, sem alterar elenco/saldo. |
| Alta | Vendedor podia aceitar a própria contraproposta | Teste exige aceite do comprador e idempotência financeira. |
| Alta | Recuperação de múltiplas salas podia hidratar estado antes de descobrir corrupção em outra sala | Preflight isolado, com teste de duas salas e estado global vazio após falha. |
| Média | Formação padrão 5x5 não correspondia ao mínimo de posições dos elencos | Adicionada formação 2-1-1 como padrão, preservando as demais. Descoberto no teste de escalação do fluxo HTTP. |
| Média | Consultar redistribuição antes de iniciar mercado gerava erro interno | Reproduzido em teste; handler retorna 409 e há fallback de erro de domínio. |
| Média | Encerramento de janela deixava propostas/listagens ativas | Cobertura confirma cancelamento e liberação de reservas. |

## Arquivos de testes alterados

- `backend/app/tests/test_beta_api_flow.py`: fluxo HTTP integral e regressões de navegação/permissões/sessão.
- `backend/app/tests/test_beta_transfers.py`: finanças, listagens, idempotência e concorrência.
- `backend/app/tests/test_beta_security_recovery.py`: segurança HTTP, configuração de produção e recuperação atômica.
- `backend/app/tests/test_lobby.py`: atualização dos cenários anteriores para exigir escolha de clube por todos os humanos antes de iniciar.

## Reproduzir

Na raiz do projeto, com dependências de `backend/requirements.txt` instaladas:

```sh
python -m pytest backend/app/tests -o addopts='' -q
ruff check backend
```

## Limites desta evidência

Esta seção comprova os testes backend e HTTP. Testes visuais, navegação com navegador, responsividade, acessibilidade e comandos frontend pertencem à execução consolidada da missão e devem ser informados pelo relatório final com seus próprios artefatos. Os relógios controlados dos testes de 38 rodadas não substituem um teste de navegador que espere os 60 segundos reais. Nenhum deploy foi realizado e nenhum catálogo real autorizado foi utilizado.
