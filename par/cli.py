"""CLI do pixel-art-replace: `python -m par <comando>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analise, imagem, openrouter, studio
from .util import ParError


def cmd_analisar(a):
    an = analise.analisar(Path(a.imagem).read_bytes(), com_ia=not a.sem_ia)
    out = an.resumo()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.out:
        arr, _ = analise.carregar(Path(a.imagem).read_bytes())
        sprites = analise.recortar(arr, an.celulas)
        d = Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(sprites):
            from PIL import Image
            Image.fromarray(s).save(d / f"sprite-{i:02d}.png")
        analise.montagem(sprites, an.fundo).save(d / "montagem.png")
        print(f"→ {len(sprites)} sprites recortadas em {d} (+ montagem.png)")


def cmd_expandir(a):
    arr, _ = analise.carregar(Path(a.imagem).read_bytes())
    img = imagem.expandir(arr, alvo=a.alvo)
    img.save(a.out)
    print(f"→ {a.out} ({img.width}x{img.height})")


def cmd_studio(a):
    studio.servir(Path(a.imagem) if a.imagem else None, Path(a.out), model=a.model, mudanca=a.mudanca or "",
                  sem_ia=a.sem_ia, port=a.port, abrir=a.abrir)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="par", description="pixel-art-replace: sprites por IA, do upload à aprovação")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analisar", help="analisa a imagem: sprite ou tilesheet (MiMo v2.6 Pro + grelha)")
    s.add_argument("imagem")
    s.add_argument("--out", help="também recorta e grava as sprites neste diretório")
    s.add_argument("--sem-ia", action="store_true", help="só o algoritmo (sem chamar o MiMo)")
    s.set_defaults(fn=cmd_analisar)
    s = sub.add_parser("expandir", help="expande a sprite para a resolução das ferramentas de geração")
    s.add_argument("imagem")
    s.add_argument("--out", required=True)
    s.add_argument("--alvo", type=int, default=imagem.ALVO, help="lado maior de referência (padrão 1024)")
    s.set_defaults(fn=cmd_expandir)
    s = sub.add_parser("up", help="ATALHO: sobe o studio e abre o navegador (upload na página, nada no terminal)")
    s.add_argument("--out", default="trabalho", help="diretório de trabalho (padrão: trabalho)")
    s.add_argument("--model", default=openrouter.MODELO_IMAGEM)
    s.add_argument("--mudanca", default="")
    s.add_argument("--sem-ia", action="store_true")
    s.add_argument("--port", type=int, default=8770)
    s.set_defaults(fn=cmd_studio, imagem=None, abrir=True)
    s = sub.add_parser("studio", help="abre o studio em localhost (análise → replace → aprovar → paralelo)")
    s.add_argument("imagem", nargs="?", help="sprite ou tilesheet de entrada (opcional: dá para fazer upload na página)")
    s.add_argument("--out", default="trabalho", help="diretório de trabalho (padrão: trabalho)")
    s.add_argument("--model", default=openrouter.MODELO_IMAGEM)
    s.add_argument("--mudanca", default="")
    s.add_argument("--sem-ia", action="store_true")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--abrir", action="store_true", help="abre o navegador sozinho")
    s.set_defaults(fn=cmd_studio)
    a = p.parse_args(argv)
    try:
        a.fn(a)
        return 0
    except ParError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
