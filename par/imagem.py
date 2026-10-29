"""Expansão para a resolução das ferramentas de geração e regresso à pixel art (paleta original).

- `expandir`: nearest-neighbor até ~1024 px do lado maior ("o tamanho que essas ferramentas fazem");
  os píxeis viram quadrados grandes, fáceis do modelo mexer e fáceis de reconverter.
- `requantizar`: a imagem devolvida volta aos píxeis da arte por VOTO MAIORITÁRIO do interior de cada
  quadrado + snap à paleta original (as cores únicas da sprite) — é o "replace" fiel.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .util import ParError

ALVO = 1024                    # lado maior de referência das ferramentas de geração
K_MAX = 64


def paleta_da_sprite(spr: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int]]:
    """(lista de cores únicas, fundo) — o fundo é a cor mais comum; máx. 32 cores."""
    px = spr.reshape(-1, 3)
    vals, conts = np.unique(px, axis=0, return_counts=True)
    fundo = tuple(int(v) for v in vals[int(conts.argmax())])
    cores = [tuple(int(v) for v in c) for c in vals]
    if len(cores) > 32:
        raise ParError(f"sprite com {len(cores)} cores (máx. 32)", "reduza a paleta da arte antes de enviar")
    return np.array(cores, np.int32), fundo


def expandir(spr: np.ndarray, alvo: int = ALVO, fundo: tuple[int, int, int] | None = None) -> Image.Image:
    """Expande a sprite (nearest-neighbor) até o lado maior ≈ `alvo` px, sem interpolación."""
    h, w = spr.shape[:2]
    k = max(1, min(K_MAX, round(alvo / max(w, h))))
    img = Image.fromarray(spr.astype(np.uint8))
    return img.resize((w * k, h * k), Image.NEAREST)


def bloco_expandido(img: Image.Image, w: int, h: int) -> int:
    """Tamanho do quadrado expandido que a imagem devolvida implica (para amostrar)."""
    larg = img.width / w
    alt = img.height / h
    return max(1, round(min(larg, alt)))


def requantizar(img: Image.Image, w: int, h: int, cores: np.ndarray,
                fundo: tuple[int, int, int], limiar: float = 0.7) -> tuple[np.ndarray, dict]:
    """Imagem devolvida (qualquer tamanho, mesmo aspect ratio) → sprite w×h na paleta original.
    Voto maioritário do interior de cada bloco; blocos sujos (voto contestado) são reportados."""
    arr = np.asarray(img.convert("RGB"), np.int32)
    if abs(arr.shape[1] / arr.shape[0] - w / h) > 0.02 * (w / h) + 0.02:
        raise ParError(f"aspect ratio mudou: devolvida {arr.shape[1]}x{arr.shape[0]}, sprite {w}x{h}",
                       "peça ao modelo manter o aspect ratio")
    paleta = np.vstack([np.array(fundo, np.int32), cores]) if tuple(fundo) not in [tuple(c) for c in cores] else cores
    out = np.zeros((h, w, 3), np.int32)
    sujos = 0
    pur = 0.0
    for yy in range(h):
        for xx in range(w):
            x1, x2 = round(xx * arr.shape[1] / w), round((xx + 1) * arr.shape[1] / w)
            y1, y2 = round(yy * arr.shape[0] / h), round((yy + 1) * arr.shape[0] / h)
            x2, y2 = max(x2, x1 + 1), max(y2, y1 + 1)
            bloco = arr[y1:y2, x1:x2].reshape(-1, 3)
            pad_y, pad_x = max(1, (y2 - y1) // 4), max(1, (x2 - x1) // 4)
            interior = arr[y1 + pad_y:max(y2 - pad_y, y1 + 1), x1 + pad_x:max(x2 - pad_x, x1 + 1)].reshape(-1, 3)
            if not len(interior):
                interior = bloco
            d = ((interior[:, None, :] - paleta[None, :, :]) ** 2).sum(axis=2)
            nearest = d.argmin(axis=1)
            counts = np.bincount(nearest, minlength=len(paleta))
            vencedor = int(counts.argmax())
            pureza = float(counts[vencedor]) / max(1, len(interior))
            out[yy, xx] = paleta[vencedor]
            pur += pureza
            if pureza < limiar:
                sujos += 1
    stats = {"pureza": round(pur / (w * h), 4), "blocos_sujos": sujos}
    return out.astype(np.uint8), stats


def comparacao(antes: np.ndarray, depois: np.ndarray) -> Image.Image:
    """Sprite atual | nova | diferenças — para mostrar ao utilizador."""
    a = antes.astype(np.uint8)
    b = depois.astype(np.uint8) if depois.shape == antes.shape else np.asarray(
        Image.fromarray(depois.astype(np.uint8)).resize((a.shape[1], a.shape[0])))
    igual = np.all(a == b, axis=-1)
    diff = np.full_like(a, 40)
    diff[~igual] = (230, 60, 60)
    esc = max(2, min(12, 512 // max(a.shape[0], a.shape[1])))
    w, h = a.shape[1] * esc, a.shape[0] * esc
    out = Image.new("RGB", (3 * w + 40, h + 30), (18, 18, 24))
    from PIL import ImageDraw
    d = ImageDraw.Draw(out)
    for i, (pane, titulo) in enumerate(((a, "atual"), (b, "novo"), (diff, f"diferenças ({int((~igual).sum())} px)"))):
        out.paste(Image.fromarray(pane).resize((w, h), Image.NEAREST), (10 + i * (w + 10), 22))
        d.text((10 + i * (w + 10), 5), titulo, fill=(235, 235, 235))
    return out
