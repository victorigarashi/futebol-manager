# Integração PES 2013 Web — estado

**Legenda:**

- **CONFIRMADO**: há teste ou execução no repositório;
- **HIPÓTESE**: vem apenas da descrição do pacote, sem verificação;
- **BLOQUEADO**: falta um artefato ou uma decisão;
- **NÃO INICIADO**: ainda não foi trabalhado.

## Fase 1 — contrato e adaptador (concluída)

| Requisito | Estado | Evidência | Bloqueio | Próximo experimento |
|---|---|---|---|---|
| `MatchPayload` versionado (v1) a partir do snapshot congelado | CONFIRMADO | `domain/match_contract.py`; `test_payload_from_the_frozen_round_respects_the_mode` | — | — |
| 5×5 e 11×11: quantidade de titulares e posições pela formação, um goleiro | CONFIRMADO | mesmo teste, parametrizado nos dois modos | — | — |
| Mandante e visitante corretos | CONFIRMADO | comparação com `frozen_match` no mesmo teste | — | — |
| Jogador comprado joga pelo clube atual | CONFIRMADO | `test_bought_player_plays_for_his_current_club...` | — | — |
| Nomes preservados; nenhum atributo inventado (`OVERALL_ONLY` quando o catálogo não tem) | CONFIRMADO | mesmo teste | — | Decidir com você a regra para os 206 jogadores sem atributos. |
| Rejeitar escalação incompleta, jogador duplicado, formação inválida, dois goleiros, clube contra si mesmo, modo desconhecido, atributo desconhecido e partida inexistente | CONFIRMADO | `test_contract_rejects_invalid_fixtures` | — | — |
| Snapshot estável depois que o mercado muda | CONFIRMADO | `test_snapshot_is_stable_after_the_market_changes` (mesmo checksum) | — | — |
| Checksum: contrato adulterado é recusado | CONFIRMADO | `test_tampered_payload_is_refused_by_the_adapter` | — | — |
| Partida encerrada não pode ser preparada de novo | CONFIRMADO | `test_finished_match_cannot_be_prepared_again` | — | — |
| Flag desligada não muda a engine atual | CONFIRMADO | `test_flag_off_changes_nothing...` (resultados idênticos) e a suíte completa | — | — |
| PES inalcançável com a flag desligada; com ela ligada, recusa toda operação | CONFIRMADO | `test_pes2013_is_unreachable...`, `test_engines_endpoint_lists_pes2013_as_disabled` | — | — |
| Jogadores personalizados convivendo com reais | BLOQUEADO | o projeto não tem jogadores criados pelo usuário | Funcionalidade de produto inexistente | Definir se ela entra no produto. |

## Fase 2 — preparação (concluída; diagnóstico em `01-fase2-diagnostico.md`)

| Requisito | Estado | Evidência | Bloqueio | Próximo experimento |
|---|---|---|---|---|
| `PESRuntimeBridge` desacoplada | CONFIRMADO (interface e implementação "indisponível") | `frontend/src/features/external-engines/pes/bridge.ts`; `bridge.test.ts` | — | Implementação real com iframe depois do E1 |
| Isolamento do runtime (outra origem, só máquina local, mensagens validadas) | CONFIRMADO (regras) | `protocol.ts`; testes de origem e de mensagens | — | E1 |
| Inventário estático dos arquivos do runtime | CONFIRMADO em arquivos sintéticos | `backend/tools/pes_runtime_inventory.py`; `test_pes_runtime_inventory.py` | Falta rodar nos arquivos reais | Itens 1–4 da lista de arquivos |
| Plano de testes Corinthians × São Paulo | PRONTO | `01-fase2-diagnostico.md`, seção 5 | B9 (personalizados) bloqueado pelo produto | — |

## Fases 2 a 5 — runtime PES

| Requisito | Estado | Evidência | Bloqueio | Próximo experimento |
|---|---|---|---|---|
| Como o PES Web monta o sistema de arquivos e carrega elencos | BLOQUEADO | nenhum artefato no workspace | Falta o `manifest.json` e o worker, legitimamente fornecidos | Ler o manifest e listar os arquivos montados e os pontos de leitura. |
| `EDIT.bin` lido pelo port Web | HIPÓTESE | — | Idem; formato desconhecido | Só depois de comprovar a leitura: documentar offsets e checksum, e fazer um round-trip com uma fixture autorizada. |
| `RosterExporter` / `PlayerStatMapper` | NÃO INICIADO | — | Depende do formato real; não se escreve um binário com base em suposições | Tabela de conversão documentada e testes de limites. |
| `can_load_custom_roster` | `False` | `Pes2013Adapter.capabilities` | Idem | — |
| `can_select_teams` / `can_auto_start_match` | `False` | — | Nenhuma API conhecida de seleção ou início | Procurar uma configuração ou estado inicial no runtime; clicar automaticamente na interface não vale como solução definitiva. |
| `can_read_result` | `False` | — | Nenhuma forma conhecida de ler o placar com confiabilidade | Procurar um resultado exposto pelo runtime. Sem isso não há integração com o campeonato. |
| `can_netplay` | `False` | — | O relay observado só aceita localhost; nenhuma partida real entre dois PCs | Primeiro um teste local com tráfego observável; depois dois PCs autorizados. Transportar pacotes não é sincronizar uma partida. |
| `supports_5v5` | `False` | — | O PES 2013 não tem 5×5 até prova em contrário | — |
| `supports_11v11` | `False` | — | Nada validado ainda | — |
| `MatchLaunchService` (CREATED → PREPARING → READY → RUNNING → FINISHED/FAILED) | NÃO INICIADO | — | Sem capacidade real, uma máquina de estados seria fachada | Implementar quando houver pelo menos `can_auto_start_match`. |
| Resultado idempotente e atômico no motor atual | CONFIRMADO | `finish_due` grava uma vez por rodada; ações com `action_id` idempotente | — | — |
| Resultado vindo dos clientes (engine que roda no navegador), Fase 5 | CONFIRMADO como regra; **não ligado à tabela** | `domain/external_results.py`; `test_external_results.py` (5 testes) | Nenhuma engine externa produz resultado ainda | Ligar `take_confirmed` ao commit da rodada quando existir `can_read_result`. |

## Livro de resultados externos (Fase 5, independente da engine)

A engine atual é autoritativa: o servidor calcula o placar. Uma engine que roda no navegador dos técnicos, como o PES Web, só chegaria ao servidor pelos clientes. A regra implementada é esta:

- o relato informa a partida **e o checksum do contrato** com que ela foi jogada; um relato de outro contrato é recusado;
- só os dois clubes da partida podem relatar, cada um por si;
- o resultado fica **CONFIRMADO** só quando os dois relatam o mesmo placar. Até lá fica PENDENTE;
- placares diferentes deixam a partida **DISPUTADA**, e nada é gravado;
- um relato repetido não muda nada;
- um resultado confirmado nunca muda e é entregue à temporada **uma única vez**;
- toda tentativa, aceita ou recusada, fica na auditoria.

**Limite, dito com clareza:** dois técnicos combinados conseguem confirmar um placar falso. A concordância prova coerência entre os dois clientes, não a verdade da partida. Só uma engine cujo resultado o servidor consiga verificar ou calcular remove esse limite.

## Interface

O painel "Experiência de partida" (Lab, menu, lobby e configurações) mostra um aviso abaixo das opções 2D e 3D: "PES 2013 Web — Experimental · indisponível", com o texto "As partidas continuam na engine atual".

- O aviso **só aparece com a flag ligada**. Com ela desligada, como em produção, nada muda na tela.
- Não é uma opção selecionável.
- O aviso vem de `GET /api/v1/match-engines`.
- Capturas: `frontend/scripts/capture-engine-notice.cjs`, rodado contra um servidor com a flag ligada e outro com ela desligada.
