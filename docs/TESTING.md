# Guia de testes da beta

As validações anteriores não foram reutilizadas como aprovação desta entrega. O backend foi reexecutado e ampliado de 62 para 77 testes. O frontend foi reexecutado com 6 testes após atualizar ferramentas.

## Automação básica

Na raiz, após instalar conforme RUNNING.md:

```sh
.venv/bin/python -m pytest backend/app/tests -o addopts='' -q
.venv/bin/ruff check backend
npm run typecheck --prefix frontend
npm run lint --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
npm audit --prefix frontend
```

O Node deve ser 22.12+ ou 24. Vitest foi atualizado para 5.1 e o lockfile atualizado. Há override localizado de `minimatch` 11.0.8 para `@typescript-eslint/typescript-estree`, pois a versão publicada do linter ainda aceitava uma versão com advisory. Lint, testes e build foram reexecutados com esse override. O audit final, incluindo dependências de desenvolvimento, retornou zero alertas na consulta executada; isso não é garantia contra advisories futuros.

## O que o backend valida

Além dos testes de domínio, `test_beta_api_flow.py` percorre via HTTP os modos 5x5 e 11x11: duas identidades, sala, clubes, mercado, propostas sigilosas, prévia sem débito, multa/confirmar, redistribuição, review, escalação e estratégia, 38 rodadas, transferências, playoffs, campeão, segunda temporada e restauração de snapshot. Relógio controlado acelera esse teste, preservando a regra de 60 segundos do servidor.

`test_live_round.py` verifica prefixo sem futuro, sincronização, dez jogos, tabela, idempotência, reconexão e transição de timers. Os testes beta de segurança/transferências verificam permissões, reservas, contrapropostas, concorrência, anúncios, validações e recuperação sem estado parcial. Consulte QA_REPORT.md para a matriz detalhada.

## Navegador: todas as telas e viewports

Use três terminais. Os fixtures abaixo usam dados sintéticos explícitos e os motores reais para preparar etapas reproduzíveis. Não são mocks de respostas HTTP e não entram no servidor normal.

Terminal 1, na raiz:

```sh
APP_ENVIRONMENT=test ENABLE_DEMO_CATALOG=true CORS_ORIGINS=http://localhost:5174 .venv/bin/python -m uvicorn tools.beta_acceptance:app --app-dir backend --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
VITE_API_BASE_URL=http://localhost:8000/api/v1 npm run dev --prefix frontend -- --host 127.0.0.1 --port 5174
```

Terminal 3:

```sh
cd frontend
npx playwright install chromium
npm run test:beta
node scripts/verify-onboarding.cjs
node scripts/verify-home-recovery.cjs
node scripts/verify-club-dialogs.cjs
# Com Chromium do sistema, prefixe CHROMIUM_PATH=/usr/bin/chromium.
```

O script verifica home, lobby, mercado, seleção, redistribuição, review, elenco 5x5 e 11x11, campeonato, pós-jogo, transferências, campeão e histórico. Em cada tela testa 375×812, 390×844, 768×1024, 1280×720, 1366×768, 1600×900 e 1920×1080. Captura screenshots e executa axe WCAG 2A/AA e 2.1AA em mobile e desktop. Onboarding é validado separadamente nos sete tamanhos, incluindo edição de perfil e identidade após reload.

As ações reais de UI incluem modal por teclado/Escape, criar sala/escolher clube, paginar catálogo, editar proposta em reais, salvar escalação, colocar atleta à venda e abrir evolução da carreira. Também injeta falha 503 em `/me` para verificar que não cria novo convidado e bloqueia localStorage para verificar recuperação pela associação no servidor.

Artefatos padrão: `/tmp/brasileirao-beta-artifacts`. Configure `BETA_ARTIFACTS` para outro destino. Reinicie o servidor de aceitação para restaurar os estados antes de repetir fluxos mutáveis. Não use suas salas reais nesses fixtures.

## Transmissão com 60 segundos reais

Em servidor e frontend isolados:

```sh
# Terminal 1, raiz
APP_ENVIRONMENT=test ENABLE_DEMO_CATALOG=true LIVE_ACCEPTANCE_STATE=/tmp/brasileirao-live-final.json CORS_ORIGINS=http://localhost:5175 .venv/bin/python -m uvicorn tools.live_acceptance:app --app-dir backend --host 127.0.0.1 --port 8002
```

```sh
# Terminal 2, raiz
VITE_API_BASE_URL=http://localhost:8002/api/v1 npm run dev --prefix frontend -- --host 127.0.0.1 --port 5175
```

```sh
# Terminal 3, raiz
LIVE_ACCEPTANCE_STATE=/tmp/brasileirao-live-final.json LIVE_WEB_URL=http://localhost:5175/ LIVE_API_URL=http://localhost:8002/api/v1 npm run test:live --prefix frontend
```

Esse teste mantém três contextos independentes, compara dois adversários no mesmo jogo e outro técnico em jogo diferente, um canvas por tela, reconexão e reload, e espera o prazo real para verificar os dez resultados. O relógio oficial dura exatamente 60 segundos a partir do início comum; a duração observada desde o primeiro clique inclui o tempo até o último técnico confirmar e a apresentação da resposta no navegador.

## Limites das evidências

- API acelera a carreira inteira; navegador valida as telas/ações e a partida em tempo real. Não é uma pessoa jogando todas as 38 transmissões em sequência no navegador.
- Axe não substitui avaliação humana com leitor de tela, percepção de movimento e legibilidade sob todas as condições. Foram executados testes automáticos de teclado/foco, contraste das telas verificadas e redução de movimento.
- Não houve deploy, teste de carga público, validação com atletas licenciados ou teste físico em celulares; mobile significa Chromium nos viewports indicados.
