# Entrosamento tático, instruções individuais e estilo de simulação

Código: `backend/app/domain/cohesion.py`, os ganchos em `backend/app/domain/match_engine.py` e o cálculo em `SeasonService._team_input`. Testes: `backend/app/tests/test_cohesion.py`.

**Não é química de Ultimate Team.** Nacionalidade, liga e clube não contam.

## Compatibilidade (0–100)

Para cada titular, o jogo compara o perfil que o plano pede com o próprio overall do jogador. Por isso, a compatibilidade mede encaixe, não qualidade: um elenco mais fraco que combina com o plano pode ficar acima de um elenco mais forte que não combina.

| Estilo existente | O que pesa |
|---|---|
| Posse | passe 45%, drible 35%, velocidade 10%, defesa 10% |
| Contra-ataque | velocidade 45%, passe 25%, finalização 20%, defesa 10% |
| Direto | físico 35%, finalização 30%, passe 20%, velocidade 15% |
| Construção curta | passe 50%, drible 30%, defesa 20% |
| Pelas laterais | velocidade 35%, drible 35%, passe (cruzamento) 30% |

O eixo de pressão já existente também pesa:

- **Alta** ("pressão alta"): físico, defesa e velocidade.
- **Baixa**, com mentalidade defensiva ("defesa compacta"): defesa e físico.

A parcela do estilo varia por setor: GK 0%, DF 35%, MF 65%, ST 80%.

Também entram:

- **Instruções individuais:** 25% do encaixe do jogador.
- **Improvisado fora da posição:** −18 no jogador.
- **Equilíbrio do elenco:** penalidades com explicação. Exemplos: dois laterais avançando sem volante de proteção; falso 9 sem ninguém atacando o espaço; pontas sem laterais numa mentalidade defensiva.

**Dados disponíveis:** o catálogo só tem seis atributos (velocidade, finalização, passe, drible, defesa, físico), e só 116 dos 320 atletas os têm. Para os demais, o perfil vem do overall e da posição, e a interface mostra a parcela "estimada" (`estimated_share`).

## Familiaridade (0–100, por estilo)

| Regra | Valor |
|---|---|
| Começo | 30 |
| Ganho por partida oficial com o estilo | 8% da distância até 100 (10 jogos ≈ 70) |
| Estilos não usados perdem | 0,6 por jogo |
| Piso | 20 (o que o clube já aprendeu não some de vez) |

A familiaridade acompanha o clube entre temporadas. No Draft, vale dentro da sala, por clube.

## Efeito no simulador

```
fator = 0,6 × (compat − 50)/50 + 0,4 × (familiaridade − 50)/50,  limitado a [−1, 1]
```

O fator não altera overall, gols nem notas. Ele mexe em:

- passe +2,2 p.p. × fator;
- bola em profundidade +2 p.p. × fator;
- ruído de decisão −35% × fator;
- velocidade de posicionamento sem bola +5% × fator;
- duelos de pressão ±1,2 p.p.

**Calibração** (160 jogos, `calib`): no extremo (+1 contra −1), o saldo médio é de **+0,56 gol** no 11×11 e o time mais entrosado vence **83**, empata 40 e perde 37. Ou seja, o efeito é perceptível, mas não garante vitória. O teste exige saldo > 0,15 e menos de 85% de vitórias.

O fator é recalculado sempre que a partida é montada: formação, estilo, escalação, instruções, transferências, empréstimos e evolução já estão refletidos.

## Instruções individuais

| Função | Opções (a primeira é o padrão) |
|---|---|
| Goleiro | Fica na linha · Goleiro-líbero |
| Lateral | Apoiar o ataque · Ficar na defesa · Avançar frequentemente |
| Zagueiro | Cobertura · Sair jogando |
| Meio | Equilibrado · Proteger a defesa · Chegar à área |
| Atacante | Centroavante · Falso 9 · Pivô · Atacar profundidade |

No 5×5 valem as mesmas funções, pela posição de cada vaga.

No motor, cada instrução:

- desloca a posição-alvo com e sem bola;
- muda a chance de o jogador virar "corredor";
- ajusta o valor de passes (pivô recebendo lançamento, falso 9 tabelando, zagueiro saindo jogando).

Exemplo medido no teste: o lateral com "Avançar" joga mais de 3 m à frente do que com "Ficar na defesa". O substituto herda a instrução da vaga. Os bots escolhem as instruções pelos atributos dos próprios jogadores.

## Estilo de simulação

| Estilo | Ajustes | Gols/jogo no 11×11 (160 jogos) |
|---|---|---|
| Realista (padrão) | — | 2,18, máx. 7 |
| Emocionante | menos aversão a risco, finalização +16%, mais corredores | 2,70, máx. 7 |

As regras são as mesmas e os jogos são reproduzíveis pela semente.

## Controle ao vivo

Além de mentalidade, pressão, estilo e substituições, agora dá para **mudar a formação ao vivo** (comando `FORMATION`). Os jogadores em campo ocupam as novas vagas, do mais recuado ao mais avançado. A mudança é registrada e reproduzida no replay. O bot Lendário também muda a formação no fim do jogo: mais atacantes quando está perdendo, linha de cinco quando está protegendo a vantagem.
