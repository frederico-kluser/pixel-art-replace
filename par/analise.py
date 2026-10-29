"""Análise da imagem: sprite única ou tilesheet? — MiMo v2.6 Pro + deteção algorítmica de grelha.

O MiMo CLASSIFICA (é sprite ou tilesheet, com colunas/linhas estimadas); o algoritmo encontra os
RECORTES exatos (faixas de conteúdo separadas por vãos, ou grelha uniforme derivada da classificação).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

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
    # decisão: grelha algorítmica confiável → tilesheet; senão, a do MiMo
    if grelha and grelha["consistente"] or tipo_ia == "tilesheet":
        tipo = "tilesheet"
    else:
        tipo = "sprite"
    celulas: list[Celula] = []
    if tipo == "tilesheet":
        if grelha and grelha["consistente"]:
            celulas = grelha["celulas"]
        else:
            cols = int(ia.get("colunas") or 1)
            rows = int(ia.get("linhas") or 1)
            if cols * rows < 2:
                tipo = "sprite"
            else:
                celulas = [Celula(x * (w // cols), y * (h // rows), w // cols, h // rows)
                           for y in range(rows) for x in range(cols)]
    else:
        celulas = [Celula(0, 0, w, h)]
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
