# Pesquisa de repositórios

Situação em 21/11/2026, sem uma auditoria exaustiva.

## Adotados

| Recurso | Uso |
|---|---|
| Three.js (MIT) | `SkinnedMesh`, `Skeleton`, `Bone` e `BufferGeometryUtils.mergeGeometries` |
| Playwright (Apache-2.0) | Capturas e vídeos de evidência, rodando no Chrome do sistema |
| Vitest e Pytest | Testes |

## Considerados como referência conceitual, sem importar código

- **Steering behaviors** (Reynolds): separation, arrive, pursuit e cobertura. Implementados à mão em `highlights.py`, nas funções `_spread`, `_intercept` e no papel de cover.
- **Google Research Football, RoboCup, Yuka**: motores completos. Não fazem sentido como dependência, porque o motor autoritativo já existe.

## A verificar na próxima etapa

Licença, manutenção e utilidade de cada um:

- Striker 3D;
- GoalDao;
- WebSoccer;
- Quaternius;
- Poly Pizza;
- Kenney Sports Pack;
- glTF-Transform;
- meshoptimizer;
- KTX-Software;
- three-mesh-bvh;
- PixiJS;
- Phaser.

Nenhum desses foi instalado.
