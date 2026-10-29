#!/usr/bin/env bash
# pixel-art-replace — UM comando só: instala o que falta e abre a interface.
# Uso:  ./iniciar.sh
# O upload das imagens faz-se NA PÁGINA — nada de imagens por terminal.
set -e
cd "$(dirname "$0")"

echo "==> dependências Python (idempotente)"
python3 -m pip install -r requirements.txt >/dev/null || python -m pip install -r requirements.txt >/dev/null

if [ ! -f web/dist/index.html ]; then
  echo "==> a construir a interface (só na primeira vez)"
  command -v npm >/dev/null || { echo "Erro: npm não encontrado — Solução: instale o Node.js (https://nodejs.org)"; exit 1; }
  (cd web && npm install && npm run build)
fi

echo "==> a subir o studio — o navegador abre sozinho (http://127.0.0.1:8770/)"
python3 -m par up --out trabalho 2>/dev/null || python -m par up --out trabalho
