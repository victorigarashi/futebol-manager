# AGENTS.md — Brasileirão Manager

Orientação para qualquer agente (humano ou IA) que trabalhe neste repositório.

## Antes de mudar o Modo Jogável

- Leia:
  - `docs/MODO_JOGAVEL.md` (arquitetura, fórmulas e histórico);
  - `docs/design/DECISION_LOG.md` (decisões em vigor);
  - `docs/design/ART_DIRECTION.md`;
  - `docs/design/ASSET_LICENSES.md`;
  - `docs/design/QUALITY_GATE.md`.
- O motor autoritativo é `backend/app/domain/highlights.py`. Os renderizadores (`frontend/src/features/career/interactive/render/`) só desenham a `view` do servidor e nunca decidem resultado.
- O 2D e o 3D compartilham `presentation.ts`, que constrói a cena a partir dos quadros oficiais e dos "cues" físicos.
- Os parâmetros de jogo ficam no topo de `highlights.py`. Os visuais ficam em `render/config.ts`.

## Regras

- **Deploy:** só com autorização explícita do proprietário. Um push em `origin/main` publica no Render.
- **Assets:** nada de copiar assets proprietários ou extrair arquivos de APKs. Registre a licença de todo asset em ASSET_LICENSES.md.
- **Typecheck:** use `npm run typecheck`, que roda `tsc -b`. O comando `tsc --noEmit -p .` não verifica nada, porque o tsconfig raiz só tem referências.
- **Evidência:** use o Lab (`#lab` e `#lab-atleta`) e Playwright. Não declare qualidade visual sem capturas reais.
- **Trabalho em paralelo:** outra sessão pode estar em `futebol-manager-edicao-resenha` (worktree). Coordene antes de commitar no mesmo branch.
