# AGENTS.md — Brasileirão Manager

Orientação para qualquer agente (humano ou IA) que trabalhe neste repositório.

## Antes de mudar o Modo Jogável

- Leia:
  - `docs/MODO_JOGAVEL.md` (arquitetura, fórmulas e histórico);
  - `docs/design/DECISION_LOG.md` (decisões em vigor);
  - `docs/design/ART_DIRECTION.md`;
  - `docs/design/ASSET_LICENSES.md`;
  - `docs/design/QUALITY_GATE.md`.
- O motor autoritativo é `backend/app/domain/highlights.py` (orquestração: relógio, oportunidades, decisões, reconexão). O núcleo de jogo V7 (física, goleiro, IA) está em `backend/app/domain/football/`; ver `docs/v7/MOTOR_V7.md`. A V6 (`Pitch`, em `highlights.py`) continua selecionável: `HighlightMatch.engine` e `GAMEPLAY_ENGINE`. Os renderizadores (`frontend/src/features/career/interactive/render/`) só desenham a `view` do servidor e nunca decidem resultado.
- O 2D e o 3D compartilham `presentation.ts`, que constrói a cena a partir dos quadros oficiais e dos "cues" físicos.
- Os parâmetros de jogo ficam no topo de `highlights.py`. Os visuais ficam em `render/config.ts`.

## Regras

- **Deploy:** só com autorização explícita do proprietário. Um push em `origin/main` publica no Render.
- **Assets:** nada de copiar assets proprietários ou extrair arquivos de APKs. Registre a licença de todo asset em ASSET_LICENSES.md.
- **Typecheck:** use `npm run typecheck`, que roda `tsc -b`. O comando `tsc --noEmit -p .` não verifica nada, porque o tsconfig raiz só tem referências.
- **Evidência:** use o Lab (`#lab` e `#lab-atleta`) e Playwright. Não declare qualidade visual sem capturas reais.
- **Medição:**
  - naturalidade e equilíbrio: `backend/tools/gameplay_metrics.py` (`ENGINE=v6|v7`);
  - goleiro: `backend/tools/keeper_battery.py`;
  - playtest automatizado: `frontend/scripts/playtest-lab.cjs`;
  - multiplayer 2D contra 3D: `frontend/scripts/verify-interactive.cjs`.
- **Trabalho em paralelo:** outra sessão pode estar em `futebol-manager-edicao-resenha` (worktree). Coordene antes de commitar no mesmo branch.
