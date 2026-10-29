"""CLI do pixel-art-replace: `python -m par <comando>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analise, imagem, medida, openrouter, studio
from .util import ParError, read_json, write_json


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


def cmd_medir(a):
    """Aferição determinística: quanto cada conversão mudou de proporção/tamanho/posição?"""
    arr_o, _ = analise.carregar(Path(a.atual).read_bytes())
    arr_n, _ = analise.carregar(Path(a.novo).read_bytes())
    if arr_o.shape != arr_n.shape:
        raise ParError(f"folhas de dimensões diferentes: {arr_o.shape[1]}x{arr_o.shape[0]} vs "
                       f"{arr_n.shape[1]}x{arr_n.shape[0]}", "a nova folha tem de ter as proporções da atual")
    if a.rects:
        estado = read_json(Path(a.rects))
        rects = estado["celulas_rects"]
        fundo = tuple(int(estado["fundo"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    else:
        an = analise.analisar(Path(a.atual).read_bytes(), com_ia=False)
        rects = [[c.x, c.y, c.w, c.h] for c in an.celulas]
        fundo = an.fundo
    res = medida.medir_folha(arr_o, arr_n, rects, fundo)
    if a.out:
        write_json(Path(a.out) / "medicao.json", res)
        print(f"→ {a.out}/medicao.json")
    print(f"VEREDITO DA FOLHA: {res['veredito_folha'].upper()}  "
          f"({res['resumo']['ok']} ok · {res['resumo']['atencao']} atenção · {res['resumo']['reprovado']} reprovado "
          f"de {res['medidas']} medidas)")
    print("médias: " + " · ".join(f"{k}={v}" for k, v in res["medias"].items() if v is not None))
    print("piores:")
    for m in res["piores"]:
        print(f"  célula {m['celula']:>2} [{m['veredito']}] escala {m['escala_largura']}x{m['escala_altura']} "
              f"proporção {m['proporcao']} centro {m['desvio_centro']} IoU {m['iou_silhueta']}")


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
    s = sub.add_parser("medir", help="aferição determinística: escala/proporção/posição/IoU de cada conversão "
                                     "(atual × novo), com veredito por sprite")
    s.add_argument("--atual", required=True, help="tilesheet atual (referência)")
    s.add_argument("--novo", required=True, help="tilesheet convertida (mesmas proporções)")
    s.add_argument("--rects", help="studio.json do fluxo (usa os rects das células); sem ele, deteta a grelha")
    s.add_argument("--out", help="grava medicao.json neste diretório")
    s.set_defaults(fn=cmd_medir)
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
