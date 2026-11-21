# Quality gate — Football Realism V6 (avaliação interna)

As notas não foram dadas: dependem do playtest do proprietário. Aqui ficam só fatos verificáveis.

| Critério | Situação | Evidência |
|---|---|---|
| Personagens 3D não são mais quadrados | Atendido | Capturas `atleta-*` (frente, costas, lado, perto, corrida, chute, mergulho) e `3d-*` |
| Proporções humanas e escala de 1,82 m | Atendido | Teste `human.test.ts` (altura entre 1,72 e 1,92 m) |
| Esqueleto e pesos | Atendido | Teste: 13 ossos com pesos normalizados |
| Orçamento de triângulos por qualidade | Atendido | Teste (medido): baixa 2.975, média 4.838, alta 6.386 triângulos por atleta |
| Animações específicas de goleiro | Parcial | Mergulho, encaixe, prontidão e espalmada procedurais. Falta defesa baixa específica e reposição |
| Escorregamento dos pés | Mitigado | Ciclo de passada integrado a partir do deslocamento oficial (1,3 m + 0,13·v por ciclo). Sem bloqueio de pé por IK |
| Seta gigante e cone | Removidos | Capturas `*-02-mira-passe`, `*-11-cruzamento-mira` |
| Marcador antigo depois do fim do lance e mensagem duplicada | Corrigidos | O nome e o anel só aparecem com decisão aberta; os controles ficam inativos fora da sua vez; o fim do lance tem uma única mensagem |
| Personagens 2D menos infantis | Atendido | Capturas `2d-*` |
| Mesma física no 2D e no 3D | Atendido | Uma única `view` do servidor; teste de gesto equivalente |
| Multiplayer com 2D e 3D ao mesmo tempo (dois navegadores) | **Não executado** | — |
| FPS em hardware real | **Não medido** | As capturas usam SwiftShader (renderização por software) |

# Quality gate — Football Engine V7 (21/11/2026)

O relatório completo está em `docs/v7/RELATORIO_FINAL.md`, com notas internas, evidências e pendências.

**Situação: não aprovado internamente para as competições.** A meta de 8 não foi atingida em todas as áreas, e a diversão depende do playtest do proprietário. O Lab já usa a V7.

| Critério | Situação | Evidência |
|---|---|---|
| Fim das paradas e arrancadas instantâneas | Atendido | `instant_start`: 20,2 → 0,1 por mil |
| Acelerações compatíveis com atletas | Muito melhor, não zerado | Acima de 10 m/s²: 264,6 → 66,9 por mil |
| Bola nunca colada nem teleportada | Atendido | Teste de quadros (bola abaixo de 40 m/s entre quadros); condução por toques |
| Goleiro nunca defende o impossível | Atendido | 0 em 120 chutes fora do alcance |
| Mergulho com deslocamento real | Atendido | `test_keeper_dive_is_a_real_displacement` |
| 2D e 3D com o mesmo resultado | Atendido | Um motor; dois navegadores sem divergência |
| Competições terminam com a V7 | Atendido | `test_football_v7_competitions.py` |
| Sprites 2D e modelos 3D novos | **Não feito** | Ver RELATORIO_FINAL §7 |
| Feedback humano | **Pendente** | — |
