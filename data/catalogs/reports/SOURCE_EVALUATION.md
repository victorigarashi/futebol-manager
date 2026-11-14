# Avaliação de fontes para catálogo brasileiro

Data da avaliação: 13/11/2026.

## FC Mania Database / FCM 26 V5

- URL: https://patchfcm.fcmania.com.br/
- Versão anunciada: FCM 26 V5, squad de 17/09/2026, atualização da base em 25/09/2026.
- Cobertura pública anunciada: 25.045 jogadores, 943 clubes e 44 ligas.
- Campos visíveis: nome, clube, liga, overall, potencial, posições e resumos de atributos.
- Brasileirão: a base pública mostra a liga e jogadores no site.
- Download/exportação/API pública autorizada: **não localizada**.
- Permissão de redistribuição: **não concedida**. Os termos do patch limitam o produto a uso pessoal, individual e intransferível e não autorizam copiar o banco para outro projeto.
- Decisão: `SOURCE_RESTRICTED`. Não houve scraping, extração em massa, acesso a arquivos internos ou contorno de controles.

O importador `data/importers/fcmania_importer.py` está pronto para um CSV/JSON fornecido pelo responsável acompanhado de autorização escrita. O arquivo deve permanecer em staging até a verificação da licença.

## EAFC26 DataHub

- URL: https://github.com/ismailoksuz/EAFC26-DataHub
- Licença declarada do dataset Kaggle: CC BY 4.0.
- Campos: overall, potential, posições, atributos e `value_eur` interno do jogo.
- Limitação: os 280 candidatos brasileiros do CSV possuem várias identidades genéricas/sentinela e não são uma base brasileira confiável.
- Decisão: manter somente para temporadas internacionais e staging, sem substituir o catálogo brasileiro.

## Transfermarkt datasets

- URL: https://github.com/dcaribou/transfermarkt-datasets
- Licença do snapshot usado: CC0-1.0.
- Campos: identidade, clube no snapshot e avaliações históricas.
- Limitação: não fornece overall/potencial e não confirma o elenco Série A 2026.
- Decisão: usar apenas como enriquecimento financeiro histórico.

## CBF

- URL: https://www.cbf.com.br/futebol-brasileiro/atletas/campeonato-brasileiro/serie-a/2026
- Uso realizado: conferência manual da existência da competição e da página de atletas.
- Exportação licenciada para integração: não fornecida.
- Decisão: não copiar a listagem nem usar scraping para promoção automática.

## Alternativas pesquisadas

Datasets abertos encontrados fornecem ratings históricos, seleções nacionais ou dados de partidas, mas não uma base atual licenciada com jogadores reais dos 20 clubes da Série A 2026 contendo simultaneamente overall, potencial e atributos. Nenhuma alternativa foi integrada sem licença e procedência suficientes.
