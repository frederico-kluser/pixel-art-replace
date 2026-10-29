"""Testes offline do pixel-art-replace (o OpenRouter é stubado)."""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from par import analise, imagem, medida, openrouter, studio
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


class GrelhaPorVaosTests(unittest.TestCase):
    def test_poses_que_nao_preenchem_a_celula(self):
        # folha 8x6 com células 79x113: poses pequenas no canto de cada célula (vãos interiores!)
        larg, alt, cols, linhas, cel = 633, 679, 8, 6, (79, 113)
        mask = np.zeros((alt, larg), bool)
        for r in range(linhas):
            for c in range(cols):
                y, x = 1 + r * cel[1], 1 + c * cel[0]
                mask[y:y + 40, x:x + 30] = True
        g = analise.estimar_grelha_por_vaos(mask)
        self.assertIsNotNone(g)
        self.assertEqual((g["colunas"], g["linhas"]), (cols, linhas))

    def test_sprite_unica_sem_grelha(self):
        mask = np.zeros((50, 40), bool)
        mask[5:40, 5:30] = True
        self.assertIsNone(analise.estimar_grelha_por_vaos(mask))


class EncaixarTests(unittest.TestCase):
    def test_encaixa_na_bbox_original_com_aspeto_certo(self):
        fundo = (0, 160, 248)
        orig = np.full((12, 8, 3), fundo, np.uint8)
        orig[2:10, 1:6] = (200, 30, 30)                      # figura 5x8 na posição (1,2)
        # gerada: figura MAIOR e deslocada, canvas com aspeto ERRADO
        ger = np.full((200, 150, 3), fundo, np.uint8)
        ger[40:180, 30:120] = (200, 30, 30)
        out = imagem.encaixar(Image.fromarray(ger), orig, fundo)
        self.assertEqual(out.size, (8 * 85, 12 * 85))        # canvas no aspeto 8:12, escala ~1024/12
        arr = np.asarray(out.convert("RGB"))
        bb = imagem.bbox_da_figura(arr, fundo)
        self.assertIsNotNone(bb)
        esc = out.size[1] / 12
        self.assertAlmostEqual(bb[0] / esc, 1, delta=1)      # bbox na posição original (±1 px de arte)
        self.assertAlmostEqual((bb[2] - bb[0]) / esc, 5, delta=1)


class LimpezaTests(unittest.TestCase):
    def test_bloco_sujo_herda_dos_vizinhos(self):
        cores = np.array([[200, 30, 30], [30, 30, 200]], np.int32)
        fundo = (0, 160, 248)
        spr = np.full((8, 8, 3), fundo, np.uint8)
        spr[2:6, 2:6] = (200, 30, 30)
        img = imagem.expandir(spr, alvo=96, fundo=fundo)
        a = np.asarray(img.convert("RGB")).copy()
        bloco = img.width // 8
        # bloco MISTURADO (voto contestado): metade cor do vizinho, metade fundo
        a[bloco * 3:bloco * 4, bloco * 3:bloco * 4] = fundo
        a[bloco * 3:bloco * 4, bloco * 3:bloco * 3 + bloco // 2] = (200, 30, 30)
        out, stats = imagem.requantizar(Image.fromarray(a), 8, 8, cores, fundo)
        self.assertGreater(stats["blocos_sujos"], 0)
        self.assertGreater(stats["blocos_limpos"], 0)
        self.assertTrue((out[3, 3] == np.array((200, 30, 30))).all())  # limpo para a cor dos vizinhos


class MedidaTests(unittest.TestCase):
    fundo = (0, 160, 248)

    def _sprite(self, x1, y1, x2, y2):
        s = np.full((24, 16, 3), self.fundo, np.uint8)
        s[y1:y2, x1:x2] = (200, 30, 30)
        return s

    def test_identidade_e_perfeita(self):
        a = self._sprite(2, 2, 10, 20)
        m = medida.medir_sprite(a, a.copy(), self.fundo)
        self.assertEqual(m["veredito"], "ok")
        self.assertEqual(m["iou_silhueta"], 1.0)
        self.assertEqual(m["proporcao"], 1.0)

    def test_escala_reprovada(self):
        a = self._sprite(2, 2, 10, 20)          # 8x18
        b = self._sprite(1, 0, 15, 24)          # 14x24 — muito maior
        m = medida.medir_sprite(a, b, self.fundo)
        self.assertEqual(m["veredito"], "reprovado")
        self.assertGreater(m["escala_largura"], 1.2)

    def test_proporcao_alterada(self):
        a = self._sprite(2, 2, 10, 20)          # 8x18
        b = self._sprite(2, 2, 14, 20)          # 12x18 — mais largo
        m = medida.medir_sprite(a, b, self.fundo)
        self.assertGreater(abs(m["proporcao"] - 1.0), 0.15)

    def test_desvio_de_centro(self):
        a = self._sprite(2, 2, 10, 20)
        b = self._sprite(4, 2, 12, 20)          # +2 px no eixo x
        m = medida.medir_sprite(a, b, self.fundo)
        self.assertEqual(m["desvio_centro"][0], 2.0)

    def test_folha_resume_pior_celula(self):
        rect = [[0, 0, 16, 24]]
        o = np.stack([self._sprite(2, 2, 10, 20)])
        ok = np.stack([self._sprite(2, 2, 10, 20)])
        mau = np.stack([self._sprite(1, 0, 15, 24)])
        r = medida.medir_folha(o[0], ok[0], rect, self.fundo)
        self.assertEqual(r["veredito_folha"], "ok")
        r = medida.medir_folha(o[0], mau[0], rect, self.fundo)
        self.assertEqual(r["veredito_folha"], "reprovado")


if __name__ == "__main__":
    unittest.main()
