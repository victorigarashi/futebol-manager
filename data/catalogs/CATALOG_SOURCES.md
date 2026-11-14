# Fontes e decisões de licenciamento

Consulta realizada em 13/11/2026. O arquivo de produção `players.json` permanece ausente e inalterado. O dado Transfermarkt processado fica em `staging/`, com campos de rating e atributos explicitamente ausentes.

## Importado para staging

- [dcaribou/transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets): licença CC0-1.0 no repositório. O próprio projeto informa snapshot até 06/07/2026, avaliações até 12/06/2026 e ausência de plantéis 2026/27. Dados tratados como fotografia histórica, não cotação atual nem vínculo de clube confirmado em novembro de 2026. Foram usados perfis, histórico de avaliações e aparições para gerar candidatos e evidência de utilização em 2025. Nenhum arquivo de foto foi baixado ou incluído.
- [EAFC26-DataHub](https://github.com/ismailoksuz/EAFC26-DataHub) / [dataset Kaggle original](https://www.kaggle.com/datasets/rovnez/fc-26-fifa-26-player-data): o endpoint público do Kaggle declara **Attribution 4.0 International (CC BY 4.0)**, versão 3, atualizada em 22/09/2025. O CSV versionado no DataHub contém 18.405 linhas e 110 colunas, incluindo overall, potential, posições e atributos. O staging guarda a atribuição, IDs EAFC e qualidade de identidade; não inclui URL/binário de foto. A licença permite redistribuição com atribuição, mas não resolve direitos subjacentes de marcas, likeness ou a validade de elenco em novembro de 2026.

## Não importado

- [EA SPORTS FC ratings](https://www.ea.com/games/ea-sports-fc/ratings): a página oficial não foi usada para extração em massa. Os ratings no staging são identificados apenas como EAFC26/Kaggle CC BY; não são apresentados como dados oficiais licenciados pela EA.
- [FC Mania Database](https://patchfcm.fcmania.com.br/) e [termos do patch](https://fcmania.com.br/termos-de-uso-patchs-fc-mania/): o patch é para uso pessoal, individual e intransferível. Não houve exportação autorizada nem autorização de redistribuição. Não foram acessados dados internos nem contornados controles.
- [CBF atletas Série A 2026](https://www.cbf.com.br/futebol-brasileiro/atletas/campeonato-brasileiro/serie-a/2026) e [termos CBF](https://www.cbf.com.br/termos-de-uso): a página consultada não expôs dados tabulares no leitor e os termos vedam cópia/reprodução não especificamente autorizada. Usada apenas como referência; sem coleta em massa.
- [PlayersDB](https://playersdb.app/): o usuário informou ter fornecido CSV antes, mas nenhum CSV foi encontrado no repositório ou Downloads nesta máquina. Os termos explicam que download não licencia direitos de terceiros. Não importado nem redistribuído.

## Ativos visuais

Manifesto de imagens vazio. URLs de imagens e binários foram excluídos porque a licença de dados não licencia imagem, escudo, marca ou direito de personalidade. Recursos neutros existentes no frontend permanecem sob seu próprio manifesto.

Este registro documenta a avaliação técnica das fontes, não constitui parecer jurídico.

## Avaliação FCM 26 V5 — 13/11/2026

A página pública do FC Mania anuncia uma Database FCM 26 V5 com overall, potencial, atributos, formações e elencos. Ela é suficiente para justificar um pedido de autorização, mas não para copiar o banco: os termos disponíveis descrevem o patch como produto de uso pessoal e individual. O projeto mantém o importador e um template de exportação em `data/catalogs/reports/`, porém não integra nenhum registro FCM sem autorização escrita.
