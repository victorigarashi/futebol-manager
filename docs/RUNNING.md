# Execução local e testes com amigos

## Requisitos

- Node.js 22.12+ ou 24; npm.
- Python 3.12+.
- Ou Docker Engine com Compose.
- Catálogo real autorizado, ou modo demo explicitamente ativado em desenvolvimento/teste.

## Docker (desenvolvimento)

```sh
cp .env.example .env
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build
```

Abra `http://localhost:5174`. API: `http://localhost:8001/api/v1`; documentação: `http://localhost:8001/docs`.

O Compose é de desenvolvimento: usa recarga automática e o servidor Vite. Não é a configuração de produção. O modo demo vem desligado por padrão. Sem catálogo e sem demo, iniciar o mercado é recusado com mensagem explícita.

## Sem Docker

Na raiz:

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm ci --prefix frontend
```

Terminal do backend, a partir de `backend`:

```sh
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true CORS_ORIGINS=http://localhost:5174 ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal do frontend, a partir de `frontend`:

```sh
VITE_API_BASE_URL=http://localhost:8000/api/v1 npm run dev -- --host 0.0.0.0 --port 5174
```

## Fluxo para jogar

1. Defina o nome do técnico e crie a liga. Escolha 5x5/11x11, orçamento, número de humanos, prazo e multa.
2. Confirme um clube e compartilhe o código. Cada amigo entra em navegador/dispositivo próprio e escolhe um clube livre.
3. O anfitrião inicia quando todos têm clube. As demais equipes são controladas por bots.
4. Faça propostas secretas, ajuste valores e confirme os direitos desejados com a prévia financeira do servidor. Desistências compromissadas seguem a multa configurada.
5. Resolva oportunidades de redistribuição e assista/pule/reveja a apresentação. O anfitrião libera a prancheta.
6. Escolha formação, titulares, reservas e estratégia; salve a escalação. Abra a temporada.
7. Todos confirmam “Estou pronto”. Cada técnico entra na própria partida, com o mesmo relógio do servidor. Os dez resultados entram juntos após 60 segundos.
8. Após a rodada 19, use a janela de trocas. Feche a janela para continuar. Ao completar 38 rodadas, dispute playoffs, veja campeão e evolução, e inicie a próxima temporada.

## Celular e rede local

Para outros aparelhos, `localhost` aponta para o próprio aparelho. Configure `VITE_API_BASE_URL` com o endereço alcançável do backend e `CORS_ORIGINS` com a origem exata do frontend, inclusive porta. Frontend e backend devem estar no mesmo site para o cookie SameSite=Lax funcionar de forma previsível. Para acesso remoto, prefira domínio HTTPS e proxy de mesma origem conforme o guia de produção. Não foi feito deploy nesta entrega.

A sessão pertence ao cookie assinado, não ao nome do técnico. Não use dois técnicos no mesmo perfil de navegador; use contextos/perfis separados. Limpar cookies remove a identidade de convidado; não há conta/senha ou recuperação externa nesta arquitetura.

## Persistência

Sem snapshots, reiniciar o backend perde as salas em memória. Para preservar:

```sh
ENABLE_JSON_SNAPSHOTS=true
SNAPSHOT_PATH=data/snapshots/rooms.json
```

No demo, o caminho é `DEMO_SNAPSHOT_PATH=data/snapshots/demo-rooms.json`. Não compartilhe snapshots entre demo e produção. Use um único processo/worker e armazenamento persistente com permissão de escrita. Faça backup do JSON e mantenha `APP_SECRET` estável para preservar sessões.
