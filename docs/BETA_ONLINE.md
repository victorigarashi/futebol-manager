# Beta online em VPS

O repositório inclui `docker-compose.production.yml` para uma única instância FastAPI e um único worker. Não use réplicas: salas, timers, WebSockets e estado do mercado vivem em memória.

## Preparação

1. Instale Docker Compose em uma VPS Linux.
2. Crie um `.env` fora do ZIP com `APP_SECRET` aleatório de pelo menos 32 caracteres e `CORS_ORIGINS=https://seu-dominio.example`.
3. Coloque um catálogo autorizado em `data/catalogs/players.json`. Sem ele, produção permanece bloqueada; use `ENABLE_DEMO_CATALOG=true` apenas localmente em desenvolvimento.
4. Garanta que `data/snapshots/` esteja em volume persistente e faça backups do arquivo JSON.
5. Execute `docker compose -f docker-compose.production.yml up -d --build`.

O frontend fica em `127.0.0.1:8080`. Coloque um proxy HTTPS externo (Nginx, Caddy ou Traefik) na frente dele, encaminhando `/` para a porta 8080. O Nginx interno encaminha `/api/v1/` e o upgrade WebSocket para o backend.

## HTTPS e WebSocket

O certificado TLS deve ser terminado no proxy externo. A URL pública deve usar `https://`; o navegador converterá o WebSocket para `wss://` pela mesma origem. Teste duas sessões de navegador, criação/entrada na sala, reconexão e restauração do snapshot antes de convidar amigos.

Não há deploy público realizado por este pacote e nenhum domínio/credencial foi incluído.
