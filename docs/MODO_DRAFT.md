# Modo Draft

Código: `backend/app/domain/draft.py` (regras) e `backend/app/services/draft_service.py` (autoridade por sala). Testes: `backend/app/tests/test_draft.py`, que cobre os itens do §31.

## Fluxo

1. O anfitrião cria a sala com `game_mode = DRAFT` e escolhe:
   - o catálogo, `draft_catalog`: `BRASILEIRAO` ou `WORLD`;
   - o overall mínimo, `draft_min_overall`: 0, 65, 70, 72, 75, 78 ou 80.

   Configuração inviável recebe HTTP 422, com o maior mínimo viável sugerido.
2. Cada técnico escolhe um clube. O anfitrião inicia, e a sala entra na fase `DRAFT` (o mercado inicial é pulado). Os bots montam os times na hora, usando as mesmas ofertas.
3. O técnico escolhe a formação (`PUT /draft/formation`). Ela fica fixa a partir da primeira escolha.
4. Ao abrir uma posição (`POST /draft/offer {slot_id}`), aparecem **exatamente três cartas** de atletas compatíveis (posição principal ou secundária). Pedir de novo devolve as mesmas três cartas: não existe re-sorteio.
5. A escolha (`POST /draft/pick {slot_id, catalog_id}`) só vale para uma das três cartas, e uma escolha confirmada não muda.
6. Depois dos titulares, vêm as **reservas livres** (`bench-1` … `bench-5` no 11×11; `bench-1` … `bench-3` no 5×5). As cartas podem ser de qualquer posição. A interface avisa quando faltar goleiro reserva ou quando todos os reservas forem da mesma posição.
7. O Draft termina:
   - quando o último técnico completa o time;
   - no prazo (o tempo de preparação da sala);
   - ou quando o anfitrião força (`POST /draft/complete`).

   Quem não terminou recebe escolhas automáticas.
8. As instâncias viram o elenco do clube. A formação montada vira a escalação salva, e o campeonato começa (fase `SQUAD_MANAGEMENT`).

## Atletas repetíveis e instâncias

- Cada escolha cria `DFT-<clube>-<nº>-<id do catálogo>`, com cópia dos dados do catálogo em `source_ids.catalog_id` e `source_ids.draft_owner`.
- Dois técnicos podem ter o mesmo atleta, e cada cópia evolui, joga e é avaliada separadamente.
- No mesmo elenco, o atleta aparece no máximo uma vez. Uma oferta nunca repete atleta.
- O resto da carreira (motor, progressão, entrosamento, estatísticas) recebe as instâncias como atletas normais, sem nenhuma regra especial. As regras do modo Tradicional não mudam.
- Empréstimos não existem no Draft.

## Sorteio equilibrado

- Os atletas elegíveis da posição são ordenados por overall e divididos em três faixas: o terço superior, o do meio e o inferior.
- Cada oferta traz uma carta de cada faixa, sorteada com semente `crc32(sala:clube:posição:nº da escolha)`.
- Resultado: todo técnico vê uma carta da faixa superior em **toda** oferta, e o overall exato continua variando.
- Se uma faixa se esgota, a faixa vizinha completa a oferta, e a oferta guarda uma nota explicando.
- Se faltam atletas na posição, entram posições vizinhas (DF↔MF↔ST), nunca um jogador de linha no gol. Também fica uma nota.

**Medição** (`test_balanced_draw_gives_every_manager_comparable_chances`): com 20 técnicos e 11 ofertas cada, a média da melhor carta por técnico varia no máximo 3,5 pontos entre eles, e todas ficam acima da média do catálogo.

## Bots

| Dificuldade | Como escolhe |
|---|---|
| Casual | Metade das vezes, uma carta aleatória. |
| Competitivo | A carta de maior overall, e garante goleiro reserva. |
| Lendário | Também pesa potencial e atributos conhecidos. |

Nenhum bot recebe ofertas diferentes das que um humano receberia.
