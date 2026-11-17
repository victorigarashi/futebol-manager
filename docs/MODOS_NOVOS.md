# Modos novos — Brasileirão Manager

Os três modos abaixo são edições isoladas: o servidor é a autoridade, os
resultados são determinísticos a partir da semente da sala e nenhum elenco,
moeda ou prêmio passa para uma Carreira.

## Draft Eliminatório

- Aceita 4, 8 ou 16 clubes.
- Cada técnico forma o elenco pelo Draft; a chave é então montada por força,
  colocando a metade mais forte contra a metade mais fraca.
- O sorteio de cada fase usa `crc32(room:tournament:stage)`. Ele é gravado no
  estado da sala: recarregar a página nunca gera outra chave.
- Todos os confrontos são de jogo único. Empate no tempo normal vai para os
  pênaltis.
- Não há premiação, mercado ou nova temporada nesta edição.

## Último Sobrevivente

- Aceita 8, 12, 16 ou 20 clubes e usa os elencos operacionais dos clubes
  escolhidos (16 atletas, incluindo dois goleiros por clube quando o catálogo
  exigir essa composição).
- Após cada rodada, a ordem é: pontos da rodada, saldo de gols, gols marcados,
  campanha acumulada (pontos, saldo, gols) e, se persistir o empate, uma ordem
  fixa obtida por `crc32(seed:club)`.
- As eliminações são sempre pares: automáticas em aproximadamente 25% do campo,
  ou 2/4 conforme a regra escolhida pela sala. O caminho exibido na tela mostra
  exatamente a sequência calculada pelo servidor.
- A final é jogo único com pênaltis se necessário. Um clube eliminado vira
  espectador: continua vendo a tabela e a decisão, mas não recebe ações de
  prontidão.

## Pack & Play

- Aceita 4, 8 ou 16 clubes. Todos os pacotes são gratuitos: não existe compra,
  moeda ou item pago.
- As faixas do catálogo são Ouro, Prata e Bronze, distribuídas por overall em
  15%, 35% e 50%, respectivamente.
- Na opção **Equilibrada**, todos os técnicos recebem a mesma mistura. Em
  **Sorte**, os sorteios são independentes, preservando as mesmas probabilidades.
- No 11×11 são quatro pacotes de seis cartas e a composição garantida é 3 GK,
  8 DF, 7 MF, 5 ST e uma carta livre. No 5×5 são três pacotes de quatro cartas:
  2 GK, 4 DF, 3 MF, 2 ST e uma livre.
- Não há repetição dentro da coleção de um técnico. Repetições entre técnicos
  são permitidas e recebem instâncias próprias com prefixo `PCK-`.
- Depois da montagem, a edição segue para torneio em jogo único, com pênaltis.
  As cartas nunca entram na Carreira.

## Transparência

O modo usa apenas o catálogo operacional instalado no servidor. Informações de
origem e o status editorial de cada atleta permanecem no catálogo; os modos não
declaram ratings editoriais como ratings oficiais de terceiros.
