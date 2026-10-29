"""Studio do pixel-art-replace (localhost): upload → análise (MiMo) → seleção → replace com
referência → aprovação/rejeitação (retentativa com considerações) → ajuste AUTOMÁTICO de todas as
imagens com o MÁXIMO de concorrência → galeria de antes/depois.

Fluxo (o que o dono pediu):
  · sprite única: expande para a resolução das ferramentas de geração, manda com a referência e mostra;
  · tilesheet: recorta as sprites, o utilizador escolhe, a escolhida vira o replace de prova e,
    aprovado, TODAS as escolhidas são ajustadas em paralelo (máx. 32 simultâneas).
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from . import analise, imagem, medida, openrouter
from .util import ParError, read_json, write_json

MAX_PARALELO = 32                                     # "máximo de concorrência possível"
RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "web" / "dist"                          # interface React (npm run build em web/)


def _encaixar_png(png: bytes, original: np.ndarray, fundo: tuple[int, int, int]) -> bytes:
    """Geração → encaixe na bbox original (drift de escala do modelo) → PNG."""
    ajustada = imagem.encaixar(Image.open(io.BytesIO(png)), original, fundo)
    buf = io.BytesIO()
    ajustada.save(buf, "PNG")
    return buf.getvalue()


# ── prompts ───────────────────────────────────────────────────────────────────

def prompt_replace(estado: dict, mudanca: str, consideracoes: list[str], imagens: int,
                   w: int, h: int) -> str:
    base = ("You are REDRAWING a pixel-art game sprite.\n"
            + ("Images: [1] style/outfit REFERENCE; [2] the original sprite BEFORE; "
               "[3] the SAME sprite AFTER conversion (approved example); [4] the sprite to convert NOW. "
               "Convert [4] the same way [2] became [3], using [1] as the style reference.\n"
               if imagens >= 4 else
               "Images: [1] style/outfit REFERENCE; [2] the sprite to REDRAW.\n")
            + f"\nLOCK (must not change): the sprite grid is {w}x{h} art-pixels; keep the EXACT grid, "
              "the same pose and silhouette, the same aspect ratio, flat solid colors only "
              "(no anti-aliasing, no gradients), and the same flat background color as the input "
              "(background = transparency). The background MUST stay EXACTLY that flat color: "
              "no gradient, no texture, no dither, no checkerboard, no vignette. Keep the figure at the "
              "EXACT same size and position within the frame as the input — do not enlarge, shrink or shift it. "
              "Keep HARD crisp edges between colors (no soft shading) and keep small face details readable: "
              "eyes and eyebrows as clear distinct pixels, exactly like the original sprite has.\n"
            f"\nCHANGE: {mudanca or 'Redraw the character with a completely new outfit and look.'}\n")
    if consideracoes:
        base += ("\nIMPORTANT corrections from the user's rejected attempts — fix exactly these:\n"
                 + "\n".join(f"- {c}" for c in consideracoes) + "\n")
    return base + "\nReturn ONLY the redrawn sprite image (same aspect ratio, highest size available)."


# ── estado ────────────────────────────────────────────────────────────────────

def novo_estado_vazio(out_dir: Path, model: str, mudanca: str) -> dict:
    """Estado sem imagem: o upload é feito NA PÁGINA (nada de imagem por terminal)."""
    return {"versao": 1, "entrada": None, "model": model, "mudanca": mudanca,
            "analise": None, "fase": "inicio", "selecionadas": [],
            "consideracoes": [], "historico": [], "aprovado": None,
            "sprites": [], "resultados": [], "paleta": [], "fundo": "#FF00FF",
            "largura_sprite": 1, "altura_sprite": 1}


class Studio:
    def __init__(self, entrada: Path | None, out_dir: Path, *, model: str = openrouter.MODELO_IMAGEM,
                 mudanca: str = "", sem_ia: bool = False):
        self.entrada = Path(entrada) if entrada else None
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.sem_ia = sem_ia
        self.lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None
        caminho = self.out_dir / "studio.json"
        if caminho.exists():
            self.estado = read_json(caminho)
        else:
            self.estado = novo_estado_vazio(self.out_dir, model, mudanca)
            self.salvar()
            if self.entrada is not None:
                self.reanalisar(self.entrada.read_bytes())   # fonte única: análise + seleção + rects
        # reconstrói as sprites em memória a partir dos PNGs (quando existem)
        self.sprites = [np.asarray(Image.open(self.out_dir / s["arquivo"]).convert("RGB"))
                        for s in self.estado.get("sprites", [])]

    def reanalisar(self, png: bytes) -> dict:
        """(Re)analisa um upload novo e reinicia o fluxo mantendo o modelo/mudança."""
        an = analise.analisar(png, com_ia=not self.sem_ia)
        arr, _ = analise.carregar(png)
        sprites = analise.recortar(arr, an.celulas)
        (self.out_dir / "entrada.png").write_bytes(png)
        cores, fundo = imagem.paleta_da_sprite(sprites[0] if sprites else arr)
        with self.lock:
            self.sprites = sprites
            fundo_arr = np.array(an.fundo, np.uint8)
            com_conteudo = [i for i, s in enumerate(sprites) if bool(np.any(np.any(s != fundo_arr, axis=-1)))]
            self.estado.update({
                "analise": an.resumo(), "fase": "analise",
                "selecionadas": com_conteudo or ([0] if sprites else []),
                "celulas_rects": [[int(c.x), int(c.y), int(c.w), int(c.h)] for c in an.celulas],
                "consideracoes": [], "historico": [], "aprovado": None, "resultados": [],
                "sprites": [{"id": i, "arquivo": f"sprite-{i:02d}.png", "tamanho": [int(s.shape[1]), int(s.shape[0])]}
                            for i, s in enumerate(sprites)],
                "paleta": [f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}" for c in cores],
                "fundo": f"#{fundo[0]:02X}{fundo[1]:02X}{fundo[2]:02X}",
                "largura_sprite": int(sprites[0].shape[1]) if sprites else 1,
                "altura_sprite": int(sprites[0].shape[0]) if sprites else 1,
            })
            for i, s in enumerate(sprites):
                Image.fromarray(s).save(self.out_dir / f"sprite-{i:02d}.png")
            self.salvar()
        return {"analise": self.estado["analise"], "sprites": self.estado["sprites"],
                "tipo": self.estado["analise"]["tipo"]}

    # ── utilidades ──
    def salvar(self) -> None:
        write_json(self.out_dir / "studio.json", self.estado)

    def paleta(self):
        cores = np.array([[int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)]
                          for c in self.estado["paleta"]], np.int32)
        fundo = tuple(int(self.estado["fundo"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return cores, fundo

    def sprite_png(self, idx: int) -> bytes:
        import io
        buf = io.BytesIO()
        imagem.expandir(self.sprites[idx]).save(buf, "PNG")
        return buf.getvalue()

    # ── fluxo ──
    def selecionar(self, ids: list[int]) -> dict:
        ids = sorted({int(i) for i in ids})
        if not ids or any(i < 0 or i >= len(self.sprites) for i in ids):
            raise ParError(f"seleção inválida: {ids}", f"escolha entre 0 e {len(self.sprites) - 1}")
        with self.lock:
            self.estado["selecionadas"] = ids
            self.estado["fase"] = "selecionado"
            self.salvar()
        return {"selecionadas": ids}

    def gerar_preview(self, ref_png: bytes, consideracao: str = "") -> dict:
        if not self.estado["selecionadas"]:
            raise ParError("nenhuma sprite selecionada", "selecione as sprites primeiro")
        self.guardar_referencia(ref_png)
        with self.lock:
            if consideracao.strip():
                self.estado["consideracoes"].append(consideracao.strip())
            tentativa = len(self.estado["historico"]) + 1
            self.estado["fase"] = "preview"
            self.salvar()
        alvo = self.estado["selecionadas"][0]
        w, h = self.sprites[alvo].shape[1], self.sprites[alvo].shape[0]
        prompt = prompt_replace(self.estado, self.estado["mudanca"], self.estado["consideracoes"],
                                imagens=2 if not self.estado["aprovado"] else 4, w=w, h=h)
        imgs = [ref_png, self.sprite_png(alvo)]
        if self.estado["aprovado"]:                       # retentativa já com exemplo aprovado
            imgs = [ref_png, (self.out_dir / self.estado["aprovado"]["antes"]).read_bytes(),
                    (self.out_dir / self.estado["aprovado"]["depois"]).read_bytes(), self.sprite_png(alvo)]
        png, usado = openrouter.gerar_imagem(prompt, imgs, model=self.estado["model"])
        png = _encaixar_png(png, self.sprites[alvo], self.paleta()[1])
        caminho = self.out_dir / f"tentativa-{tentativa:02d}.png"
        caminho.write_bytes(png)
        # PORTÃO DETERMINÍSTICO: aferir a conversão ANTES de o utilizador decidir
        cores, fundo = self.paleta()
        arte, _ = imagem.requantizar(Image.open(io.BytesIO(png)), w, h, cores, fundo)
        med = medida.medir_sprite(self.sprites[alvo], arte, fundo)
        with self.lock:
            self.estado["historico"].append({"tentativa": tentativa, "sprite": alvo, "modelo": usado,
                                             "consideracoes": self.estado["consideracoes"][-1:] or [],
                                             "imagem": caminho.name, "medicao": med})
            self.salvar()
        return {"tentativa": tentativa, "imagem": caminho.name, "modelo": usado, "sprite": alvo,
                "medicao": med}

    def aprovar(self) -> dict:
        if not self.estado["historico"]:
            raise ParError("nada gerado ainda", "gere o replace primeiro")
        ult = self.estado["historico"][-1]
        with self.lock:
            antes = f"{ult['sprite']}-original.png"
            Image.fromarray(self.sprites[ult["sprite"]]).save(self.out_dir / antes)
            self.estado["aprovado"] = {"sprite": ult["sprite"], "antes": antes,
                                       "depois": ult["imagem"], "modelo": ult["modelo"]}
            self.estado["fase"] = "aprovado"
            self.salvar()
        return {"aprovado": self.estado["aprovado"]}

    def converter_todas(self) -> dict:
        """Ajusta TODAS as selecionadas em paralelo (máx. de concorrência)."""
        if not self.estado["aprovado"]:
            raise ParError("nenhum replace aprovado", "aprove o replace primeiro")
        ap = self.estado["aprovado"]
        ref = self._ref
        antes = (self.out_dir / ap["antes"]).read_bytes()
        depois = (self.out_dir / ap["depois"]).read_bytes()
        pend = [i for i in self.estado["selecionadas"]
                if i != ap["sprite"] and not any(r["id"] == i and r["estado"] == "ok"
                                                 for r in self.estado["resultados"])]
        with self.lock:
            self.estado["fase"] = "convertendo"
            for i in pend:
                if not any(r["id"] == i for r in self.estado["resultados"]):
                    self.estado["resultados"].append({"id": i, "estado": "pendente"})
            self.salvar()
        if not pend:
            return self.finalizar()
        self._pool = ThreadPoolExecutor(max_workers=min(MAX_PARALELO, len(pend)))
        for i in pend:
            self._pool.submit(self._converter_uma, i, ref, antes, depois)
        return {"em_paralelo": len(pend), "max_paralelo": min(MAX_PARALELO, len(pend))}

    def _converter_uma(self, idx: int, ref: bytes, antes: bytes, depois: bytes) -> None:
        try:
            h, w = self.sprites[idx].shape[:2]
            prompt = prompt_replace(self.estado, self.estado["mudanca"], self.estado["consideracoes"],
                                    imagens=4, w=w, h=h)
            png, usado = None, ""
            ultimo_erro = ""
            for tentativa in range(2):                      # retry automático: arruma falhas na giração
                try:
                    png, usado = openrouter.gerar_imagem(prompt, [ref, antes, depois, self.sprite_png(idx)],
                                                         model=self.estado["model"])
                    png = _encaixar_png(png, self.sprites[idx], self.paleta()[1])
                    break
                except Exception as e:                      # noqa: BLE001
                    ultimo_erro = str(e)
                    png = None
            if png is None:
                raise ParError(f"sprite {idx}: {ultimo_erro}", "verifique créditos/rate limit e repita")
            (self.out_dir / f"sprite-{idx:02d}-novo.png").write_bytes(png)
            cores, fundo = self.paleta()
            h, w = self.sprites[idx].shape[:2]
            novo, stats = imagem.requantizar(Image.open(self.out_dir / f"sprite-{idx:02d}-novo.png"),
                                             w, h, cores, fundo)
            Image.fromarray(novo).save(self.out_dir / f"sprite-{idx:02d}-novo.png")
            # PORTÃO DETERMINÍSTICO: medir cada conversão (aparece no resultado antes de qualquer uso)
            stats["medicao"] = medida.medir_sprite(self.sprites[idx], novo, fundo)
            with self.lock:
                for r in self.estado["resultados"]:
                    if r["id"] == idx:
                        r.pop("erro", None)               # limpa resíduo de tentativa anterior
                        r.update({"estado": "ok", "imagem": f"sprite-{idx:02d}-novo.png",
                                  "modelo": usado, **stats})
                self.salvar()
        except Exception as e:                            # noqa: BLE001 - cada sprite falha sozinha
            with self.lock:
                for r in self.estado["resultados"]:
                    if r["id"] == idx:
                        r.update({"estado": "erro", "erro": str(e)})
                self.salvar()

    def progresso(self) -> dict:
        res = self.estado["resultados"]
        return {"total": len(res), "ok": sum(1 for r in res if r["estado"] == "ok"),
                "erros": sum(1 for r in res if r["estado"] == "erro"),
                "pendentes": sum(1 for r in res if r["estado"] == "pendente")}

    def _montar_tilesheet(self) -> dict:
        """Tilesheet final NAS MESMAS PROPORÇÕES da entrada: cada sprite convertida volta ao seu
        retângulo original (celulas_rects); as células não convertidas ficam como estavam."""
        origem = self.out_dir / "entrada.png"
        rects = self.estado.get("celulas_rects") or []
        if not origem.exists() or not rects:
            return {}
        base = np.asarray(Image.open(origem).convert("RGB"))
        novo = base.copy()
        cores, fundo = self.paleta()
        # a sprite de PROVA (aprovada) também entra: é a conversão dela própria
        ap = self.estado.get("aprovado")
        if ap and int(ap["sprite"]) < len(rects):
            x, y, w, h = rects[int(ap["sprite"])]
            sp_img = Image.open(self.out_dir / ap["depois"]).convert("RGB")
            sp, _ = imagem.requantizar(sp_img, w, h, cores, fundo)
            novo[y:y + h, x:x + w] = sp
        for r in self.estado["resultados"]:
            if r["estado"] != "ok" or r["id"] >= len(rects):
                continue
            x, y, w, h = rects[r["id"]]
            sp = np.asarray(Image.open(self.out_dir / r["imagem"]).convert("RGB"))
            if sp.shape[:2] != (h, w):
                sp = np.asarray(Image.fromarray(sp).resize((w, h), Image.NEAREST))
            novo[y:y + h, x:x + w] = sp
        img = Image.fromarray(novo)
        img.save(self.out_dir / "tilesheet-novo.png")
        img.resize((img.width * 16, img.height * 16), Image.NEAREST).save(
            self.out_dir / "tilesheet-novo-expandido.png")
        imagem.comparacao(base, novo).save(self.out_dir / "tilesheet-comparacao.png")
        return {"tilesheet_novo": "tilesheet-novo.png", "tilesheet_expandido": "tilesheet-novo-expandido.png",
                "tilesheet_comparacao": "tilesheet-comparacao.png", "dimensoes": [img.width, img.height]}

    def finalizar(self) -> dict:
        galeria = []
        for r in self.estado["resultados"]:
            if r["estado"] != "ok":
                continue
            idx = r["id"]
            comp = imagem.comparacao(self.sprites[idx],
                                     np.asarray(Image.open(self.out_dir / r["imagem"]).convert("RGB")))
            nome = f"comparacao-{idx:02d}.png"
            comp.save(self.out_dir / nome)
            r["comparacao"] = nome
            galeria.append({"id": idx, "comparacao": nome, "novo": r["imagem"]})
        folha = self._montar_tilesheet()
        with self.lock:
            self.estado["fase"] = "pronto"
            self.salvar()
        return {"fase": "pronto", "galeria": galeria, "progresso": self.progresso(), **folha}

    @property
    def _ref(self) -> bytes:
        return (self.out_dir / "referencia.png").read_bytes()

    def guardar_referencia(self, png: bytes) -> None:
        (self.out_dir / "referencia.png").write_bytes(png)


# ── servidor HTTP ─────────────────────────────────────────────────────────────

def fazer_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, status=200):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _erro(self, e):
            self._json({"erro": str(getattr(e, "what", None) or e)}, 500)

        def _png(self, data: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def _estatico(self, rel: str) -> bool:
            """Serve um ficheiro de web/dist (a interface React). Devolve False se não existir."""
            alvo = (DIST / rel.lstrip("/")).resolve()
            if DIST.resolve() not in alvo.parents or not alvo.is_file():
                return False
            dados = alvo.read_bytes()
            tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
            return True

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    if (DIST / "index.html").exists():
                        self._estatico("/index.html")
                        return
                    corpo = ("<b>web/dist não existe.</b> Para ver a interface: "
                             "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code> "
                             "(ou <code>npm run dev</code> para o servidor de desenvolvimento).").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(corpo)))
                    self.end_headers()
                    self.wfile.write(corpo)
                elif self.path.startswith("/api/") or self.path.startswith("/sprite/") \
                        or self.path.startswith("/ficheiros/"):
                    self._rota_api()
                elif self._estatico(self.path.split("?")[0]):
                    return
                elif (DIST / "index.html").exists():
                    self._estatico("/index.html")     # SPA fallback
                else:
                    self._json({"erro": "não encontrado"}, 404)
            except Exception as e:                       # noqa: BLE001
                self._erro(e)

        def _rota_api(self):
            if self.path.startswith("/sprite/"):
                self._png(studio.sprite_png(int(self.path[len("/sprite/"):-4])))
            elif self.path.startswith("/ficheiros/"):
                nome = self.path[len("/ficheiros/"):].split("?")[0]
                alvo = (studio.out_dir / nome).resolve()
                if studio.out_dir.resolve() not in alvo.parents:
                    raise ParError("caminho fora do diretório")
                self._png(alvo.read_bytes())
            elif self.path == "/api/estado":
                self._json({"fase": studio.estado["fase"], "model": studio.estado["model"],
                            "analise": studio.estado["analise"], "sprites": studio.estado["sprites"],
                            "selecionadas": studio.estado["selecionadas"],
                            "progresso": studio.progresso(), "resultados": studio.estado["resultados"]})
            elif self.path == "/api/resultado":
                self._json(studio.finalizar())
            else:
                self._json({"erro": "não encontrado"}, 404)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/analisar":
                    png = base64.b64decode(body.get("img") or "")
                    if not png:
                        raise ParError("falta a imagem", "escolha um ficheiro")
                    self._json(studio.reanalisar(png))
                elif self.path == "/api/selecionar":
                    self._json(studio.selecionar(body.get("ids") or []))
                elif self.path == "/api/gerar":
                    ref = base64.b64decode(body.get("ref") or "") or None
                    if ref:
                        studio.guardar_referencia(ref)
                    elif not (studio.out_dir / "referencia.png").exists():
                        raise ParError("falta a imagem de referência", "faça upload na página")
                    self._json(studio.gerar_preview(studio._ref, body.get("consideracao") or ""))
                elif self.path == "/api/aprovar":
                    self._json(studio.aprovar())
                elif self.path == "/api/converter":
                    self._json(studio.converter_todas())
                else:
                    self._json({"erro": "não encontrado"}, 404)
            except Exception as e:                       # noqa: BLE001
                self._erro(e)

    return Handler


def servir(entrada: Path | None, out_dir: Path, *, model: str = openrouter.MODELO_IMAGEM,
           mudanca: str = "", sem_ia: bool = False, port: int = 8770,
           host: str = "127.0.0.1", abrir: bool = True) -> None:
    """Sobe o studio. `entrada=None` = o upload é feito NA PÁGINA (nada de imagem por terminal).
    `abrir=True` abre o navegador sozinho."""
    studio = Studio(entrada, out_dir, model=model, mudanca=mudanca, sem_ia=sem_ia)
    httpd = ThreadingHTTPServer((host, port), fazer_handler(studio))
    url = f"http://{host}:{port}/"
    print(f"pixel-art-replace → {url}  (modelo de imagem: {studio.estado['model']})")
    an = studio.estado.get("analise")
    if an:
        nome = studio.entrada.name if studio.entrada else "upload na página"
        print(f"entrada: {nome} · análise: {an['tipo']} ({an['celulas']} sprites) · Ctrl+C para sair")
    else:
        print("sem imagem ainda — faça o upload NA PÁGINA · Ctrl+C para sair")
    if abrir:
        import webbrowser
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
