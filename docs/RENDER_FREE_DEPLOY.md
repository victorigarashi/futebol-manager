# Beta multiplayer no Render Free

## Arquitetura

O Blueprint `render.yaml` cria dois serviços gratuitos, ambos no Render:

- `brasileirao-manager-api`: FastAPI/Uvicorn, uma única instância e um único worker.
- `brasileirao-manager-web`: Static Site React/Vite com fallback SPA para `index.html`.

O frontend é compilado com `https://brasileirao-manager-api.onrender.com/api/v1`. O cliente deriva `wss://brasileirao-manager-api.onrender.com/api/v1/ws/...` dessa URL. CORS aceita somente `https://brasileirao-manager-web.onrender.com`; cookies são `Secure`, `HttpOnly` e `SameSite=Lax`. Os dois subdomínios `onrender.com` são same-site. Se os nomes já estiverem ocupados ou se for usado domínio próprio, atualize os dois valores juntos antes do primeiro deploy e reconstrua o Static Site.

## Publicação pelo Blueprint

1. Extraia o ZIP e envie o conteúdo para um repositório Git seu, sem arquivos `.env` reais.
2. No painel do Render, clique em **New > Blueprint**, conecte esse repositório e escolha `render.yaml`.
3. Revise que a API está no plano **Free**, que há `numInstances: 1`, e crie os dois serviços. O Render gera `APP_SECRET`; não o substitua por um segredo versionado.
4. Espere o healthcheck responder em `https://brasileirao-manager-api.onrender.com/api/v1/health`.
5. Abra `https://brasileirao-manager-web.onrender.com` em dois navegadores/perfis independentes e faça o roteiro de teste multiplayer.

## Roteiro de aceite online

1. No navegador A, crie uma sala e escolha um clube.
2. No navegador B, entre pelo código e escolha outro clube.
3. O host inicia o mercado; ambos enviam propostas, confirmam escolhas e chegam ao elenco.
4. Monte escalações, marque Pronto e acompanhe a partida de 60 segundos, campo 2D e classificação ao vivo.
5. Recarregue cada navegador e confira recuperação de sessão/room enquanto a mesma instância está viva.
6. Avance uma rodada e confirme os eventos WebSocket/reconexão.

## Limitações honestas do plano gratuito

O Web Service Free pode suspender após inatividade e o primeiro acesso posterior pode demorar. O filesystem é efêmero: o snapshot em `/tmp` pode ajudar somente enquanto a instância continua existindo; não é persistência confiável após reinício, redeploy ou suspensão. Sem banco ou armazenamento externo, salas e carreiras podem ser perdidas nesses eventos. Não há ping artificial configurado.

Esta beta usa uma única instância porque salas, locks e WebSockets estão em memória. Escalar para mais de uma instância exigiria armazenamento compartilhado e não faz parte desta publicação gratuita.
