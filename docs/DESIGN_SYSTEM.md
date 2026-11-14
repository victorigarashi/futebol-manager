# Design system da beta

A implementação mantém os componentes, o canvas 2D e os escudos locais existentes. A camada de acabamento fica em `frontend/src/styles/beta.css`, importada no início de `frontend/src/index.css`. Seletores prefixados com `html` superam o CSS recuperado sem apagar layouts funcionais; estados e layout específicos de temporada ficam em `features/season/season-beta.css`.

## Identidade

Futebol entre amigos, competição e gestão esportiva: superfícies azul-escuras, destaque verde, escudos e placares em primeiro plano. Títulos moderados e densidade legível substituem o uso de Impact e heróis de tela inteira. Não há fontes remotas, imagens geradas de jogadores ou novas dependências de serviços.

## Tokens centrais

| Token | Valor / função |
| --- | --- |
| `--bg` / `--ink` | `#0D1117`, fundo |
| `--surface` | `#161C24`, cards |
| `--surface-raised` | `#1D2630`, controles e superfícies elevadas |
| `--line` | `#2B3440`, bordas |
| `--primary` | `#26B47D`, ação e seleção |
| `--highlight` / `--lime` | `#90FCA3`, destaque legível |
| `--paper` | `#F1F5F9`, texto principal |
| `--muted` | `#94A3B8`, texto secundário |
| `--danger`, `--warning`, `--away` | estados semânticos |
| `--pitch`, `--pitch-stripe`, `--pitch-line` | campo tático e transmissão |
| `--font-body`, `--font-heading`, `--font-numbers` | fontes locais do sistema |
| `--space-*`, `--radius-*`, `--shadow-*` | escala de espaçamento, cantos e elevação |

As cores de seleção, erro e aviso são tokens semânticos. Novos estilos não devem definir cores independentes nos componentes. O arquivo legado ainda contém declarações recuperadas; a camada beta centraliza a apresentação efetiva dessas superfícies.

## Componentes e padrões

- Botões e campos com área mínima de toque de 44 px, contraste consistente e foco visível em teclado.
- Modais limitados à altura disponível de `100dvh`, rolagem interna, fundo escurecido e tipografia legível. Gestão de foco/Escape pertence ao componente `Modal` compartilhado.
- Cards de clubes e atletas com títulos legíveis, hierarquia de orçamento/overall e botões com estados claros.
- Review com escudo, informações reais da contratação e retrato abstrato de iniciais/posição quando não há fotografia autorizada.
- Prancheta esportiva preservada e lista acessível de seleção de titulares como alternativa ao campo visual.
- Skeletons estáticos, estados vazios e erros consistentes; nenhuma animação de carregamento obrigatória.
- Tabelas em contêineres de rolagem próprios, sem mascarar overflow do documento com `overflow-x: hidden`.
- Barra de liga com conexão descrita por texto, código copiável, etapas e retorno às ligas.
- Histórico de carreira com resumo esportivo e lançamentos provenientes do servidor.

## Responsividade e acessibilidade

A folha contém ajustes de composição para 1100, 900 e 640 px, cobrindo os tamanhos de celular, tablet e desktop solicitados. Grids usam `minmax(0, 1fr)` e componentes flexíveis para impedir largura mínima oculta. Textos de conteúdo geralmente ficam entre 13 e 16 px; rótulos auxiliares são limitados a 10–12 px com contraste suficiente. Os títulos principais ficam entre 30 e 48 px, conforme a tela.

`prefers-reduced-motion` remove transições/animações e rolagem suave. Estados não dependem somente de cor: os componentes exibem textos de conexão, seleção, improvisação, posição e erro.

## Evidência e limites

O build TypeScript/Vite foi executado após a inclusão da camada e passou. Isso comprova integração e processamento da folha; não substitui inspeção visual. A verificação automatizada em navegador e os screenshots finais são registrados pelo fluxo de QA na documentação de entrega. Não foi declarada aprovação visual apenas com base no CSS.


Consolidação: a execução final de integração e navegador está registrada em `BETA_DELIVERY_REPORT.md`, que deve ser usada para os resultados finais desta entrega.
