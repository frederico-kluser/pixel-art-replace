# pixel-art-replace

Substitui o look de sprites/pixel art com IA — do upload à aprovação — sem partir a grelha.

![estado](https://img.shields.io/badge/status-ativo-green) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![react](https://img.shields.io/badge/interface-React%20%2B%20Tailwind%20%2B%20shadcn-61dafb)

## Como rodar (ver a interface)

A interface é uma **app React** (`web/`, com Tailwind + shadcn + Motion) servida pelo backend Python.
Copie os blocos **na íntegra** — funcionam a partir da raiz do projeto.

```bash
# 1) dependências (uma vez): backend + comando global `par`
pip install -r requirements.txt
pip install -e .          # passa a poder correr `par` de QUALQUER pasta

# 2) construir a interface (uma vez; ou após mudanças em web/)
cd web && npm install && npm run build && cd ..

# 3) subir o studio com a folha de exemplo
par studio examples/folha-teste.png --out trabalho --mudanca "um look novo de samurai"
```

Abra **<http://127.0.0.1:8770/>** no navegador: o fluxo guiado é
**1 Imagem → 2 Look → 3 Prova → 4 Lote → 5 Resultado**.

Sem `pip install -e .`, o equivalente é `python -m par studio …` **a partir da raiz do projeto**.

**Modo desenvolvimento** (hot reload): mantenha o backend a correr (passo 3) e, noutro terminal:

```bash
cd web && npm run dev     # → http://127.0.0.1:5173/ (faz proxy da API para a porta 8770)
```

> A chave da OpenRouter lê-se de `OPENROUTER_API_KEY` ou `~/.dsh/.credentials.yaml` (nunca é pedida
> se já existir; nunca vai para o git). Sem chave, `--sem-ia` faz a análise só com o algoritmo.

## O que faz

```
enviar UMA sprite ou uma TILESHEET
   │
   ├─ sprite única ──► expande para a resolução das ferramentas de geração (≈1024 px)
   │                   → manda junto com a IMAGEM DE REFERÊNCIA → mostra o resultado
   │
   └─ tilesheet ─────► RECORTA as sprites (grelha detetada)
                       → o utilizador ESCOLHE as que quer (a primeira = sprite de prova)
                       → a prova é expandida + referência → REPLACE de prova
                       → aprovado (com considerações na retentativa, se rejeitar)
                       → TODAS as escolhidas são ajustadas AUTOMATICAMENTE,
                         em paralelo (máx. 32), e cada uma volta à paleta original
```

- **Análise**: o **MiMo v2.6 Pro** (`xiaomi/mimo-v2.6-pro` via OpenRouter) classifica a imagem
  (sprite vs tilesheet, colunas/linhas estimadas) + deteção algorítmica de grelha para os recortes exatos.
- **Geração**: melhor modelo de imagem do OpenRouter (`google/gemini-3-pro-image`, fallbacks automáticos).
- **Regresso à pixel art**: voto maioritário por bloco + snap à paleta original (as cores únicas da arte).
- Estado persistido em `studio.json`; erros no formato `Erro: … — Solução: …`.

## Uso também por linha de comandos

```bash
# análise rápida (e recorte, com --out)
par analisar folha.png --out recortes/

# expandir uma sprite para a resolução das ferramentas de geração
par expandir sprite.png --out sprite-grande.png

# studio completo (mesmo do passo 3 acima)
par studio folha.png --out trabalho --mudanca "novo traje"
```

(`python -m par …` também funciona, a partir da raiz do projeto.)

## Estrutura

```
par/analise.py     análise: sprite vs tilesheet (MiMo + grelha), recorte, montagem
par/openrouter.py  cliente OpenRouter: analisar_ia + gerar_imagem (com fallbacks e backoff)
par/imagem.py      expansão (nearest ≈1024), requantização (voto de bloco), comparação
par/studio.py      servidor localhost + fluxo completo + serve web/dist
par/cli.py         python -m par analisar|expandir|studio
web/               interface React (Tailwind + shadcn + Motion) — ver "Como rodar"
tests/             testes offline (o OpenRouter é stubado)
examples/          folha de exemplo para experimentar
```

## Desenvolvimento

```bash
python -m unittest discover -s tests       # backend (offline)
cd web && npm run build                    # interface (tsc + vite)
```

Requisitos: Python 3.10+, Pillow, numpy · Node 18+ (só para a interface).
