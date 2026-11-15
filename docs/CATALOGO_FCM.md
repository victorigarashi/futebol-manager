# Catálogo de jogadores e clubes (lista FCM 27)

Data: 15/11/2026. Branch `feature/catalogo-fcm-fotos`.

## Origem

Dois CSVs fornecidos pelo responsável do projeto, que decidiu incluí-los no jogo:

- `brasileirao_fcm_titulares_reservas.csv`: 320 atletas, 16 por clube (11 titulares e 5 reservas), com ID FC Mania, nome, posição, camisa, overall, potencial, idade, nacionalidade e URL da foto;
- `brasileirao_fcm_times.csv`: 20 clubes, com formação e URL do escudo.

Os CSVs brutos não são versionados (`data/catalogs/sources/` está no `.gitignore`). O que fica no repositório é o catálogo gerado.

**Direitos de uso.** Os termos do patch FC Mania preveem uso pessoal, e as fotos e escudos pertencem aos seus titulares (ver `docs/pesquisa-dados/RELATORIO_FONTES_JOGADORES.md`). As imagens **não foram baixadas nem re-hospedadas**: o jogo guarda apenas a URL original e o navegador do jogador as carrega de lá. Se a fonte sair do ar ou bloquear o acesso, o jogo mostra as iniciais do atleta e o escudo local.

## Como foi integrado

- **Sem duplicatas:**
  - um registro por `player_id` da fonte (o importador recusa IDs repetidos);
  - nenhum nome repetido dentro de um clube;
  - o catálogo antigo foi **substituído**, e não somado.
- **IDs estáveis:**
  - 116 atletas que já existiam (mesmo nome e clube, ou nome único nos dois arquivos) mantêm o ID `BR26-…` e os atributos editoriais, ajustados pela diferença de overall;
  - os demais recebem `FCM-<id da fonte>`.
- **Removidos:**
  - os 144 genéricos `synthetic-career`;
  - 60 atletas do catálogo antigo que não estão na lista nova.
- **Posições:** o jogo tem quatro linhas (GOL, DEF, MEI, ATA).
  - Pontas e meias de lado (PD, PE, MD, ME) jogam na linha de ataque, como os importadores anteriores já faziam com LW/RW, e mantêm MEI como posição secundária.
  - O 11×11 exige 3 atacantes por clube. Por isso Ziyech, Cristian Medina e Memphis Depay, os meias-atacantes de melhor overall nos clubes que ficaram com menos de 3, passaram para a linha de ataque, com MEI como posição secundária.
- **Preços:** são internos do jogo (nunca uma cotação real). Seguem a mesma curva do catálogo anterior: cerca de R$ 4,4 mi para overall 63, R$ 20 mi para 72 e R$ 55 mi para 78.
- **Mercado inicial:** não exige mais orçamento para comprar um elenco inteiro. Um clube que não compra ninguém fica com os próprios atletas sem custo. A regra antiga só funcionava por causa dos genéricos de custo zero.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `data/catalogs/players.json` | Catálogo operacional (fonte `FC_MANIA_FCM27`), com `photo_url`, `shirt_number`, `squad_role` e `source_ids.fcmania` |
| `data/catalogs/clubs.json` | Clubes: formação da fonte, URL do escudo e ID na fonte |
| `data/catalogs/fcm_import_summary.json` | Relatório da importação |
| `frontend/src/lib/clubMedia.ts` | URLs dos escudos (arquivo gerado) |
| `data/importers/fcm_squads_importer.py` | Importador reproduzível |

Para regerar:

```sh
python3 -m data.importers.fcm_squads_importer \
  --players caminho/brasileirao_fcm_titulares_reservas.csv \
  --teams caminho/brasileirao_fcm_times.csv
```

## Onde as fotos aparecem

- mercado (cartões e ficha da proposta);
- elenco (reservas e ficha do atleta);
- central do clube (destaques);
- transferências;
- histórico do clube.

Os escudos aparecem em todos os lugares que já usavam `ClubCrest`.
