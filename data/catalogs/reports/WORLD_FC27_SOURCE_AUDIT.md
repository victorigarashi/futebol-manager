# Auditoria de fontes — Draft Mundial FC 27

Consulta: 17/11/2026. Este relatório distingue consulta pública de autorização
para distribuição. Nenhuma fonte de ratings FC 27 abaixo é importada no jogo.

| Fonte | Cobertura observada | Campos observados | Licença/permissão para redistribuir | Decisão |
| --- | --- | --- | --- | --- |
| [EA FC 27 Ratings](https://www.ea.com/games/ea-sports-fc/ratings) | 19.789 itens mostrados na consulta | OVR, PAC, SHO, PAS, DRI, DEF, PHY, posição, clube/nacionalidade | Acordo da EA proíbe copiar e distribuir conteúdo sem autorização expressa | Não importar |
| [FUTWIZ Career Mode](https://www.futwiz.com/fc27/career-mode/players) | Página declara cobrir todos os jogadores do modo carreira | overall, potencial, filtros por posição, idade, liga, clube e nação | Não foi encontrada licença de dados. A própria página informa que faces, escudos e logos pertencem à EA | Não importar |
| [FIFA Index](https://fifaindex.com/Players) | 21.672 jogadores mostrados na consulta | OVR, potencial e atributos detalhados, inclusive goleiro | Não foi encontrada licença aberta de redistribuição nos dados consultados | Não importar |
| [FUT.GG](https://www.fut.gg/fc-27/ratings/) | Banco FC 27 e Top 100 | ratings, atributos, preços e evoluções | Página declara © 2026 Stormstrike Inc.; não foi encontrada licença aberta de dados | Não importar |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing) | Base colaborativa, cobertura variável por atleta | ID estável, nome, nacionalidade, data de nascimento, posição e clube quando preenchidos | Dados estruturados sob CC0 | Elegível apenas para identidade; clube exige verificação temporal |
| [Wikimedia Commons](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia/licenses) | Arquivo a arquivo, cobertura variável | arquivo, autor, URL, licença e restrições informadas | Cada arquivo tem licença própria; crédito obrigatório em CC-BY | Elegível somente via manifesto e revisão individual |

## Resultado da pesquisa

Os portais FC 27 consultados oferecem dados e atributos de origem EA, mas não
concedem uma licença independente para embutir ou redistribuir essas tabelas no
jogo. Eles servem apenas como referência de pesquisa. `world_players.json`
continua com avaliações editoriais próprias e não afirma equivalência a EA FC.

O pipeline `data/importers/commons_photo_manifest.py` não faz scraping, não faz
correspondência automática por nome e não aceita URL remota como asset do jogo.
Ele só anexa uma foto local já revisada quando o manifesto contém QID, crédito,
licença permitida, checksum e estado de identidade/licença aprovados. Arquivos
CC-BY-SA, NC, ND, licença desconhecida ou com alerta de personalidade ficam
pendentes de revisão.

## Amostra de revisão negativa

As imagens atuais de Erling Haaland e Kylian Mbappé vinculadas no Wikidata foram
consultadas individualmente no Commons. Ambas se apresentaram como CC-BY-SA 4.0
e com aviso `personality`; nenhuma é incluída pelo pipeline. Isso demonstra que
o filtro evita a associação automática de uma foto aparentemente disponível.

## Próximo lote permitido

Um curador deve adicionar registros ao `world_photo_manifest.json` e colocar o
arquivo licenciado em `frontend/public/player-photos/world/`. Para cada linha:

1. confirmar manualmente o QID do atleta e a página do arquivo;
2. registrar o autor, a licença e a linha de crédito do Commons;
3. verificar se o Commons não aponta restrição de personalidade;
4. calcular SHA-256 do arquivo local;
5. executar o importador para gerar **outro** JSON de catálogo e revisar o
   relatório antes de trocar qualquer configuração do Draft.
