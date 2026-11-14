# Auditoria de fontes do catálogo — Série A 2026

Data da auditoria: 14/11/2026  
Escopo: fontes indicadas para o Brasileirão Manager — Edição Resenha. Esta auditoria não copiou, raspou em massa ou promoveu para produção qualquer base de terceiros.

## Resultado executivo

**Jogadores prontos para o catálogo operacional: 0.** Há cobertura técnica suficiente em fontes candidatas, mas não há nesta entrega uma combinação de dados de identidade, elenco 2026 confirmado, estatísticas e licença de redistribuição que permita publicar 320 atletas no ZIP. Portanto `data/catalogs/players.json` continua ausente de propósito e o mercado não deve ser declarado pronto com elenco real.

O ZIP auditado não inclui os snapshots brutos de staging que estavam no ZIP de entrada. Mantém apenas manifestos, relatórios, contrato, importadores offline e este parecer. Isso evita redistribuir material cuja cadeia de direitos não foi comprovada.

## FC Mania FCM 26 V5: inspeção direta

A base consultada foi **FCM 26 V5 (17/09/2026)**, exibida no site como atualizada em 30/10/2026. A navegação oferece **Jogadores**, **Times** e **Ligas**, seletor de edição (FCM 27/26/25), busca e filtros por liga, nacionalidade, idade, categoria, faixa de OVR, elenco, face real e posições GOL/DEF/MEI/ATA.

Na tabela de jogadores são mostrados nome, clube, nacionalidade, OVR, POT, posição, idade e os seis grupos RIT, FIN, PAS, DRI, DEF e FÍS. Uma ficha individual verificada (Kylian Mbappé, usada apenas para confirmar o formato, não como registro do jogo) expõe:

- identidade, clube, liga, seleção, idade, altura, peso, pé preferido, skills, pé fraco, reputação, camisa, contrato e nascimento;
- OVR e potencial;
- posições principal/secundárias;
- RITMO (aceleração, pique), FINALIZAÇÃO (posicionamento, finalização, força do chute, chute de longe, voleio, pênaltis), PASSE (visão, cruzamento, falta, curto, longo, curva), DRIBLE (agilidade, equilíbrio, reação, controle, drible, compostura), DEFESA (interceptação, cabeceio, consciência, dividida, carrinho), FÍSICO (impulsão, fôlego, força, agressividade) e GOLEIRO (elasticidade, manejo, chute, reflexo, posicionamento).

O rodapé informa que os dados são extraídos do squad do patch FC Mania. A página não ofereceu exportação oficial, API documentada nem licença de reutilização. Os [termos do FC Mania](https://fcmania.com.br/termos-de-uso-patchs-fc-mania/) concedem uso pessoal, individual e intransferível do patch. Consequência: nenhum dado FC Mania, foto ou rating foi importado ou redistribuído. Para usar o material no jogo seria necessária autorização escrita do FC Mania/representantes dos titulares, cobrindo extração, armazenamento, criação de derivados e redistribuição no ZIP.

## Fontes investigadas

| Fonte | Arquivos/estrutura verificados | Cobertura útil | Situação para o ZIP |
|---|---|---:|---|
| [wiUl/scrapping-brasileirao-sofascore](https://github.com/wiUl/scrapping-brasileirao-sofascore) | `data/brasileirao_2026_player_stats.csv`: 566 linhas, 566 `player_id` distintos, 118 colunas, 20 clubes | Identidade, clube e estatísticas de jogo; inclui gols, assistências, passes, desarmes, interceptações, duelos, minutos e métricas de goleiro. Não inclui posição, OVR ou POT. | **Bloqueada.** Repositório não traz `LICENSE`; o README declara origem SofaScore. Os [termos do SofaScore](https://www.sofascore.com/terms-and-conditions) proíbem agregação, scraping e reprodução sem consentimento expresso. Pedir licença ao titular/autor antes de ingestão ou redistribuição. |
| [glauber-molinari/BRASIM26](https://github.com/glauber-molinari/BRASIM26) | `players.json`: 20 clubes, 840 atletas, 87 GK/267 DF/259 MF/227 FW; 35–55 atletas por clube | Nome, posição macro, idade, camisa e URL de foto. Sem ID estável por atleta, OVR, POT ou estatísticas individuais. Scripts apontam API-Football e Transfermarkt. | **Bloqueada.** Sem `LICENSE`; IDs devem ser reconciliados por fonte autorizada. Não usar a chave pública encontrada no código. |
| [jhonatasjgr/brasileirao-2025](https://github.com/jhonatasjgr/brasileirao-2025) | `cartola_api_completo.csv`: 28.589 linhas, 46 colunas, temporada 2025 | Histórico Cartola; não comprova elenco 2026. | **Bloqueada e desatualizada.** README cita MIT, mas não há arquivo de licença no clone auditado; origem Cartola/Globo requer direitos próprios. |
| [lucasscalioni/scraper-whoscored-brasileirao](https://github.com/lucasscalioni/scraper-whoscored-brasileirao) | saída de jogadores: 113 linhas, `IdJogador,Name,Time,Position` | Estrutura de ETL e identidade histórica 2024/25. | **Bloqueada e insuficiente.** Sem licença; dados provenientes de WhoScored; não é elenco 2026. |
| [campoanaliticoestudos/Banco-de-dados-futebol](https://github.com/campoanaliticoestudos/Banco-de-dados-futebol) | CSVs de partidas/eventos, com material brasileiro principalmente histórico | Referência analítica de partidas, não um catálogo de elencos 2026. | **Não elegível.** Sem licença detectada e sem cobertura de jogadores necessária. |
| [leeofernandes1980/brasileirao-dataset](https://github.com/leeofernandes1980/brasileirao-dataset) | `campeonato-brasileiro-full.csv`: 8.405 linhas, 16 colunas | Calendário/resultados (mandante, visitante, formações, técnicos, placar), não jogadores. | **Não elegível.** Sem licença detectada; não fornece o catálogo requerido. |
| [FootyStats Série A datasets](https://footystats.org/pt/brazil/serie-a/datasets) | Página apresenta 20 times e download/API de estatísticas; a página consultada anunciava CSV de jogadores com 871 linhas | Pode conter cobertura estatística atual, sob oferta comercial/API. | **Pendente de contratação/licença.** Não foi feito download automatizado nem login. Confirmar por escrito permissão para armazenamento e redistribuição de nomes, clubes, posições e estatísticas no jogo. |

### Campos confirmados no CSV wiUl

Além dos quatro identificadores (`player_id`, `player_name`, `team_id`, `team_name`), há rating de fonte, gols, assistências, `expectedGoals`, `expectedAssists`, passes certos/totais por zona, passes-chave, dribles, desarmes, interceptações, cartões, cruzamentos, chutes, duelos, minutos, pênaltis, bolas longas, cortes, perdas/recuperações, defesas, clean sheets, gols sofridos, além de partidas iniciadas/aparições. Isso é materialmente suficiente para alimentar o modelo interno **quando** houver autorização e um mapeamento de posição confiável. Não é suficiente para chamar nenhum resultado de OVR/POT oficial.

## Confronto e qualidade

O cruzamento não foi promovido por igualdade de nome. As fontes divergem em escopo, temporada e identificadores:

- wiUl possui ID de jogador e ID de equipe, mas não posição primária/segunda;
- BRASIM26 oferece apenas posição macro e nomes, sem ID de atleta estável;
- Cartola/WhoScored são históricos de 2025 ou anteriores;
- o dataset leeo é de partidas, não de atletas.

Mesmo que wiUl e BRASIM26 tenham cobertura numérica acima de 320, não há prova de que cada associação de nome represente o mesmo atleta ou vínculo 2026. A integração deve exigir identificador de provedor + nascimento/nacionalidade, ou uma fila de revisão humana para cada conflito.

## Modelo de rating próprio (já existente)

O importador `data/importers/brasileirao_rating_model.py` continua sendo o único mecanismo aceito para estimativas internas. Ele só produz resultado se todos os indicadores estiverem presentes e normalizados em 0–100; caso contrário retorna pendente.

| Posição | Indicadores obrigatórios | Pesos do overall |
|---|---|---|
| GK | idade, minutos, aparições, regularidade, defesas, taxa de gols sofridos | 30% defesas, 25% inverso da taxa de gols sofridos, 20% regularidade, 15% minutos, 10% aparições |
| DF | idade, minutos, aparições, regularidade, desarmes, interceptações, duelos | 30% interceptações, 25% desarmes, 20% duelos, 15% minutos, 10% regularidade |
| MF | idade, minutos, aparições, regularidade, passes, passes-chave, assistências | 30% passes, 20% passes-chave, 20% assistências, 20% minutos, 10% regularidade |
| ST | idade, minutos, aparições, regularidade, chutes, gols, assistências | 35% gols, 20% chutes, 15% assistências, 20% minutos, 10% regularidade |

`overall` e `potential` são limitados a 1–99. `potential = overall + clamp((24 - idade) × 0,8, -5, +7)`. Todo resultado deve sair com `confidence: INTERNAL_ESTIMATE`, versão do modelo, fonte, data de corte e lista dos campos de entrada. O preço inicial em centavos é calculado apenas por `game_pricing.py`; é valor interno do jogo, nunca valor de mercado oficial.

## Contrato de integração e autorização por campo

O contrato Pydantic requer `id`, nome, código de clube, idade, posição, overall, potencial, valor em centavos, fonte e versão. Todo registro aprovado deve portar no mínimo:

```json
{
  "catalog_version": "2026-licensed-YYYYMMDD",
  "source": "PROVIDER_NAME",
  "source_version": "provider-release-or-cutoff",
  "source_retrieved_at": "YYYY-MM-DD",
  "authorization_status": "WRITTEN_REDISTRIBUTION_PERMISSION",
  "player_source_id": "stable-provider-id",
  "identity_evidence": ["provider_id", "date_of_birth", "nationality"],
  "rating_model": "BRASILEIRAO_MANAGER_RATING_V1",
  "rating_status": "INTERNAL_ESTIMATE"
}
```

As posições devem ser normalizadas para `GK`, `DF`, `MF` ou `ST`, preservando a posição original e as secundárias. Valores monetários devem ser inteiros em centavos. Fotos, escudos e marcas ficam fora deste pipeline até haver licença separada.

## Próximo passo desbloqueador

1. Contratar ou obter autorização escrita de uma fonte que permita publicação do catálogo no aplicativo e no ZIP, ou assinar licença direta com a detentora apropriada.
2. Receber CSV/JSON exportado oficialmente, com ID estável, data de nascimento, clube/temporada 2026, posição primária/secundárias e estatísticas por competição/data.
3. Rodar `python3 -m data.importers.catalog_builder` localmente contra o arquivo autorizado; o processo deve gerar relatório de conflitos, cobertura e viabilidade antes de escrever `players.json`.
4. Exigir no mínimo 320 atletas e, para cada clube, cobertura para a escalação exigida (inclusive GK, DF, MF e ST). Só após essa validação promover os registros e declarar o mercado pronto.

Nenhum dado desta auditoria é apresentado como rating oficial de EA, FC Mania, SofaScore, Transfermarkt, API-Football ou FootyStats.
