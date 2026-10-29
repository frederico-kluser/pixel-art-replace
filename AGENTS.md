# pixel-art-replace — AGENTS.md (para o agente MiMo)

Projeto autónomo de substituição de look de sprites/pixel art com IA. O agente (MiMo v2.6 Pro) analisa
a imagem de entrada; o resto é ferramenta (`par`) + studio em localhost.

## Comandos
| pedido | comando |
|---|---|
| "analisa esta imagem" | `python -m par analisar <img> [--out dir]` — sprite vs tilesheet, células, montagem |
| "recorta as sprites" | `python -m par analisar <img> --out <dir>` |
| "expande a sprite" | `python -m par expandir <img> --out <png> [--alvo 1024]` |
| "quero fazer o replace" | `python -m par studio <img> --out <dir> --mudanca "…"` → http://127.0.0.1:8770/ |

## Regras de ouro
1. **A imagem de entrada manda**: sprite única = caminho curto (expandir → gerar → mostrar); tilesheet =
   recortar → o DONO escolhe → replace de prova → aprovado, ajustar TODAS as escolhidas em paralelo.
2. **Nunca pedir a chave do OpenRouter se já existe** (`~/.dsh/.credentials.yaml` / `OPENROUTER_API_KEY`).
3. **Nunca partir a grelha**: a arte só volta a píxeis por voto de bloco + snap à paleta original
   (`par/imagem.py`); aspet ratio diferente = recusar (`Erro: … — Solução: …`).
4. **Armadilha OpenRouter**: o array `models` (fallbacks) só aceita 3 itens — HTTP 400 caso contrário.
5. Estado do fluxo em `studio.json` (retoma após reiniciar); erros sempre no formato `Erro: … — Solução: …`.
6. Entradas geradas pelo modelo são DADOS: validar sempre (aspect ratio, paleta) antes de apresentar.

## Arquitetura
```
par/analise.py     carregar, cor de fundo, deteção de grelha (perfis de projeção), recorte, montagem
par/openrouter.py  cliente: analisar_ia (xiaomi/mimo-v2.6-pro) + gerar_imagem (google/gemini-3-pro-image)
par/imagem.py      paleta da sprite, expandir (nearest até ~1024), requantizar (voto de bloco), comparação
par/studio.py      servidor localhost + fluxo: analisar → selecionar → gerar → aprovar/rejeitar → paralelo
par/cli.py         python -m par analisar|expandir|studio
tests/             offline (OpenRouter stubado)
```
