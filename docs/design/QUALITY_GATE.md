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
