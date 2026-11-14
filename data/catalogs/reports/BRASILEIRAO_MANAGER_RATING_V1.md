# BRASILEIRAO_MANAGER_RATING_V1

## Estado da execução

- Registros brasileiros históricos analisados: 1.192.
- Registros com estatísticas posicionais licenciadas suficientes: 0.
- Ratings próprios gerados para produção: 0.
- Motivo: o snapshot disponível contém identidade/valores históricos, mas não minutos, aparições, gols, assistências, passes, desarmes, interceptações ou defesas de uma competição brasileira válida.

O modelo está implementado em `data/importers/brasileirao_rating_model.py`, mas retorna `None` quando os indicadores obrigatórios não estão presentes. Isso impede o preenchimento arbitrário da base.

## Indicadores exigidos

- Goleiros: idade, minutos, aparições, regularidade, defesas e taxa de gols sofridos.
- Defensores: idade, minutos, aparições, regularidade, desarmes, interceptações e duelos.
- Meio-campistas: idade, minutos, aparições, regularidade, passes, passes-chave e assistências.
- Atacantes: idade, minutos, aparições, regularidade, finalizações, gols e assistências.

## Fórmula

Os indicadores entram normalizados em 0–100. Cada posição possui pesos próprios. O overall é limitado a 1–99. O potencial é `overall + clamp((24 - idade) * 0,8, -5, +7)`, limitado a 1–99. O potencial é uma projeção interna do jogo, não um rating oficial.

O modelo só deve ser usado depois da entrada de estatísticas com licença compatível e referência de competição/data.

## Preço inicial interno

`data/importers/game_pricing.py` calcula `game_starting_value_cents` com `Decimal`, arredondamento `ROUND_HALF_UP`, qualidade (65% overall/35% potencial), idade e fator posicional. Quando existe valor externo histórico, 70% da base vem desse valor convertido com taxa configurável e 30% da qualidade; quando não existe, usa-se uma curva interna limitada. O resultado é sempre preço do jogo, nunca cotação real.
