# Performance Lab: resultados medidos

## Ambiente

Tudo foi medido no navegador, sem nenhuma estimativa. Os dados brutos estão em `data/performance-vsync.json` e `data/performance-uncapped.json`.

- **GPU:** Intel UHD do Raptor Lake-S (iGPU), driver Mesa, via `ANGLE (Intel, Mesa Intel(R) Graphics (RPL-S), OpenGL ES 3.2)`. A máquina também tem uma RTX 3050 Laptop, mas o offload PRIME travou o Chrome headless, então **nenhum número abaixo usa a placa NVIDIA**.
- **Navegador:** Chrome 152 headless, com Playwright e `--use-angle=gl`. O canvas tinha 940×715 e o DPR era 1.
- **CPU:** 16 threads. Linux 7.0.
- **Cena:** gramado, sol com sombra PCF de 2048², 22 atletas andando em círculos, cada um com um `AnimationMixer` próprio e três clipes misturados (corrida, sprint e idle). A câmera tem visão de TV.
- **Método:** 0,8 s de aquecimento e depois 3 s de medição por configuração. O FPS vem do intervalo entre `requestAnimationFrame`. O "uncapped" usa `--disable-gpu-vsync --disable-frame-rate-limit`.

## Resultados (sem vsync)

| Atletas | Detalhe | Sombra | LOD | Animação | FPS | ms (p95) | Draw calls | Triângulos | CPU de animação (ms por quadro) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | médio | sim | — | mixer | 299 | 3,3 (6,5) | 2 | 5,6 mil | 0,03 |
| 5 | médio | sim | — | mixer | 283 | 3,5 (6,8) | 6 | 28 mil | 0,07 |
| 10 | médio | sim | — | mixer | 259 | 3,9 (7,5) | 11 | 56 mil | 0,24 |
| 22 | médio | sim | — | mixer | 218 | 4,6 (9,0) | 23 | 121 mil | 0,46 |
| 22 | baixo | sim | — | mixer | 244 | 4,1 (8,2) | 23 | 69 mil | 0,40 |
| 22 | alto | sim | — | mixer | 183 | 5,5 (10,5) | 23 | 233 mil | 0,36 |
| 22 | alto | **não** | — | mixer | 272 | 3,7 (7,1) | 23 | 233 mil | 0,35 |
| 22 | alto | sim | **sim** (baixo além de 25 m) | mixer | 237 | 4,2 (8,1) | 23 | 69 mil | 0,37 |
| 22 | médio | sim | — | amostrador de poses | 213 | 4,7 (8,8) | 23 | 121 mil | 0,45 |

Com vsync, todas as configurações ficaram travadas em 60 fps, com p95 de 16,8–16,9 ms e 180 de 180 quadros.

## Assets (medidos com `GLTFExporter`)

| Nível | Triângulos (atleta da semente 11) | GLB |
|---|---|---|
| Baixo | 3.172 | 172 KB |
| Médio | 5.612 | 968 KB **com os 30 clipes assados** |
| Alto | 10.814 | 499 KB |

- Os clipes a 30 fps sem compressão são a maior parte do GLB médio (cerca de 800 KB). Recomendações: amostrar a 15 fps, quantizar os quatérnios e usar `gltf-transform resample` + `meshopt` (redução esperada de 5 a 10×, **ainda não medida**).
- A carga de 22 atletas (geometria compartilhada mais compilação de shader) levou de 10 a 51 ms.
- O atlas de sprites tem 1920×2400, ocupa 17,6 MB em RGBA na GPU e leva cerca de 2,8 s para gerar (SPRITES.md).

## Leitura

- **O custo de animação não é problema.** São menos de 0,5 ms por quadro para 22 esqueletos de 21 ossos, tanto com o `AnimationMixer` quanto com o amostrador de poses.
- **As sombras são o item mais caro:** cerca de 1,8 ms em 22 atletas de detalhe alto. O LOD recupera cerca de 1,3 ms e corta 70% dos triângulos.
- **Recomendação para celular:** detalhe médio perto da câmera, baixo além de 25 m, sombra num único mapa de 1024², DPR no máximo 1,5. **É preciso medir num aparelho real**: a medição em celular não foi feita.
- "Draw calls" vem de `renderer.info` da última renderização: 22 atletas mais o gramado. O passe de sombra **não** aparece nesse contador.
- O uso de heap do JS (14–34 MB) oscilou com a coleta de lixo. Não serve para comparar configurações.
- O DPR do headless era 1, então a comparação entre DPR 1 e DPR 2 **não foi feita**. Ela fica disponível na aba, em modo interativo.
