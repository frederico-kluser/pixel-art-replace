"""Análise da imagem: sprite única ou tilesheet? — MiMo v2.6 Pro + deteção algorítmica de grelha.

O MiMo CLASSIFICA (é sprite ou tilesheet, com colunas/linhas estimadas); o algoritmo encontra os
RECORTES exatos (faixas de conteúdo separadas por vãos, ou grelha uniforme derivada da classificação).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
from PIL import Image

from . import openrouter
from .util import ParError


@dataclass
class Celula:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Analise:
    tipo: str                                   # "sprite" | "tilesheet"
    largura: int
    altura: int
    fundo: tuple[int, int, int]
    tem_alfa: bool
    celulas: list[Celula] = field(default_factory=list)
    algoritmo: dict = field(default_factory=dict)
    ia: dict = field(default_factory=dict)

    def resumo(self) -> dict:
        fundo = f"#{self.fundo[0]:02X}{self.fundo[1]:02X}{self.fundo[2]:02X}"
        return {"tipo": self.tipo, "tamanho": [self.largura, self.altura],
                "fundo": fundo, "tem_alfa": self.tem_alfa,
                "celulas": len(self.celulas), "celula_px": [self.celulas[0].w, self.celulas[0].h] if self.celulas else None,
                "algoritmo": self.algoritmo, "ia": self.ia}


def carregar(png: bytes) -> tuple[np.ndarray, bool]:
    """(arr HxWx3 uint8, tem_alfa) — o alfa vira fundo da cor mais comum."""
    img = Image.open(io.BytesIO(png))
    tem_alfa = img.mode in ("RGBA", "LA") or "transparency" in img.info
    rgba = np.asarray(img.convert("RGBA"))
    alfa = rgba[..., 3]
    cores = rgba[..., :3]
    if tem_alfa and (alfa < 250).any():
        fundo = _cor_mais_comum(cores[alfa >= 250].reshape(-1, 3)) if (alfa >= 250).any() else (255, 0, 255)
        arr = cores.copy()
        arr[alfa < 128] = fundo
        return arr, True
    return cores.copy(), False


def _cor_mais_comum(px: np.ndarray) -> tuple[int, int, int]:
    vals, conts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    return tuple(int(v) for v in vals[int(conts.argmax())])


def _faixas_de_conteudo(vazio: np.ndarray) -> list[tuple[int, int]]:
    """Runs de vãos (True) → lista das faixas de CONTEÚDO (entre vãos)."""
    faixas: list[tuple[int, int]] = []
    dentro = False
    inicio = 0
    for i, v in enumerate(vazio):
        if not v and not dentro:
            inicio, dentro = i, True
        elif v and dentro:
            faixas.append((inicio, i))
            dentro = False
    if dentro:
        faixas.append((inicio, len(vazio)))
    return faixas


def detectar_grelha(mask: np.ndarray) -> dict | None:
    """Grelha por perfis de projeção: vãos de linhas/colunas sem conteúdo separam as células."""
    linhas = mask.any(axis=1)
    colunas = mask.any(axis=0)
    if not linhas.any():
        return None
    fr = _faixas_de_conteudo(~linhas)
    fc = _faixas_de_conteudo(~colunas)
    if len(fr) < 2 or len(fc) < 2:
        return None
    hs = [b - a for a, b in fr]
    ws = [b - a for a, b in fc]
    consistente = (max(hs) - min(hs) <= max(2, 0.15 * min(hs))) and (max(ws) - min(ws) <= max(2, 0.15 * min(ws)))
    celulas = [Celula(x, y, x2 - x, y2 - y) for y, y2 in fr for x, x2 in fc]
    return {"colunas": len(fc), "linhas": len(fr), "celula": [int(np.median(ws)), int(np.median(hs))],
            "consistente": bool(consistente), "celulas": celulas}


def _passo_dos_vaos(vazio: np.ndarray) -> int | None:
    """Passo da grelha pelas PONTAS dos vãos totalmente vazios: cada vão termina onde o conteúdo de
    uma célula começa (as poses são empacotadas no canto da célula), logo os fins alinham-se na grelha.
    Testa cada diferença como passo candidato e aceita a MENOR que encaixa ≥90% dos fins (±2 px)."""
    runs: list[tuple[int, int]] = []
    ini = None
    for i, v in enumerate(vazio):
        if v and ini is None:
            ini = i
        elif not v and ini is not None:
            runs.append((ini, i - 1))
            ini = None
    if ini is not None:
        runs.append((ini, len(vazio) - 1))
    fins = [b + 1 for a, b in runs]
    if len(fins) < 3:
        return None
    difs = sorted({b - a for a, b in pairwise(fins) if b > a})
    for p in difs:
        if p < 8:
            continue
        base = fins[0] % p
        encaixa = sum(1 for f in fins if min(abs((f - base) % p), p - abs((f - base) % p)) <= 2)
        if encaixa >= 0.9 * len(fins) and len(vazio) / p >= 2.5:
            return int(p)
    return None


def estimar_grelha_por_vaos(mask: np.ndarray) -> dict | None:
    """Grelha onde as poses NÃO preenchem a célula (os vãos interiores falsificam a deteção por runs):
    usa o passo regular entre as pontas dos vãos totalmente vazios."""
    pitch_x = _passo_dos_vaos(~mask.any(axis=0))
    pitch_y = _passo_dos_vaos(~mask.any(axis=1))
    if not pitch_x or not pitch_y:
        return None
    cols = max(2, round(mask.shape[1] / pitch_x))
    linhas = max(2, round(mask.shape[0] / pitch_y))
    return {"colunas": cols, "linhas": linhas, "celula": [mask.shape[1] // cols, mask.shape[0] // linhas],
            "consistente": True, "metodo": "vaos"}


def celulas_uniformes(larg: int, alt: int, cols: int, linhas: int) -> list[Celula]:
    """Slicing uniforme com limites fracionários (a folha pode ter margem e não dividir exata)."""
    out: list[Celula] = []
    for r in range(linhas):
        y1, y2 = round(r * alt / linhas), round((r + 1) * alt / linhas)
        for c in range(cols):
            x1, x2 = round(c * larg / cols), round((c + 1) * larg / cols)
            out.append(Celula(x1, y1, x2 - x1, y2 - y1))
    return out


def analisar(png: bytes, *, com_ia: bool = True, api_key: str | None = None) -> Analise:
    """Analisa o upload: classificação do MiMo + recortes algorítmicos."""
    arr, tem_alfa = carregar(png)
    h, w = arr.shape[:2]
    fundo = _cor_mais_comum(arr.reshape(-1, 3))
    mask = np.any(arr != np.array(fundo, np.uint8), axis=-1)
    grelha = detectar_grelha(mask)
    ia: dict = {}
    if com_ia:
        try:
            ia = openrouter.analisar_ia(png, api_key=api_key)
        except Exception as e:                   # noqa: BLE001 - a análise algorítmica sozinha chega
            ia = {"erro": str(e)}
    tipo_ia = str(ia.get("tipo", "")).lower()
    # grelha confiável por runs; senão, pelos VAÃOS (poses que não preenchem a célula); senão, o MiMo
    vaos = None if (grelha and grelha["consistente"]) else estimar_grelha_por_vaos(mask)
    if (grelha and grelha["consistente"]) or vaos or tipo_ia == "tilesheet":
        tipo = "tilesheet"
    else:
        tipo = "sprite"
    celulas: list[Celula] = []
    if tipo == "tilesheet":
        if grelha and grelha["consistente"]:
            celulas = grelha["celulas"]
            cols, rows = grelha["colunas"], grelha["linhas"]
        else:
            cols = (vaos or {}).get("colunas") or int(ia.get("colunas") or 1)
            rows = (vaos or {}).get("linhas") or int(ia.get("linhas") or 1)
            if cols * rows < 2:
                tipo = "sprite"
            else:
                celulas = celulas_uniformes(w, h, cols, rows)
                if vaos:
                    grelha = vaos
    else:
        celulas = [Celula(0, 0, w, h)]
        cols = rows = 1
    return Analise(tipo, w, h, fundo, tem_alfa, celulas,
                   algoritmo={k: v for k, v in (grelha or {}).items() if k != "celulas"} if grelha else {"grelha": "não detetada"},
                   ia=ia)


def recortar(arr: np.ndarray, celulas: list[Celula]) -> list[np.ndarray]:
    """Recorta as células (cada uma com o fundo limpo por volta)."""
    return [arr[c.y:c.y + c.h, c.x:c.x + c.w].copy() for c in celulas]


def montagem(sprites: list[np.ndarray], fundo: tuple[int, int, int], cols: int = 6) -> Image.Image:
    """Folha de contacto das sprites recortadas (para o utilizador escolher)."""
    if not sprites:
        raise ParError("sem sprites para mostrar", "faça o upload de uma imagem")
    cw = max(s.shape[1] for s in sprites)
    ch = max(s.shape[0] for s in sprites)
    cols = max(1, min(cols, len(sprites)))
    rows = (len(sprites) + cols - 1) // cols
    out = np.full((rows * (ch + 2) + 2, cols * (cw + 2) + 2, 3), fundo, np.uint8)
    for i, s in enumerate(sprites):
        r, c = divmod(i, cols)
        y, x = 2 + r * (ch + 2), 2 + c * (cw + 2)
        out[y:y + s.shape[0], x:x + s.shape[1]] = s
    return Image.fromarray(out)
