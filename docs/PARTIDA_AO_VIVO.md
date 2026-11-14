> Este documento registra a entrega anterior da transmissão. Para os resultados atuais da beta, consulte BETA_DELIVERY_REPORT.md e TESTING.md.

# Partida ao vivo — entrega

A rodada é transmitida durante **60 segundos reais**, equivalentes a 90 minutos. O servidor define o início e o término. Quando o último técnico humano confirma “Estou pronto”, as dez partidas ficam disponíveis com o mesmo relógio e cada técnico entra automaticamente na transmissão do próprio clube.

## Implementação

- O motor determinístico existente continua gerando cada partida uma única vez. A seed inclui sala, temporada e confronto. A preparação dos dez fluxos ocorre antes de publicar o início comum; não existem dez relógios independentes.
- Os eventos possuem tempos distintos dentro de cada minuto, preservando sua ordem causal. O mesmo fluxo determina gols, xG, estatísticas, pressão, bola e ações dos atletas.
- `SeasonService.advance` inicia a transmissão sem gravar resultados oficiais. `finish_due` efetua um único commit dos dez resultados após o prazo. Uma task por sala acompanha o prazo, mesmo sem espectadores conectados.
- `GET /api/v1/rooms/{room_id}/season/live` retorna a partida do técnico autenticado, o prefixo de eventos já liberados, os dez placares parciais e a classificação provisória. Cada resposta usa uma amostra única do relógio para placar, eventos e tabela.
- `GET /matches/{match_id}` exige participação do clube do técnico. O navegador oferece apenas replays do próprio clube.
- O WebSocket existente notifica início, ticks e encerramento. Na conexão/reconexão, envia `season.sync` com o estado personalizado. O cliente atualiza somente a consulta ao vivo nos ticks, sem buscar novamente lobby, mercado e histórico completo a cada notificação. Há polling de recuperação a cada segundo.
- A interface reutiliza o canvas do replay 2D, os escudos, os tokens visuais e as páginas existentes. As posições partem da formação congelada no início da partida. Durante a transmissão não há pausa, salto para gol futuro ou aceleração.
- A pressão usa intervalos reais de três minutos do jogo; a tabela usa resultados anteriores mais os dez placares parciais, sem persistir resultados provisórios.
- O encerramento libera a rodada seguinte, a janela após a rodada 19 ou os playoffs após a rodada 38, preservando as regras existentes.
- Snapshots JSON opcionais guardam os fluxos completos e os prazos da transmissão. A recuperação valida a rodada e retoma o relógio original; se o prazo já passou, o servidor oficializa ao iniciar.

A arquitetura original permanece: estado em memória de um único processo, sem banco ou Redis. Persistência após reiniciar depende da configuração opcional de snapshots descrita no README.

## Executar

Com Docker, use o fluxo existente do projeto:

```sh
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build
```

Acesse `http://localhost:5174`. O catálogo de demonstração contém jogadores e valores sintéticos e é separado de produção. Para usar dados reais, configure o catálogo autorizado já suportado pelo projeto.

## Verificações automatizadas

Na raiz do projeto, com Python 3.12 ou superior:

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m pytest backend/app/tests -o addopts='' -q
.venv/bin/ruff check backend
npm ci --prefix frontend
npm run test --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
```

Cobertura nova: dez partidas, prazo de 60 segundos com relógio controlado, nenhum resultado oficial antes do fim, prevenção de eventos futuros, reconciliação de estatísticas/replay, tabela após gol com rodadas anteriores, humanos no mesmo jogo e em jogos diferentes, autorização HTTP, WebSocket/reconexão, recuperação de snapshot, oficialização idempotente e início imediato da próxima rodada durante a notificação do encerramento.

## Teste de navegador com prazo real

O servidor de aceitação abaixo é **exclusivo para testes**. Ele monta uma sala sintética pronta para a rodada, com três identidades locais, sem mudar o fluxo de produção. Execute em três terminais:

```sh
# Terminal 1, a partir de backend:
CORS_ORIGINS=http://localhost:5174 APP_ENVIRONMENT=test ../.venv/bin/python -m uvicorn tools.live_acceptance:app --host 127.0.0.1 --port 8000
```

```sh
# Terminal 2, a partir de frontend:
npm run dev -- --host 127.0.0.1 --port 5174
```

```sh
# Terminal 3, a partir de frontend:
npx playwright install chromium
npm run test:live
# Alternativa para Chromium instalado no sistema:
# CHROMIUM_PATH=/usr/bin/chromium npm run test:live
```

Esse teste abre três contextos isolados, confirma os técnicos pela interface, verifica um campo por tela e seleção correta do confronto, testa celular a 390 px e desktop a 1440 px, simula perda de rede/recarregamento e aguarda a oficialização real. A sala deve estar nova a cada execução; reinicie o servidor de aceitação antes de repetir.

Os artefatos vão para `/tmp/brasileirao-live-artifacts` (substituível por `LIVE_ARTIFACTS`). O arquivo local de identidades é `/tmp/brasileirao-acceptance.json` (substituível por `LIVE_ACCEPTANCE_STATE` em ambos os processos). Esses arquivos temporários não integram a entrega.

## Resultado da validação nesta entrega

- Backend: 62 testes.
- Frontend: 5 testes.
- Ruff, ESLint e build TypeScript/Vite concluídos.
- Navegador Chromium: três sessões, um canvas por técnico, mesma partida para adversários humanos, outra partida para o terceiro técnico, sem transbordamento horizontal em desktop/celular e sem erros de JavaScript.
- Reconexão retomou em aproximadamente 23 minutos de jogo, mantendo o prazo original.
- Os dez resultados permaneceram provisórios até o prazo. O encerramento foi observado 60,76 segundos após o primeiro clique em “Estou pronto” (o último técnico confirmou depois desse primeiro clique); o prazo oficial do servidor é exatamente 60 segundos após o início comum.

A imagem de inspiração mencionada na solicitação não foi anexada à conversa. A organização implementada segue a descrição solicitada e a identidade visual que já existia no projeto.
