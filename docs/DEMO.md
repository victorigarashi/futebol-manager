# Demonstração isolada

O catálogo autorizado real continua ausente. O demo permite testar o ciclo completo com atletas e valores **sintéticos**, explicitamente identificados por nomes `DEMO ...` ou genéricos identificados gerados pelo motor. Não representa licenciamento de atletas reais.

Ativação local:

```sh
APP_ENVIRONMENT=development ENABLE_DEMO_CATALOG=true docker compose up --build
```

Regras verificadas por testes:

- `ENABLE_DEMO_CATALOG` desligado por padrão.
- Permitido apenas em `development`/`test`; produção recusa inicialização com demo.
- Snapshot separado, inclusive rejeição de catálogo incompatível ao restaurar.
- Os dois modos suportam 20 clubes, mercado, formação, temporada, playoffs e carreira.
- Nenhum scraping, fotografia inventada de jogador real ou API paga foi adicionado.

`backend/tools/beta_acceptance.py` e `live_acceptance.py` são servidores **de aceitação**, não o servidor normal. Preparam estados reproduzíveis usando os motores reais, com identidades locais, para os scripts de navegador. Use `app.main:app` para jogar. Nunca publique `tools.*` como entrada de produção.

Dados reais ainda necessários: catálogo autorizado com IDs estáveis, posições, atributos, idade, valores, origem e versão, conforme `data/catalogs/players.schema.example.json`. Fotos só devem ser adicionadas com autorização/licença e tratamento de fallback; não fazem parte desta entrega.
