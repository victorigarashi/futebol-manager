# Auditoria cruzada: CSV BrazilSerieA e catálogo 2026

Data: 14/11/2026  
Decisão de promoção: **nenhum registro promovido para `players.json`**.

## Arquivo prioritário inspecionado

Origem: [AhmetFurkan3/data_scouting_app — BrazilSerieA.csv](https://github.com/AhmetFurkan3/data_scouting_app/blob/main/BrazilSerieA.csv)  
Commit verificado: `539e83e3ec17fe4bba011f5ef79b2b800213cfb6`  
SHA-256 do arquivo analisado: `93b1398d030a20e4f523bdf0dea41d4bf3b7fdcd55254234ac40cfcfbf2516ff`

O arquivo contém **522 linhas e 166 colunas**. As colunas cobrem identidade parcial (`Player`, `Nation`, `Position`, `Age`, `Squad`, `League`) e estatísticas por 90 minutos: gols, assistências, xG, xA, chutes, passes, passes-chave, conduções, dribles, desarmes, interceptações, bloqueios, recuperações, duelos aéreos e uma seção de goleiros/advanced goalkeeping.

Não há ID estável de atleta, data de nascimento, minutos, aparições, data de corte ou coluna de temporada. A composição de clubes inclui Fortaleza, Juventude, Sport Recife e Ceará, e não inclui Athletico, Coritiba, Chapecoense ou Remo. Portanto, ainda que o arquivo tenha sido encontrado num repositório atualizado em 2026, sua própria estrutura não confirma que represente a Série A 2026.

O repositório possui licença Apache-2.0 para o **trabalho do repositório**, mas o README afirma que os dados vêm do FBref. Essa licença do repositório não concede automaticamente direitos sobre os dados de terceiros. Os [termos da Sports Reference/FBref](https://fbref.org/termsofuse.html) e a [política de uso de dados](https://fbref.co.uk/data_use.html) vedam criar base ou serviço substituto com dados do site sem permissão e informam que parte das bases não pode ser redistribuída. Por isso o CSV não foi copiado para este ZIP nem usado para calcular ratings publicados.

## Cruzamento de identidade: método e resultado

Foram analisados, localmente e sem promover os dados brutos:

- `BrazilSerieA.csv`: 522 linhas / 166 colunas;
- [wiUl/scrapping-brasileirao-sofascore](https://github.com/wiUl/scrapping-brasileirao-sofascore): 566 jogadores, 20 clubes e 118 colunas, com `player_id` e `team_id`;
- [glauber-molinari/BRASIM26](https://github.com/glauber-molinari/BRASIM26): 840 atletas em 20 clubes, com posição macro e idade, sem ID estável de jogador;
- [jhonatasjgr/brasileirao-2025](https://github.com/jhonatasjgr/brasileirao-2025): histórico Cartola 2025; não usado para confirmar elenco 2026;
- [FootyStats Série A](https://footystats.org/pt/brazil/serie-a/datasets): avaliado como potencial fonte comercial, sem download/login automatizado.

O cruzamento foi conservador. Um candidato precisava ter: (1) nome normalizado único no wiUl; (2) o mesmo clube atual entre wiUl e BRASIM26; (3) posição macro compatível; e (4) diferença de idade de até dois anos entre o CSV e o BRASIM26. Isso evita fundir homônimos apenas pelo nome, mas **não equivale a verificação definitiva**: não há data de nascimento no CSV prioritário e o BRASIM26 não oferece ID de atleta.

Resultado: **168 candidatos plausíveis** dos 522 registros. Cobertura entre esses candidatos: 13 GK, 68 DF, 49 MF e 38 FW. Há candidatos em 19 dos 20 clubes do wiUl; Athletico não alcançou um cruzamento de três fontes nas regras acima. Esse número é uma fila de revisão, não uma contagem de atletas elegíveis para produção.

Exemplos que passaram no cruzamento triplo (identidade não promovida): Yuri Alberto — Corinthians — `player_id` wiUl 905463 — FW; Caio Alexandre — Bahia — 1008832 — MF; Anthoni — Internacional — 1106134 — GK; Lucas Arcanjo — Vitória — 982558 — GK; Fabrício Bruno — Cruzeiro — 840220 — DF; Arthur Cabral — Botafogo — 870762 — FW; Hulk — Atlético Mineiro — 34705 — FW; Kaio Jorge — Cruzeiro — 954888 — FW. Eles ilustram a evidência de clube e posição, não autorizam a distribuição das estatísticas subjacentes.

## Viabilidade do modelo de rating

`BRASILEIRAO_MANAGER_RATING_V1` exige:

- GK: idade, minutos, aparições, regularidade, defesas e taxa de gols sofridos;
- DF: idade, minutos, aparições, regularidade, desarmes, interceptações e duelos;
- MF: idade, minutos, aparições, regularidade, passes, passes-chave e assistências;
- ST: idade, minutos, aparições, regularidade, chutes, gols e assistências.

O CSV priorizado fornece vários indicadores por 90, mas não minutos, aparições nem regularidade e é juridicamente bloqueado para esta distribuição. Assim, atletas com dados suficientemente autorizados para `BRASILEIRAO_MANAGER_RATING_V1`: **0**; ratings próprios gerados: **0**. Não foi reduzida a exigência do modelo, pois isso transformaria ausência de exposição em nota arbitrária.

## Bloqueios por fonte

| Fonte | Situação de dados | Situação de direitos | Ação neste ZIP |
|---|---|---|---|
| CSV Ahmet/FBref | 522 estatísticos, sem temporada/ID/minutos/aparições | Apache-2.0 não transfere direitos sobre FBref; uso/dados em massa exigem permissão | Excluído; apenas checksum e auditoria |
| wiUl/SofaScore | 566 jogadores, 118 colunas, IDs de provedor | Sem `LICENSE` no repositório; [SofaScore proíbe scraping/reprodução sem consentimento](https://www.sofascore.com/terms-and-conditions) | Excluído; usado somente para auditoria local |
| BRASIM26 | 840 nomes/posições/idades; sem ratings | Sem `LICENSE`; scripts consultam API-Football e Transfermarkt | Excluído; não usar chave exposta no código |
| Cartola 2025 | Histórico de 2025 | Sem licença verificável no clone auditado; não confirma 2026 | Excluído |
| FootyStats | Página oferece API/CSV | [Proíbe revenda ou redistribuição dos dados](https://footystats.org/api/documentations/terms-of-use-and-legal) | Não baixado; exigir licença específica |

## Consequência para jogo, mercado e bots

Não houve atletas elegíveis a inserir no mercado ou distribuir para bots. Esta é uma decisão de segurança de dados, não uma falha técnica: importar os 168 candidatos ou os 522 registros os faria parecer licenciados e atuais quando nenhuma dessas duas condições foi comprovada.

Os dados bloqueados permanecem somente fora do ZIP, no ambiente temporário de auditoria. Este pacote conserva manifestos, pipeline offline, contratos e relatórios; não contém o CSV de FBref, o CSV SofaScore, `players.json` do BRASIM26, imagens, chaves, nem estatísticas brutas de fontes bloqueadas.

## Rota para desbloquear registros reais

Para gerar o primeiro catálogo distribuível, é necessário receber uma exportação licenciada que permita expressamente armazenamento, cálculo derivado e redistribuição no jogo. Ela deve conter, por atleta, ID estável, nascimento ou evidência equivalente, clube/Série A 2026, posições, minutos/aparições e as métricas posicionais exigidas. O pipeline então pode cruzar por ID + nascimento, calcular `INTERNAL_ESTIMATE`, verificar cobertura de 20 clubes e escrever `players.json` sem duplicidade.
