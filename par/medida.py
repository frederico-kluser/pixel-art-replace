"""Aferição DETERMINÍSTICA de cada conversão: quanto mudou de proporção/tamanho/posição?

O modelo redesenha — e redesenhar pode ocupar espaços novos ou deturpar proporções. Este módulo
mede, por sprite, o quanto a conversão se afastou do original e atribui um veredito objetivo
ANTES de o utilizador aprovar (e antes de a sprite ocupar o lugar da original):

métricas (todas em píxeis de arte, sobre as DUAS sprites re-quantizadas):
  · escala_altura / escala_largura — razão das alturas/larguras da bbox da figura (1.0 = igual);
  · proporcao        — razão de aspeto da figura: (larg/alt)_novo / (larg/alt)_original (1.0 = igual);
  · desvio_centro    — offset do centro da figura em píxeis de arte [dx, dy];
  · area             — razão de píxeis da figura (quanto de espaço ocupa);
  · iou_silhueta     — interseção/sobreposição das silhuetas (1.0 = silhueta idêntica).

veredito por sprite: `ok` (≤10% de desvio em tudo e IoU≥0.5) · `atencao` (≤20% e IoU≥0.3) ·
`reprovado` (além disso). O veredito da folha = o pior dos sprites.
"""

from __future__ import annotations

import numpy as np

LIMIARES = {
    #          ok (≤)   atencao (≤)   [fora = reprovado]
    "escala": 0.10,      # desvio relativo de escala (altura e largura)
    "proporcao": 0.10,   # desvio relativo da razão de aspeto da figura
    "centro": 2.0,       # píxeis de arte de desvio do centro
    "iou": 0.50,         # mínimo de IoU para `ok` (atenção até 0.30)
}

_ESCALA_ATENCAO = 0.20
_CENTRO_ATENCAO = 4.0
_IOU_ATENCAO = 0.30


def _mascara(spr: np.ndarray, fundo: tuple[int, int, int], tol: int = 40) -> np.ndarray:
    return np.abs(spr.astype(np.int32) - np.array(fundo, np.int32)).sum(axis=-1) > tol


def medir_sprite(original: np.ndarray, convertida: np.ndarray, fundo: tuple[int, int, int]) -> dict:
    """Métricas determinísticas de uma conversão (ambas as sprites na mesma grelha de arte)."""
    if original.shape != convertida.shape:
        return {"veredito": "reprovado", "erro": f"dimensões diferentes: {original.shape} vs {convertida.shape}"}
    mo, mc = _mascara(original, fundo), _mascara(convertida, fundo)
    if not mo.any() and not mc.any():
        return {"veredito": "ok", "nota": "célula vazia (sem figura nos dois lados)"}
    if not mo.any() or not mc.any():
        return {"veredito": "reprovado", "erro": "sprite sem figura (só fundo) num dos lados"}

    def bbox(m):
        ys, xs = np.nonzero(m)
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

    ox1, oy1, ox2, oy2 = bbox(mo)
    cx1, cy1, cx2, cy2 = bbox(mc)
    ow, oh = ox2 - ox1, oy2 - oy1
    cw, ch = cx2 - cx1, cy2 - cy1
    escala_largura = cw / ow
    escala_altura = ch / oh
    proporcao = (cw / ch) / (ow / oh)
    desvio_centro = [round((cx1 + cx2) / 2 - (ox1 + ox2) / 2, 2), round((cy1 + cy2) / 2 - (oy1 + oy2) / 2, 2)]
    area = float(mc.sum()) / float(mo.sum())
    inter = float((mo & mc).sum())
    uni = float((mo | mc).sum())
    iou = inter / uni if uni else 0.0

    def nivel(ok: float, atencao: float, valor: float) -> str:
        d = abs(valor - 1.0) if ok < 1 else valor          # para IoU usa-se o valor direto
        return "ok" if d <= ok else ("atencao" if d <= atencao else "reprovado")

    niveis = {
        "escala": "ok" if max(abs(escala_altura - 1), abs(escala_largura - 1)) <= LIMIARES["escala"]
                  else ("atencao" if max(abs(escala_altura - 1), abs(escala_largura - 1)) <= _ESCALA_ATENCAO
                        else "reprovado"),
        "proporcao": nivel(LIMIARES["proporcao"], _ESCALA_ATENCAO, proporcao),
        "centro": "ok" if max(abs(desvio_centro[0]), abs(desvio_centro[1])) <= LIMIARES["centro"]
                  else ("atencao" if max(abs(desvio_centro[0]), abs(desvio_centro[1])) <= _CENTRO_ATENCAO
                        else "reprovado"),
        "iou": "ok" if iou >= LIMIARES["iou"] else ("atencao" if iou >= _IOU_ATENCAO else "reprovado"),
    }
    ordem = {"ok": 0, "atencao": 1, "reprovado": 2}
    veredito = max(niveis, key=lambda k: ordem[niveis[k]])
    veredito = niveis[veredito]
    return {"veredito": veredito,
            "escala_altura": round(escala_altura, 4), "escala_largura": round(escala_largura, 4),
            "proporcao": round(proporcao, 4), "desvio_centro": desvio_centro,
            "area": round(area, 4), "iou_silhueta": round(iou, 4),
            "niveis": niveis,
            "bbox_original": [ox1, oy1, ox2, oy2], "bbox_convertida": [cx1, cy1, cx2, cy2]}


def medir_folha(original: np.ndarray, convertida: np.ndarray, rects: list[list[int]],
                fundo: tuple[int, int, int]) -> dict:
    """Mede célula a célula (rects = [[x,y,w,h], …] da grelha) e resume o estado da folha."""
    medicoes = []
    for i, (x, y, w, h) in enumerate(rects):
        o = original[y:y + h, x:x + w]
        c = convertida[y:y + h, x:x + w]
        m = medir_sprite(o, c, fundo)
        m["celula"] = i
        medicoes.append(m)
    validas = [m for m in medicoes if "erro" not in m]
    ordem = {"ok": 0, "atencao": 1, "reprovado": 2}
    veredito_folha = max((m["veredito"] for m in validas), key=lambda v: ordem[v], default="reprovado")

    def media(campo):
        vals = [m[campo] for m in validas if campo in m]
        return round(float(np.mean(vals)), 4) if vals else None

    return {"veredito_folha": veredito_folha,
            "total_celulas": len(rects), "medidas": len(validas),
            "resumo": {"ok": sum(1 for m in validas if m["veredito"] == "ok"),
                       "atencao": sum(1 for m in validas if m["veredito"] == "atencao"),
                       "reprovado": sum(1 for m in validas if m["veredito"] == "reprovado")},
            "medias": {"escala_altura": media("escala_altura"), "escala_largura": media("escala_largura"),
                       "proporcao": media("proporcao"), "area": media("area"), "iou_silhueta": media("iou_silhueta")},
            "piores": sorted((m for m in validas if "proporcao" in m),
                             key=lambda m: (ordem[m["veredito"]], -abs(m["proporcao"] - 1)), reverse=True)[:10],
            "medicoes": medicoes}
