# Modo Jogável — momentos decisivos

Data: 20/11/2026. Branch `fix/resgate-beta`. Prompt Master V3, validações 25 a 48.

## 1. O que é

A sala escolhe, ao ser criada, **como as partidas são jogadas** (regra `execution_mode`):

- **Modo Jogável** (`INTERACTIVE`, padrão das novas salas);
- **Modo Técnico** (`TECHNICAL`, a simulação 2D de antes, intacta).

No Modo Jogável, a partida avança em **simulação rápida** e para em cada **momento decisivo**:

- quando é um ataque do seu time, você joga;
- a defesa e os dois goleiros são sempre da IA;
- os ataques dos bots são jogados pela IA com a **mesma física** e exibidos como melhores momentos.

A regra vale para a sala inteira e fica congelada na temporada. Assim, funciona em todos os modos com o mesmo motor:

- Carreira, com liga, Copa do Brasil e playoffs;
- Draft;
- Draft Eliminatório;
- Último Sobrevivente;
- Pack & Play.

Não existe uma cópia do motor por modo.

## 2. Arquitetura

| Camada | Onde | Responsabilidade |
|---|---|---|
| Motor (domínio, puro) | `backend/app/domain/highlights.py` | Linha do tempo das oportunidades, cenários, física, IA de movimento, goleiro, IA de decisão e a máquina de estados `HighlightMatch` |
| Serviço | `season_service.py` | Cria as sessões no início da rodada, avança-as na tarefa da rodada, bloqueia o commit até terminarem, grava o resultado oficial no mesmo formato do motor técnico (`highlight_record`) e faz snapshot e restauração |
| API | `GET /rooms/{id}/season/interactive?revision=N`, `POST /rooms/{id}/season/interactive/actions` | Estado autoritativo (quando nada mudou, só alguns bytes) e uma ação por gesto |
| Tela | `frontend/src/features/career/interactive/` | Canvas, gesto, previsão da trajetória e reprodução dos quadros oficiais |

O resultado oficial tem exatamente as chaves do motor técnico: placar, eventos `GOAL`/`SHOT`/`SAVE`, escalações, notas, minutos e estatísticas. Por isso não precisam de nenhum caso especial:

- tabela e mata-mata, com agregado e pênaltis;
- artilharia e assistências;
- evolução dos jogadores;
- notícias e histórico.

A sessão sai da rodada no momento em que o registro é gravado, então a partida é registrada uma única vez.

## 3. Estados

```
CLOCK ──(minuto da próxima oportunidade)──▶ abre oportunidade
   humano controla ─▶ DECISION ──(gesto | tempo esgotado → IA)──▶ EXECUTING ──▶ DECISION (domínio do atacante)
                                                                        └──▶ OUTCOME (gol, defesa, perda, bola fora) ──▶ CLOCK
   bot / IA no lugar ─▶ REPLAY (todas as ações resolvidas de uma vez) ──▶ OUTCOME ──▶ CLOCK
45′ ─▶ HALF_TIME (6 s) ─▶ CLOCK ... 90′ e linha do tempo vazia ─▶ FINISHED
```

- `advance(now)` aplica cada transição no **seu próprio horário lógico**. Se ninguém consultar o servidor por um minuto, ele recupera as transições em ordem, sem pular nem duplicar.
- A ação humana e a automática do cronômetro rodam sob o mesmo lock da sala, e `advance(now)` é aplicado antes. Assim, só uma das duas vence.
- A ação traz `action_id`, `opportunity_id` e `revision`:
  - ação repetida devolve `DUPLICATE` e não é aplicada;
  - ação atrasada, de outra oportunidade ou de outro clube é recusada com 409.

## 4. Oportunidades

**Quantidade.** É sorteada por Poisson. A taxa é:

`4,2 · exp((ataque − (0,8·defesa + 0,2·goleiro)) / 18)`

A taxa é ajustada por:

- mentalidade: ofensiva 1,15, defensiva 0,85;
- entrosamento: `1 + 0,12·coesão`.

O resultado fica entre 1 e 9. Não há número fixo de oportunidades nem igualdade forçada entre os times.

**Ataque e defesa** vêm dos **atributos** dos titulares, ponderados por posição, e não só do overall:

- ataque: chute, passe, drible e velocidade;
- defesa: marcação, físico e velocidade.

**Tipos:**

- ataque trabalhado;
- contra-ataque;
- jogada pela ponta;
- linha de fundo;
- infiltração;
- cara a cara;
- no modo Tradicional, também falta perigosa e pênalti;
- escanteio, que é continuação de um lance.

O estilo tático puxa o tipo:

- contra-ataque → contra-ataques;
- jogo pelas pontas → pontas e cruzamentos;
- jogo direto → infiltrações.

**Final de jogo.** Aos 80′, quem está perdendo pode ganhar mais um ataque. A chance depende da qualidade do time, de 20% a 70%.

**Posições.** Os atacantes saem da formação, avançados. A defesa fica em bloco compacto e desarrumada no contra-ataque. Os goleiros ficam no gol. Ninguém nasce a menos de 1,3 m de outro jogador.

## 5. Física (passo de 0,1 s, determinística)

| Ação | Velocidade inicial | Alcance | Erro (desvio do ângulo, rad) |
|---|---|---|---|
| Passe | 7 + 19·força m/s, atrito 5 m/s² | v²/10 | 0,075·(1,3 − passe/100)·(1 + 0,9·pressão)·(0,7 + 0,6·força) |
| Lançamento ou cruzamento | 11 + 15·força | voo de 12 + 46·força m (±9%·(1,2 − passe/100)) | 0,06·(1,3 − passe/100)·(1 + 0,8·pressão) |
| Chute | 16 + 18·força, atrito 1,5 | até a linha | 0,042·(1,35 − chute/100)·(1 + pressão)·(0,75 + 1,6·max(0, força − 0,55)) |
| Condução | velocidade do atleta | 3 + 9·força m | desarme: 0,32 + (marcação − drible)/160 + (físico − físico)/400 |

**Pressão:** `1 − distância do marcador mais próximo / 4,5 m`.

**Interceptação.** Quando um defensor alcança a bola (a até 0,95 m), a chance de cortar é:

`0,16 + 0,42·marcação/100 − 0,015·velocidade da bola`

- Se ele falha, a bola desvia e continua.
- Uma bola no alto (acima de 1,9 m) não pode ser jogada.

**Domínio.** Atacante a até 0,9 m da bola. A chance é:

`0,99 − 0,045·max(0, v − 11)·(1,25 − drible/100)`

Se falha, a bola espirra e continua viva.

**Goleiro.** Reage à **trajetória real** depois de um tempo de reação:

`0,42 − 0,2·goleiro/100`

O tempo aumenta 0,08 s se a visão estiver bloqueada. Depois disso:

- desloca-se de 1,7 a 3,5 m/s;
- alcance de 0,7 m em pé e até 1,65 m mergulhando, quando teve tempo.

Defendeu: segura ou rebate. O rebote continua a oportunidade, e quem chegar primeiro fica com a bola. Ele nunca teleporta e nunca conhece uma ação ainda não executada.

**Proteção contra ataque infinito.**

- No máximo 8 ações. O domínio seguinte à oitava ação encerra o lance ("a defesa se reorganiza").
- A defesa reage até 0,12 s mais rápido conforme o lance se alonga.
- Uma ação dura no máximo 7 s; depois disso, quem estiver mais perto fica com a bola.

**Calibragem empírica.** 40 jogos IA × IA por formato, com os mesmos números do catálogo:

- 11×11: cerca de 0,9 gol por jogo;
- 5×5: cerca de 1,5 gol por jogo.

Ataques humanos tendem a converter mais.

## 6. Gesto

1. Pressione em qualquer ponto do campo e arraste.
2. A direção do arraste é a direção da jogada, a partir do jogador com a bola.
3. O comprimento do arraste é a força: 40% do comprimento do campo equivale a 100%.
4. Tudo é medido em coordenadas normalizadas, então o mesmo gesto tem a mesma intenção em qualquer tela.
5. No celular em pé, o campo gira e o ataque vai para cima.

**Tipo de jogada:**

- **Automático** (tecla 1): é chute se a linha aponta para o gol a menos de 32 m; é cruzamento se você está na ponta, perto da área, arrastando para dentro; senão, é passe.
- Também dá para escolher Passe (2), Lançamento (3), Conduzir (4) ou Chute (5).

A linha prevista usa as fórmulas acima e é **só uma previsão**: o erro e a defesa só acontecem no servidor.

Só uma ação é enviada, ao soltar. Esc, toque cancelado e perda do ponteiro cancelam o gesto.

## 7. Tempo, desconexão e reconexão

**Tempo de decisão.** O anfitrião escolhe 5, 10, 15 ou 20 s (padrão 10 s).

- Opcionalmente, há tempo livre contra bots.
- Quando o tempo acaba, a IA faz uma ação contextual uma vez.
- O relógio da partida não anda durante a decisão.

**Desconexão.**

- O cliente consulta o servidor a cada 0,35 s. Sem consultas por 6 s, o técnico conta como desconectado.
- A decisão aberta congela, guardando o tempo restante, e começa a tolerância de **30 s**. O adversário vê o aviso.
- Se ele volta na tolerância, a decisão é retomada com o tempo que restava (no mínimo 3 s).
- Se não volta, a IA assume aquela e as próximas oportunidades dele. Quando ele volta a consultar, retoma na próxima decisão.
- Se os dois humanos caem, cada um segue a mesma regra. A partida nunca fica presa.

**Reinício do servidor.** A sessão é um dado simples e vai no snapshot JSON (`matches[id].highlight`), junto com a rodada.

- Com `ENABLE_JSON_SNAPSHOTS`, um reinício restaura a partida no último snapshot: placar, oportunidade e decisão.
- O snapshot é gravado a cada ação aceita e em cada commit de rodada.
- Transições que aconteceram depois do último snapshot, como lances de bot ou tempo esgotado, são recalculadas pelo relógio. O resultado pode diferir só nesses trechos não gravados.
- Sem snapshots, ou com a instância recriada do zero (no Render Free o `/tmp` não é persistente entre deploys), o estado em memória se perde.

## 8. Estado por modo

Teste de fumaça: o motor e o serviço jogam a competição inteira com `execution_mode = INTERACTIVE`. Foram feitas duas execuções por modo: humanos ausentes (tolerância e depois IA) e humanos chutando a cada decisão.

| Modo | Jogar | Bot | Multiplayer | Finalizar | Avançar | Testado |
|---|---|---|---|---|---|---|
| Carreira (liga + playoffs, 8 clubes) | sim | sim | sim (servidor) | sim | sim, campeão | fumaça do serviço |
| Draft Eliminatório (8) | sim | sim | sim (servidor) | sim | sim, campeão | fumaça do serviço |
| Pack & Play (4) | sim | sim | sim (servidor) | sim | sim, campeão | fumaça do serviço |
| Último Sobrevivente (8) | sim | sim | sim (servidor) | sim | sim, campeão | fumaça do serviço |
| Draft (liga) | o mesmo fluxo da Carreira | — | — | — | — | não executado separadamente |
| Copa do Brasil (20 clubes) | o mesmo fluxo de mata-mata | — | — | — | — | não executado separadamente |

**Não executado nesta entrega** (o proprietário pediu deploy sem validação adicional):

- pytest completo;
- testes de navegador, de dois navegadores e mobile;
- capturas.

O "multiplayer" da tabela significa que o servidor suporta os dois humanos na mesma partida. Isso não foi verificado com dois navegadores reais.
