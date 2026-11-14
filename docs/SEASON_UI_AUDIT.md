# Auditoria: temporada e transmissão — beta

## Problemas e correções

| Prioridade | Problema observado no código inicial | Correção aplicada |
|---|---|---|
| Alta | Não havia resumo pós-partida, somente aviso de encerramento | Resumo derivado do replay oficial: placar, autores/minutos dos gols, finalizações do clube, posição, mudança quando acompanhada ao vivo e próximo adversário do calendário real |
| Alta | Mobile exigia percorrer todo o fluxo para chegar a estatísticas/tabela | Botões de navegação Fluxo, Estatísticas e Classificação após o campo; seleção com `aria-pressed`, controles acessíveis e campo sempre disponível |
| Alta | Tabela oficial construída com divs, sem empates/derrotas/escudos | `StandingsTable`: tabela semântica com caption, cabeçalhos, escudos, nomes, pontos, J/V/E/D/GP/GC/SG, clube próprio e marcação da zona G8 |
| Média | Classificação ao vivo não indicava mudança de posição | Setas e rótulos textuais derivados da comparação entre tabela provisória e tabela oficial pré-rodada do servidor |
| Média | Erro ao carregar campeonato/replay resultava em loading sem saída | Estados de erro com mensagem e botão de tentar novamente; estado de reconexão sem apagar dados já obtidos |
| Média | Botão de prontidão não distinguia confirmação concluída | Texto “Você está pronto”, prevenção de repetição e contagem de técnicos humanos da sala |
| Média | Próxima etapa de playoffs exibia nomes internos em inglês | Nomes esportivos em português; chaveamento com escudos, vencedores textuais e pênaltis separados do placar regulamentar |
| Média | Tela de campeão tinha pouca hierarquia e não mostrava técnico | Seção de conquista com clube/escudo/troféu e técnico humano consultado no estado real da sala; sem inventar técnico quando indisponível |
| Média | Premiação de campeão exibida como valor fixo no frontend | Removido valor financeiro fixo; referência ao cálculo do servidor. O painel de carreira integrado trata saldos e histórico reais |
| Média | Cores arbitrárias no canvas e movimento contínuo mesmo com reduced motion | Campo lê tokens do design system central. Preferência por movimento reduzido limita pintura a 4 FPS e evita interpolação da bola |
| Média | Atualização do replay não distinguia temporada para IDs reutilizados | Chave do componente inclui número da temporada para reiniciar corretamente a reprodução |
| Baixa | Pequenos textos e layout antigo com títulos excessivos | Hierarquia mais compacta, alvos de toque ≥44px, cartões consistentes e CSS local com tokens do design system |

## Arquivos

- `frontend/src/features/season/SeasonPage.tsx`
- `frontend/src/features/season/LiveMatchPage.tsx`
- `frontend/src/features/season/MatchReplay.tsx`
- `frontend/src/features/season/StandingsTable.tsx` (novo)
- `frontend/src/features/season/season-beta.css` (novo)

O motor de simulação, seed, duração, autorização do confronto e liberação dos eventos continuam no backend existente. Nenhuma estatística de melhor jogador foi inventada.

## Evidências executadas

- `npm run build --prefix frontend`: aprovado após alterações de temporada.
- `npm run lint --prefix frontend`: aprovado após alterações de temporada.
- Chromium automatizado com backend real de aceitação, três técnicos sintéticos identificados e simulação existente.
- Temporada e transmissão sem overflow horizontal nas resoluções: 375×812, 390×844, 768×1024, 1280×720, 1366×768, 1600×900, 1920×1080.
- Um único canvas por tela na transmissão.
- Botão Estatísticas mostra estatísticas e oculta timeline no mobile; Classificação mostra tabela e oculta estatísticas; Fluxo retorna ao fluxo.
- Nenhum erro de JavaScript na execução automatizada.
- Screenshots: `docs/evidencias/beta-season-desktop.png`, `beta-live-desktop.png`, `beta-live-mobile.png`, `beta-live-mobile-table.png`.

## Limites

- A mudança pós-jogo de posição é mostrada quando a sessão acompanhou a rodada e manteve a tabela oficial anterior. Ao abrir a aplicação somente depois do fim, a posição atual continua disponível, mas não se inventa uma posição anterior.
- Não há cálculo de melhor jogador no motor atual, portanto nenhum MVP é apresentado.
- A tela especial do campeão foi implementada a partir do estado existente e passou pelo typecheck/build. A validação de carreira completa/champion e de todos os demais fluxos pertence à suíte integrada coordenada pelo agente principal.


Consolidação: a execução final de integração e navegador está registrada em `BETA_DELIVERY_REPORT.md`, que deve ser usada para os resultados finais desta entrega.
