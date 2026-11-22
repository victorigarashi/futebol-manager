# Retro Career: gate de nostalgia (menu principal, Central e Elenco)

**Status: aguardando aprovação visual do proprietário.** A identidade ainda não foi propagada para as demais telas, conforme o gate da ATUALIZACAO_V8.

## Como ver

```bash
# backend com carreira semeada (11×11, Flamengo × Remo, 2 técnicos)
cd backend && APP_ENVIRONMENT=test PLAYER_CATALOG_PATH=../data/catalogs/players.json LIVE_INTRO_SECONDS=6 \
  CORS_ORIGINS='["http://localhost:5180"]' CAREER_ACCEPTANCE_STATE=/tmp/retro-career.json \
  ../.venv/bin/python -m uvicorn tools.career_acceptance:app --port 8010
cd frontend && VITE_API_BASE_URL=http://localhost:8010/api/v1 npx vite --port 5180
node scripts/retro/gate.cjs /tmp/retro-career.json     # capturas + 32 verificações
```

- O gate gera as capturas reais em `gate/`, nas resoluções 1366×768 e 1920×1080, mais o celular a 390×844.
- O antes (`baseline/`), o mockup aprovado e o implementado ficam lado a lado em `comparativo/`.

## O que mudou

| Tela | Antes | Agora |
|---|---|---|
| Menu principal | Lista vertical escura | Categorias horizontais: Início, Jogar, Online e Personalizar. O tile dominante "Continuar carreira" traz o escudo e a sala reais; os demais tiles levam a ações existentes. Rodapé só com atalhos que funcionam |
| Moldura da carreira | Duas barras escuras empilhadas (cabeçalho e barra da sala) e um cabeçalho de clube | Placas angulares. À esquerda: escudo, clube, técnico e sala. À direita: temporada e rodada, posição e pontos, orçamento, prontos, conexão, convite e Menu. A navegação Central, Elenco, Mercado, Competições e Clube fica com cantos retos, e a ação principal "Próxima partida" em amarelo-esverdeado |
| Central | Cartões escuros | **Avançar:** a rodada atual e as próximas do clube, com escudos e mando, os técnicos prontos ou aguardando e "Preparar partida". **Notícias:** derivadas de eventos reais, com paginação. **Também:** próximo jogo, classificação compacta, elenco e finanças |
| Elenco | Campo plano e listas | **Campo em perspectiva:** camisas nas cores do clube, overall efetivo, sobrenome e barra de adequação à posição. **Também:** cartões de reservas com a adequação à vaga escolhida, atleta em destaque no topo, formação e força à direita, e ficha com comparação |

**Preservado sem alteração de regra:**

- validação no servidor;
- troca por seleção e por arraste;
- escalação automática e "Restaurar";
- cancelamento do "pronto" ao salvar;
- tempo real (socket e polling);
- modos curtos (sem Mercado) e anfitrião.

As telas de partida ao vivo, Modo Jogável, recuperação e pós-jogo continuam com a moldura antiga. Elas pertencem às frentes de gameplay e Football Experience.

## Decisões

| Item | Situação |
|---|---|
| Menu FIFA 16, Central FIFA 16, navegação horizontal e Elenco aprimorado | Aprovados pelo proprietário (PROMPT_MASTER §1). Implementados. **A aprovação visual desta implementação está pendente** |
| Seleção: amarelo-esverdeado na aba ativa e no CTA; turquesa no foco do tile | Segue os tokens sugeridos. O foco turquesa vem do FIFA 16 |
| Jogador sempre em destaque no Elenco: o de maior overall, até o técnico escolher | Apresentação, sem regra nova |
| Calendário por rodadas, não por dias | O jogo não tem datas reais. Não foram inventados dias da semana |
| Caixa de entrada na Central | **Não criada.** Não existe caixa de entrada no estado. As propostas ficam no Mercado. Pendente de decisão |
| Telas não migradas (Mercado, Competições, Clube, Táticas, pré-jogo, lobby, Draft, Pack) | Aparecem em painel escuro legível sobre o estádio até a propagação |

## Verificações (32/32, `gate/checks.json`)

- Nas duas resoluções:
  - Central, Elenco e Menu sem rolagem da página;
  - ação principal visível;
  - setas movem o foco entre os tiles;
  - Esc volta à Central e à aba Início do menu;
  - 11 titulares sem sobreposição de nomes;
  - Menu → Continuar volta à carreira;
  - sem erros no console.
- Troca titular ↔ reserva salva e **validada pelo servidor**.
- Celular: sem rolagem horizontal, sem titular cortado e sem sobreposição.
- O projeto inteiro passa no lint (0 avisos), nos 54 testes e no build.

## Pendências e próximos passos (depois da aprovação)

1. Propagar para Mercado, Perfil, Competições, Clube, lobby, Draft e Pack & Play. O pré-jogo e o pós-jogo dependem da coordenação com a frente Football Experience.
2. Táticas consumindo o contrato do Football Tactical Engine, quando ele existir. Nenhum slider decorativo.
3. Rever, junto com o proprietário, a tela de entrada (nome do técnico), que ainda tem o visual antigo.
4. Medir os fundos (cerca de 1 MB nos três WebP) e o custo do `backdrop-filter` em celular real.
