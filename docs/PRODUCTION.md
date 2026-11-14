# Preparação para um deploy futuro

Nenhum deploy foi realizado. A aplicação continua em uma instância única, em memória, com snapshots JSON opcionais. Não adicionar múltiplos workers ou réplicas: isso divide salas, timers, ofertas e conexões em estados diferentes.

## Configuração obrigatória

- `APP_ENVIRONMENT=production`.
- `APP_SECRET`: segredo exclusivo de pelo menos 32 caracteres, gerado fora do repositório. Trocar o segredo invalida cookies existentes.
- `SESSION_COOKIE_SECURE=true`; servir por HTTPS.
- `CORS_ORIGINS`: origens HTTPS exatas do frontend, sem `*`.
- `ENABLE_DEMO_CATALOG=false`.
- `PLAYER_CATALOG_PATH`: catálogo autorizado legível.
- `ENABLE_JSON_SNAPSHOTS=true` e `SNAPSHOT_PATH` em volume persistente gravável; backup e permissões restritas.

A configuração recusa produção com segredo padrão/curto, cookie inseguro, CORS aberto/HTTP ou demo habilitado.

## Topologia

Compile o React com `npm ci && npm run build` em `frontend` e sirva `dist` como conteúdo estático. Configure `VITE_API_BASE_URL=/api/v1` antes do build para um proxy de mesma origem; a geração de URL WebSocket aceita base relativa. O proxy deve encaminhar `/api/v1` e o upgrade de `/api/v1/ws` ao FastAPI.

Backend, um processo:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 4096
```

Não usar `--reload`, Vite dev server ou os servidores `tools.*` publicamente. O Compose fornecido é de desenvolvimento, não um orquestrador de produção.

## Limites e operação

- Limites configuráveis em memória: `REQUEST_LIMIT_PER_MINUTE=600`, `AUTH_LIMIT_PER_MINUTE=120`, `MAX_REQUEST_BODY_BYTES=1048576`.
- O backend valida `Origin` em mutações e WS, identidade, associação à sala e papel do técnico. CORS não substitui esses controles.
- O proxy deve fornecer TLS, limites globais, timeout de upgrade e tamanho de cabeçalhos/corpos. Não confiar em `X-Forwarded-For` enviado diretamente por clientes. Ajuste limite com base em carga medida, especialmente durante transmissão.
- WebSockets não são log persistente de eventos; o cliente reconsulta estado ao reconectar e usa polling de recuperação.
- Snapshots são gravados atomicamente e validados antes de restaurar. Falha de disco ainda pode deixar memória mais recente que o último JSON; backup/restauração precisam ser exercitados na infraestrutura escolhida.
- Cookies de convidado são identidades assinadas, não autenticação com senha. Não há recuperação externa de identidade após apagar o cookie.
- Não registrar tokens, cookies, propostas secretas completas ou segredos em logs. O esquema OpenAPI não inclui credenciais reais.

## Verificação antes de disponibilizar a amigos

Use os guias de testes e evidências desta entrega como base. No ambiente escolhido, valide HTTPS/cookies/Origin reais, abertura de duas sessões, reconexão, escrita/leitura do volume e recuperação após reiniciar. O teste local automatizado não valida DNS, proxy, latência pública ou falhas do provedor. Não foi executado teste de carga com jogadores reais.
