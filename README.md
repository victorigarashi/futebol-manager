# Brasileirão Manager — Edição Resenha

Beta de futebol multiplayer para jogar com amigos: ligas de 20 clubes, mercado secreto, gestão do elenco, jogos ao vivo, 38 rodadas, playoffs e carreira por múltiplas temporadas.

**Stack preservada:** React + TypeScript + Vite, FastAPI + Pydantic + WebSocket. Estado em memória de uma única instância, snapshots JSON opcionais. Sem banco, Redis ou serviço pago obrigatório.

## Início rápido em demonstração

O jogo usa o catálogo real em `data/catalogs/players.json`. Para testar com dados sintéticos claramente identificados:

```sh
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build
```

Abra `http://localhost:5174`. Crie o nome do técnico e a liga, escolha um clube e compartilhe o código. Use navegadores/perfis separados para cada técnico. O anfitrião inicia o mercado depois que todos escolhem seus clubes.

O demo está desligado por padrão e é recusado em produção. Sem demo, configure um catálogo autorizado antes de iniciar o mercado. O catálogo operacional (`data/catalogs/players.json`) traz 320 atletas reais com foto e os 20 escudos; veja [Catálogo FCM](docs/CATALOGO_FCM.md).

## O que a beta inclui

- Salas públicas/privadas, clubes exclusivos, bots e recuperação das próprias ligas pelo servidor.
- Propostas secretas em reais na interface, edição/cancelamento, reservas e prévia financeira autoritativa.
- Seleção de contratações, multas, redistribuição e apresentação dos reforços confirmados.
- Titulares/reservas, formações, estratégia e OVR efetivo validado pelo backend.
- Dez partidas por rodada, um campo 2D por técnico, 60 segundos do servidor, eventos e tabela ao vivo.
- Pós-jogo, replays próprios, transferências/trocas, anúncios, playoffs, campeão e histórico do clube.
- Layout responsivo, modais com teclado/foco, estados de erro/recuperação e tokens visuais centralizados.

## Documentação

- [Modo Carreira: motor 2D, partida ao vivo e nova interface](docs/MODO_CARREIRA.md)
- [Partidas condensadas (1:30 / 2:00 / 3:00), transmissão 2D e motor](docs/PARTIDAS_CONDENSADAS.md)
- [Fontes de dados de jogadores: cobertura e direitos de uso](docs/pesquisa-dados/RELATORIO_FONTES_JOGADORES.md)

- [Execução local e amigos](docs/RUNNING.md)
- [Modo demo e pendências de dados reais](docs/DEMO.md)
- [Entrega parcial de dados reais e auditoria de fontes](docs/CATALOG_DATA_DELIVERY.md)
- [Pipeline de importação e promoção do catálogo](data/importers/README.md)
- [Catálogo de jogadores e clubes com fotos (lista FCM 27)](docs/CATALOGO_FCM.md)
- [Estabilidade multiplayer no Render](docs/ESTABILIDADE_MULTIPLAYER.md)
- [Desempenho do tempo real no Render Free (WebSocket sequenciado, backpressure, canvas adaptativo)](docs/DESEMPENHO_TEMPO_REAL.md)
- [Testes e reprodução dos scripts de navegador](docs/TESTING.md)
- [Auditoria de UI e correções](docs/FINAL_UI_AUDIT.md)
- [Auditoria do backend](docs/BACKEND_AUDIT.md)
- [API e WebSockets](docs/API.md)
- [Preparação para produção futura](docs/PRODUCTION.md)
- [Beta online em VPS](docs/BETA_ONLINE.md)
- [Relatório consolidado da entrega](docs/BETA_DELIVERY_REPORT.md)

## Validação desta entrega

77 testes backend e 6 frontend aprovados; Ruff, ESLint, typecheck e build executados. Navegador Chromium percorreu telas e ações em sete viewports, com screenshots e verificações axe. A transmissão foi reexecutada com o prazo real de 60 segundos. Consulte o relatório consolidado para evidências e limites; não confundir implementação com prova de uso em produção.

## Persistência e limites

Sem snapshots, reiniciar o backend perde o estado. Habilite `ENABLE_JSON_SNAPSHOTS=true` e um caminho gravável; o demo usa um arquivo separado. Mantenha `APP_SECRET` estável para preservar cookies e use **um processo/worker, uma réplica**.

JSON não oferece garantias de banco de dados. Limpar cookies perde a identidade de convidado; não há conta/senha ou recuperação externa. O escudo correto do Bragantino não consta dos recursos autorizados recebidos: a célula da prancha estava incorreta e recebe fallback explícito até ser substituída por um recurso correto. Nenhum deploy foi realizado.
