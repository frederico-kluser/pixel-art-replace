"""Testes offline do pixel-art-replace (o OpenRouter é stubado)."""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from par import analise, imagem, openrouter, studio
from par.util import ParError


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def sprite_cor(cor, w=16, h=24, fundo=(255, 0, 255)) -> np.ndarray:
    a = np.zeros((h, w, 3), np.uint8)
    a[:, :] = fundo
    a[2:h - 2, 2:w - 2] = cor
    return a


def tilesheet_fake(cols=3, rows=2, cw=16, ch=16) -> np.ndarray:
    fundo = (255, 0, 255)
    out = np.full((rows * (ch + 2) + 2, cols * (cw + 2) + 2, 3), fundo, np.uint8)
    cores = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30), (200, 30, 200), (30, 200, 200)]
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        y, x = 2 + r * (ch + 2), 2 + c * (cw + 2)
        out[y + 2:y + ch - 2, x + 2:x + cw - 2] = cores[i % len(cores)]
    return out


class AnaliseTests(unittest.TestCase):
    def test_sprite_unica(self):
        an = analise.analisar(png(Image.fromarray(sprite_cor((200, 30, 30)))), com_ia=False)
        self.assertEqual(an.tipo, "sprite")
        self.assertEqual(len(an.celulas), 1)

    def test_tilesheet_recorta_todas(self):
        arr = tilesheet_fake()
        an = analise.analisar(png(Image.fromarray(arr)), com_ia=False)
        self.assertEqual(an.tipo, "tilesheet")
        self.assertEqual(len(an.celulas), 6)
        rec = analise.recortar(arr, an.celulas)
        self.assertEqual(len(rec), 6)
        self.assertTrue(bool(np.any(rec[0] != rec[1])))         # células diferentes

    def test_grelha_uniforme_via_ia(self):
        # folha SEM vãos (conteúdo encostado) — só a classificação do MiMo (stub) acha a grelha
        arr = tilesheet_fake(cols=2, rows=2, cw=16, ch=16)
        arr[0, 0] = arr[0, 0]                                   # sem vãos: preencher tudo
        arr = np.full((32, 32, 3), (255, 0, 255), np.uint8)
        for i in range(4):
            r, c = divmod(i, 2)
            arr[r * 16:(r + 1) * 16, c * 16:(c + 1) * 16] = [(200, 30, 30), (30, 200, 30),
                                                             (30, 30, 200), (200, 200, 30)][i]
        orig = openrouter.analisar_ia
        openrouter.analisar_ia = lambda p, **k: {"tipo": "tilesheet", "colunas": 2, "linhas": 2,
                                                 "celula": [16, 16], "confianca": 0.9, "nota": "stub"}
        try:
            an = analise.analisar(png(Image.fromarray(arr)), com_ia=True)
        finally:
            openrouter.analisar_ia = orig
        self.assertEqual(an.tipo, "tilesheet")
        self.assertEqual(len(an.celulas), 4)


class ImagemTests(unittest.TestCase):
    def test_expandir_e_requantizar_roundtrip(self):
        spr = sprite_cor((200, 30, 30))
        cores, fundo = imagem.paleta_da_sprite(spr)
        img = imagem.expandir(spr, alvo=128)
        self.assertGreaterEqual(max(img.width, img.height), 96)     # ≈128 px de lado
        out, stats = imagem.requantizar(img, spr.shape[1], spr.shape[0], cores, fundo)
        self.assertTrue((out == spr).all())
        self.assertEqual(stats["blocos_sujos"], 0)

    def test_requantizar_recusa_aspect(self):
        cores = np.array([[200, 30, 30]], np.int32)
        with self.assertRaises(ParError):
            imagem.requantizar(Image.new("RGB", (100, 100)), 16, 32, cores, (255, 0, 255))

    def test_paleta_max_32(self):
        a = np.random.randint(0, 255, (8, 8, 3), np.uint8)
        with self.assertRaises(ParError):
            imagem.paleta_da_sprite(a)


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="par-"))
        self.img = self.dir / "folha.png"
        Image.fromarray(tilesheet_fake()).save(self.img)
        self._gerar = openrouter.gerar_imagem
        self._analisar = openrouter.analisar_ia
        self.chamadas: list[int] = []

        def fake_gerar(prompt, imagens, **kw):
            self.chamadas.append(len(imagens))
            spr = sprite_cor((30, 30, 200), 16, 16)
            return png(Image.fromarray(spr)), "modelo-teste"

        openrouter.gerar_imagem = fake_gerar
        openrouter.analisar_ia = lambda p, **k: {"tipo": "tilesheet", "colunas": 3, "linhas": 2,
                                                 "celula": [16, 16], "confianca": 0.9, "nota": "stub"}

    def tearDown(self):
        openrouter.gerar_imagem = self._gerar
        openrouter.analisar_ia = self._analisar
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fluxo_completo_tilesheet(self):
        st = studio.Studio(self.img, self.dir / "run", mudanca="novo traje")
        self.assertEqual(len(st.sprites), 6)
        st.selecionar([0, 1, 2])
        ref = png(Image.new("RGB", (16, 16), (10, 10, 10)))
        r = st.gerar_preview(ref, "o cinto preto")               # retentativa com consideração
        self.assertEqual(r["tentativa"], 1)
        st.aprovar()
        res = st.converter_todas()
        self.assertEqual(res["em_paralelo"], 2)                  # as 3 escolhidas menos a aprovada
        st._pool.shutdown(wait=True)
        self.assertEqual(st.progresso()["ok"], 2)
        fim = st.finalizar()
        self.assertEqual(fim["fase"], "pronto")
        self.assertEqual(len(fim["galeria"]), 2)
        for g in fim["galeria"]:
            self.assertTrue((st.out_dir / g["comparacao"]).exists())

    def test_fluxo_sprite_unica(self):
        Image.fromarray(sprite_cor((200, 30, 30))).save(self.dir / "spr.png")
        openrouter.analisar_ia = lambda p, **k: {"tipo": "sprite", "nota": "stub"}
        st = studio.Studio(self.dir / "spr.png", self.dir / "run2", mudanca="azul")
        self.assertEqual(st.estado["analise"]["tipo"], "sprite")
        st.gerar_preview(png(Image.new("RGB", (8, 8))))
        st.aprovar()
        self.assertEqual(st.converter_todas()["fase"], "pronto")   # nada mais para converter
        self.assertEqual(st.progresso()["total"], 0)

    def test_selecao_invalida(self):
        st = studio.Studio(self.img, self.dir / "run3")
        with self.assertRaises(ParError):
            st.selecionar([99])


class ParseTests(unittest.TestCase):
    def test_parse_resposta(self):
        png_b = b"\x89PNG-fake"
        self.assertEqual(openrouter.parse_data_uri(openrouter.data_uri(png_b)), png_b)


if __name__ == "__main__":
    unittest.main()
