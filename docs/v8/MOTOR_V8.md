# Football V8: motor integrado, contrato tático e apresentação

A V8 é o perfil `v8` do pacote `app/domain/football` da V7. É um único motor: a V7 continua reproduzível pelo perfil `v7`, só para comparação.

```
Football Core (servidor, autoritativo)
  world.py   física da bola (rolagem, voo, quique, efeito Magnus) · locomoção · corpos
  keeper.py  goleiro-agente (posição, reação, passo, salto, mergulho, contato por varredura)
  brain.py   IA coletiva (papéis + contrato tático)
  choice.py  decisões com a bola (utility AI)
  play.py    uma ação: preparação → contato → bola livre → domínio → assentamento
  ↓ quadros oficiais (posição, orientação, estado) + cues (KICK, CONTROL, SAVE, DIVE, THROW…)
Shared Match State (HighlightMatch.view)
  ↓
presentation.ts → avatar3d.ts (3D) · sprites2d.ts (2D)
                  ↑ football/athlete · football/anim · football/sprites (biblioteca comum)
```

## 1. Seleção

| Onde | Motor |
|---|---|
| Lab (`#lab`) | V8 por padrão; V7 e V6 selecionáveis |
| Partidas (`GAMEPLAY_ENGINE`) | Padrão `v6` até a aprovação; `v8` liga a V8 |
| Snapshots | Cada partida termina com o motor em que começou |

## 2. Contrato tático (consumido pelo motor)

`HighlightMatch._tactics()` monta o contrato por oportunidade a partir **do que o jogo já tem**: as táticas salvas, a formação, as instruções individuais e o entrosamento. Não é um sistema tático novo. A futura Football Tactical Engine pode preencher as mesmas chaves.

| Chave | Origem | Efeito na V8 |
|---|---|---|
| `style` | Estilo do atacante | Risco aceito no passe (posse < contra-ataque/direto); bônus de passe em profundidade (direto/contra); amplitude e cruzamentos (pelas pontas) |
| `att_mentality` | Mentalidade do atacante | Quanto o bloco avança com a bola; disposição para chutar |
| `def_mentality` | Mentalidade do defensor | Altura e compactação do bloco |
| `def_pressure` | Pressão do defensor | ALTA: linha alta e dois pressionadores; BAIXA: bloco baixo perto da área |
| `roles` | Formação (`slot_role`) | GK, CB, FB, MF ou ST de cada atleta |
| `instructions` | Instruções individuais | Ver abaixo |
| `att_cohesion` / `def_cohesion` | Entrosamento | A defesa entrosada relê a jogada um pouco antes, até 0,05 s |

**Instruções individuais com comportamento próprio:**

| Posição | Instrução | Comportamento |
|---|---|---|
| Lateral | Avançar frequentemente | **Ultrapassagem** por fora do portador quando ele está aberto do mesmo lado |
| Lateral | Apoiar o ataque | Apoio por fora (ultrapassa no estilo pelas pontas) |
| Lateral | Ficar na defesa | Segura a posição |
| Centroavante | Pivô | Vem buscar de costas quando a bola está longe |
| Centroavante | Falso 9 | Recua entre as linhas |
| Centroavante | Atacar profundidade | Sempre no ombro do último defensor |
| Meia | Proteger a defesa | Segurança atrás da bola; na defesa, protege a frente da área |
| Meia | Chegar à área | Infiltra na área no terço final |
| Zagueiro | Cobertura | Último homem, mais fundo que a linha |

**Combinações:**

- **Tabela:** quem passa continua correndo, e o bot valoriza o companheiro que já corre para o espaço.
- **Terceiro homem:** enquanto um passe viaja, um terceiro jogador ataca o espaço além do receptor, só se esse espaço existir.
- **Ultrapassagem:** feita pela instrução do lateral.
- **Pivô:** feito pela instrução do centroavante.
- **Infiltração:** corrida às costas da linha e passe em profundidade.
- **Cruzamento:** atacantes ocupam primeiro pau, segundo pau e marca do pênalti; mais dois atacam a zona de queda prevista.

Nenhuma combinação é roteirizada: todas reagem ao estado real e podem não acontecer.

**Defesa:**

- **um** pressionador, que acompanha sem se jogar;
- cobertura;
- marcadores goleiro-lado;
- linha comum;
- **sombra de cobertura** (meias livres fecham a linha de passe para o atacante mais perigoso);
- bloco baixo ou linha alta pela pressão.

**Testes** (`test_football_v8.py`):

- a instrução do lateral muda a corrida (ultrapassar > ficar, em mais de 5 m);
- a pressão alta afasta a linha da própria área em mais de 3 m em relação à pressão baixa.

## 3. Física e mecânicas V8

**Goleiro.**

- No mergulho, as mãos partem da altura do peito e só chegam à bola baixa quando o corpo cai: 0,34 s para baixo, 0,18 s a meia altura, 0,14 s no alto.
- Em pé, a bola rasteira é coberta pelas pernas, com 0,45 + 0,15·goleiro m para cada lado, e não pelos braços.
- Ele continua sem defender bola fora do alcance (teste).

**Chute.**

- O bot mira o ponto do gol que os corpos dos bloqueadores e o alcance do goleiro deixam mais livre.
- **Chute colocado com curva:** um chute de força média perto da trave sai com efeito lateral e volta para o alvo. O coeficiente de Magnus é 0,0036, e a curva é de 1 a 2 m em 20 m. A mira mostrada continua terminando no ponto mirado.

**Cruzamento.**

- O lance passa a ser uma **disputa aérea** entre todos que alcançam a bola, e não "o primeiro corpo sob a bola".
- A disputa pesa posição, impulsão e físico.
- O bot só cruza se houver uma disputa possível de ganhar.

**Condução do bot perto do gol.** O valor da condução é a chance de manter a bola × a chance criada (xG no destino).

**Bola parada.** A barreira (os 4 defensores mais próximos da linha bola–gol) segura a posição até o chute.

**Reposição.** Depois de encaixar, o goleiro rola a bola para o companheiro livre mais próximo. Isso é apresentação: o resultado da ação já está decidido.

## 4. Apresentação

**3D** (`avatar3d.ts`):

- o atleta humano da pesquisa (21 ossos, uniforme oficial com número, pele, cabelo e chuteira por atleta);
- locomoção `matched+ik` (SPRINT.md);
- clipes de ação com o **quadro de contato alinhado ao cue do servidor** (passe curto ou longo, cruzamento, chute, chute de primeira, domínio, cabeceio, desarme em pé ou carrinho);
- goleiro com mergulho baixo ou alto espelhado para o lado real, deitado no chão, levantando, encaixe, salto e reposição;
- na decisão, o corpo congela no meio da passada.

Os estilos V6 continuam disponíveis com `localStorage bm_3d_style=human|voxel`.

**2D** (`sprites2d.ts`):

- sprites **gerados do mesmo atleta 3D**: 8 direções, corrida, sprint, condução, passe, chute, domínio, cabeceio, comemoração, goleiro pronto e mergulho;
- um atlas-máscara pré-gerado por padrão de camisa (`frontend/public/sprites`, `scripts/bake-sprites.cjs`), recolorido por time;
- duas aparências por time mais o goleiro (no máximo 6 folhas, cerca de 70 MB);
- o quadro da corrida avança pela distância oficial.

Sem WebGL, ou com `bm_2d_style=vector`, os sprites vetoriais da V6 desenham.

**Lab:**

- seletor de motor V8/V7/V6, dificuldade, treinos e partida completa;
- "Diagnóstico": FPS, CPU por quadro, deslize dos pés e revisão; só no Lab, nunca nas partidas públicas;
- link para o laboratório de animação, goleiro, sprites, física e IA (`football-lab.html`).
