# pixel-art-replace

Substitui o look de sprites/pixel art com IA — do upload à aprovação — sem partir a grelha.

## O que faz

```
enviar UMA sprite ou uma TILESHEET
   │
   ├─ sprite única ──► expande para a resolução das ferramentas de geração (≈1024 px)
   │                   → manda junto com a IMAGEM DE REFERÊNCIA → mostra o resultado
   │
   └─ tilesheet ─────► RECORTA as sprites (grelha detetada)
                       → o utilizador ESCOLHE as que quer
                       → a escolhida é expandida + referência → REPLACE de prova
                       → aprovado (com considerações na retentativa, se rejeitar)
                       → TODAS as escolhidas são ajustadas AUTOMATICAMENTE,
                         em paralelo (máx. 32), e cada uma volta à paleta original
```

- **Análise**: o **MiMo v2.6 Pro** (`xiaomi/mimo-v2.6-pro` via OpenRouter) classifica a imagem
  (sprite vs tilesheet, colunas/linhas estimadas) + deteção algorítmica de grelha para os recortes exatos.
- **Geração**: melhor modelo de imagem do OpenRouter (`google/gemini-3-pro-image`, fallbacks automáticos).
- **Regresso à pixel art**: voto maioritário por bloco + snap à paleta original (as cores únicas da arte).
- Estado persistido em `studio.json`; erros no formato `Erro: … — Solução: …`.

## Uso

```bash
# análise rápida (e recorte, com --out)
python -m par analisar folha.png --out recortes/

# expandir uma sprite para a resolução das ferramentas de geração
python -m par expandir sprite.png --out sprite-grande.png

# studio completo em localhost
python -m par studio folha.png --out trabalho/ --mudanca "novo traje de samurai"
# → http://127.0.0.1:8770/
```

`--sem-ia` faz a análise só com o algoritmo. A chave OpenRouter vem de `OPENROUTER_API_KEY` ou
`~/.dsh/.credentials.yaml` (o projeto nunca pede se já existe).

## Desenvolvimento

```bash
python -m unittest discover -s tests -v   # testes offline (o OpenRouter é stubado)
```

Requisitos: Python 3.10+, Pillow, numpy.
