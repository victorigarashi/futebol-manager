# Auditoria dos atributos e da procedência dos ratings

Data: 20/11/2026. Branch `fix/resgate-beta`.

## 1. O que o jogo usa de verdade

| Catálogo | Atletas | Overall e potencial | Atributos detalhados (PAC/SHO/PAS/DRI/DEF/PHY e goleiro) |
|---|---|---|---|
| Brasileirão (`players.json`) | 320 | Lista de elencos **FC Mania FCM27**, fornecida pelo dono da liga em 15/11/2026 (`SUPPLIED_SQUAD_LIST`) | 114 atletas: **estimativa editorial do projeto de 14/11/2026**, deslocada pela diferença de overall. 206 atletas: **sem atributos** (o motor deriva um perfil transparente do overall e da posição). |
| Mundial (`world_players.json`) | 2.386 | Avaliação editorial própria `BRASILEIRAO_MANAGER_WORLD_RATING_V1` sobre a identidade CC0 do Transfermarkt-datasets | Nenhum |

**Nenhum** valor do jogo é rating oficial licenciado da EA SPORTS FC.

## 2. Por que os números não batem com o EA FC

1. **Mistura silenciosa de fontes e versões.** O overall vem do FCM27; os atributos vêm de uma estimativa editorial anterior, feita para outro overall. A diferença entre os dois overalls é de 3,4 pontos em média, chegando a 13.
2. **Atributos de outra pessoa.** O importador reaproveitava o atleta antigo "pelo nome, se único", sem olhar clube nem idade:

   | Atleta | Recebeu os atributos de |
   |---|---|
   | Everton (SAN) | Everton (CHA) |
   | Bruno Henrique (INT, 37 anos) | Bruno Henrique (FLA, 35 anos) |

3. **Posição.** Os alas do FC Mania ("MD/ME") vão para a linha de ataque, por decisão de projeto: o jogo tem 4 linhas e precisa de 3 atacantes por clube. Um lateral escalado como ala, como Wendell (SAO), aparece como atacante com perfil de defensor.
4. **206 atletas sem atributos.** O cartão mostra o perfil derivado. Antes, só havia um aviso genérico.

## 3. Comparação com a fonte oficial (amostra)

**Fonte:** página oficial pública "EA SPORTS FC™ 27 Liga do Brasil Player Ratings" (ea.com), lida em 20/11/2026. É uma consulta manual de amostra só para auditoria; nenhum dado da EA foi copiado para o catálogo.

| Atleta (EA FC 27) | Pos. EA | OVR EA | OVR no jogo (FCM27) | PAC/SHO/PAS/DRI/DEF/PHY na EA | No jogo (editorial) | Divergência |
|---|---|---|---|---|---|---|
| Luciano Juba (BAH) | LB | 77 | 77 | 84/70/73/78/70/62 | 79/53/69/66/75/73 | Overall igual; SHO −17, DRI −12, PHY +11 |
| Éverton Ribeiro (BAH) | CM | 76 | 74 | 69/75/79/77/52/51 | 65/74/78/80/38/65 | OVR −2; DEF −14, PHY +14 |
| Jean Lucas (BAH) | CM | 77 | 78 | 72/71/74/77/73/75 | 70/72/80/76/64/79 | OVR +1; DEF −9 |
| Erick Pulga (BAH) | LW | 73 | 75 | 77/70/63/77/29/49 | 75/75/67/77/38/66 | OVR +2; PHY +17 |
| Nicolás Acevedo (BAH) | CDM | 73 | 74 | 77/62/71/71/70/70 | (perfil derivado) | OVR +1 |
| Cristian Olivera (BAH) | RW | 73 | 74 | 88/68/62/77/37/60 | (perfil derivado) | OVR +1 |
| Rodrigo Nestor (BAH) | CM | 72 | 74 | 73/71/72/73/59/60 | (perfil derivado) | OVR +2 |
| Alejo Veliz (BAH) | ST | 72 | 73 | 71/71/57/67/29/75 | (perfil derivado) | OVR +1 |
| Ronaldo (BAH) | GK | 73 | 74 | (a página não mostra atributos de goleiro) | goleiro: atributos editoriais `gk_*` | OVR +1 |

**Conclusão:**

- O **overall** do FCM27 fica a ±2 do EA FC 27 na amostra. O FC Mania é um patch com valores próprios, próximos aos da EA, mas não idênticos.
- Os **atributos** editoriais divergem em até 17 pontos. Essa é a origem da percepção de que "os números não correspondem".

## 4. Correções aplicadas

- **Importador** (`data/importers/fcm_squads_importer.py`): o reaproveitamento por nome único só vale com a mesma idade (±1 ano).
- **Catálogo** (`players.json`): removidos os atributos de outra pessoa (Everton/SAN e Bruno Henrique/INT), que passam a usar o perfil derivado e identificado.
- **Procedência por atleta:** novos campos `rating_source` e `attribute_source`; `CatalogPlayer` passou a aceitá-los.
- **Cartão do jogador** (elenco): mostra em linguagem simples a origem do overall e dos atributos e diz explicitamente que não são ratings oficiais da EA.
- **Separação base × carreira:**
  - o catálogo guarda o overall base;
  - a carreira guarda o atual (`current_overalls`, `base_overall`, `overall_delta`);
  - a evolução não é destruída por uma atualização do catálogo.

## 5. Licença e alternativas

| Opção | Situação | Consequência |
|---|---|---|
| **A. Pedir autorização ao FC Mania** para o banco FCM27 completo (atributos inclusos) | Recomendada | Overall e atributos da **mesma** fonte e versão; resolve a mistura. Os termos atuais do patch dizem que ele é "uso pessoal, individual e intransferível". |
| B. Atributos do dataset EAFC26 (Kaggle, **CC BY 4.0**, já analisado em `staging/`) | Possível, com atribuição | É **FC 26**, não 27: precisaria ficar rotulado como "EA FC 26 (dataset CC BY)" e continuaria sendo outra fonte e versão em relação ao overall FCM27. |
| C. Ratings oficiais EA SPORTS FC 27 | **Não usar** sem licença | Banco proprietário: proibido copiar ou redistribuir em massa, nem por scraping. |
| D. Manter a estimativa editorial identificada (estado atual) | Aplicada | Legal e transparente, mas os atributos continuam diferentes dos do EA FC. |

**Atenção ao estado atual:** segundo `CATALOG_SOURCES.md`, o próprio catálogo de produção (overall FCM27 e fotos com link para o servidor do FC Mania) depende de uma lista fornecida pelo dono da liga, cuja redistribuição os termos do FC Mania não autorizam. Isso precisa de decisão do dono do projeto. Nada foi removido sem autorização.

Este relatório é uma avaliação técnica, não um parecer jurídico.
