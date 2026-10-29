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
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from . import analise, imagem, openrouter
from .util import ParError, read_json, write_json

MAX_PARALELO = 32                                     # "máximo de concorrência possível"


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
              "(background = transparency).\n"
            f"\nCHANGE: {mudanca or 'Redraw the character with a completely new outfit and look.'}\n")
    if consideracoes:
        base += ("\nIMPORTANT corrections from the user's rejected attempts — fix exactly these:\n"
                 + "\n".join(f"- {c}" for c in consideracoes) + "\n")
    return base + "\nReturn ONLY the redrawn sprite image (same aspect ratio, highest size available)."


# ── estado ────────────────────────────────────────────────────────────────────

class Studio:
    def __init__(self, entrada: Path, out_dir: Path, *, model: str = openrouter.MODELO_IMAGEM,
                 mudanca: str = "", sem_ia: bool = False):
        self.entrada = Path(entrada)
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
            png = self.entrada.read_bytes()
            an = analise.analisar(png, com_ia=not sem_ia)
            arr, _ = analise.carregar(png)
            sprites = analise.recortar(arr, an.celulas)
            (self.out_dir / "entrada.png").write_bytes(png)
            self.sprites: list[np.ndarray] = []
            for i, s in enumerate(sprites):
                nome = f"sprite-{i:02d}.png"
                Image.fromarray(s).save(self.out_dir / nome)
                self.sprites.append(s)
            cores, fundo = imagem.paleta_da_sprite(sprites[0] if sprites else arr)
            self.estado = {
                "versao": 1, "entrada": self.entrada.name, "model": model, "mudanca": mudanca,
                "analise": an.resumo(), "fase": "analise", "selecionadas": [0] if sprites else [],
                "consideracoes": [], "historico": [], "aprovado": None,
                "sprites": [{"id": i, "arquivo": f"sprite-{i:02d}.png", "tamanho": [int(s.shape[1]), int(s.shape[0])]}
                            for i, s in enumerate(sprites)],
                "resultados": [],
                "paleta": [f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}" for c in cores],
                "fundo": f"#{fundo[0]:02X}{fundo[1]:02X}{fundo[2]:02X}",
                "largura_sprite": int(sprites[0].shape[1]) if sprites else 1,
                "altura_sprite": int(sprites[0].shape[0]) if sprites else 1,
            }
            self.salvar()
        # reconstrói as sprites em memória a partir dos PNGs
        self.sprites = [np.asarray(Image.open(self.out_dir / s["arquivo"]).convert("RGB"))
                        for s in self.estado["sprites"]]

    def reanalisar(self, png: bytes) -> dict:
        """(Re)analisa um upload novo e reinicia o fluxo mantendo o modelo/mudança."""
        an = analise.analisar(png, com_ia=not self.sem_ia)
        arr, _ = analise.carregar(png)
        sprites = analise.recortar(arr, an.celulas)
        (self.out_dir / "entrada.png").write_bytes(png)
        cores, fundo = imagem.paleta_da_sprite(sprites[0] if sprites else arr)
        with self.lock:
            self.sprites = sprites
            self.estado.update({
                "analise": an.resumo(), "fase": "analise", "selecionadas": [0] if sprites else [],
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
        caminho = self.out_dir / f"tentativa-{tentativa:02d}.png"
        caminho.write_bytes(png)
        with self.lock:
            self.estado["historico"].append({"tentativa": tentativa, "sprite": alvo, "modelo": usado,
                                             "consideracoes": self.estado["consideracoes"][-1:] or [],
                                             "imagem": caminho.name})
            self.salvar()
        return {"tentativa": tentativa, "imagem": caminho.name, "modelo": usado, "sprite": alvo}

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
            png, usado = openrouter.gerar_imagem(prompt, [ref, antes, depois, self.sprite_png(idx)],
                                                 model=self.estado["model"])
            (self.out_dir / f"sprite-{idx:02d}-novo.png").write_bytes(png)
            cores, fundo = self.paleta()
            h, w = self.sprites[idx].shape[:2]
            novo, stats = imagem.requantizar(Image.open(self.out_dir / f"sprite-{idx:02d}-novo.png"),
                                             w, h, cores, fundo)
            Image.fromarray(novo).save(self.out_dir / f"sprite-{idx:02d}-novo.png")
            with self.lock:
                for r in self.estado["resultados"]:
                    if r["id"] == idx:
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
        with self.lock:
            self.estado["fase"] = "pronto"
            self.salvar()
        return {"fase": "pronto", "galeria": galeria, "progresso": self.progresso()}

    @property
    def _ref(self) -> bytes:
        return (self.out_dir / "referencia.png").read_bytes()

    def guardar_referencia(self, png: bytes) -> None:
        (self.out_dir / "referencia.png").write_bytes(png)


# ── servidor HTTP ─────────────────────────────────────────────────────────────

HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<title>pixel-art-replace</title><style>
body{background:#121218;color:#ebebeb;font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px}
h1{font-size:19px}h2{font-size:15px;margin:16px 0 8px}
img{image-rendering:pixelated;background:#1a1a22;border:1px solid #333;max-width:380px}
.thumb{max-width:96px;cursor:pointer;border:3px solid transparent}
.thumb.sel{border-color:#2b5bd7}
button{background:#2b5bd7;color:#fff;border:0;border-radius:6px;padding:8px 14px;margin:4px 4px 4px 0;cursor:pointer}
button.red{background:#a33}button.grn{background:#2b7a3b}button:disabled{opacity:.45;cursor:default}
textarea{width:100%;max-width:640px;background:#1c1c24;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}.col{flex:1;min-width:300px}
.bar{height:10px;background:#222;border-radius:5px;overflow:hidden;max-width:640px}.bar i{display:block;height:100%;background:#2b5bd7;width:0}
.small{color:#9aa;font-size:12px}</style></head><body>
<h1>pixel-art-replace</h1>
<p class="small">sprite ou tilesheet → análise (MiMo v2.6 Pro) → expandir → replace com referência → aprovar → ajustar tudo em paralelo</p>
<div class="row"><div class="col">
<h2>1 · Imagem (sprite ou tilesheet)</h2>
<input type="file" id="img" accept="image/*"> <button id="analisar">Analisar</button>
<p class="small" id="aninfo">–</p>
<div id="thumbs"></div>
<p class="small">clique nas sprites que quer incluir (em tilesheets)</p>
</div><div class="col">
<h2>2 · Referência + mudança</h2>
<input type="file" id="ref" accept="image/*">
<p class="small" id="refok">nenhuma referência</p>
<label>O que mudar (CHANGE):<br><textarea id="mudanca" rows="2">Redraw with a completely new outfit and look (same pose, same silhouette)</textarea></label>
<button id="gerar" class="grn">Gerar replace de prova</button>
</div></div>
<h2>3 · Aprovar ou rejeitar</h2>
<div class="row"><div><p class="small">original</p><img id="orig"></div>
<div><p class="small">gerado (tentativa <span id="tent">–</span>)</p><img id="gerada"></div></div>
<p><label>Considerações para a retentativa:<br><textarea id="cons" rows="2"></textarea></label></p>
<button id="rejeitar" class="red" disabled>Rejeitar e regerar</button>
<button id="aprovar" class="grn" disabled>Aprovar</button>
<h2>4 · Ajustar todas (paralelo)</h2>
<button id="converter" disabled>Ajustar todas as selecionadas</button>
<div class="bar"><i id="prog"></i></div><p class="small" id="progtext">–</p>
<h2>5 · Resultado</h2><div id="galeria" class="row"></div>
<script>
const $=id=>document.getElementById(id);let imgB64=null,refB64=null,selecionadas=new Set([0]);
const b64=f=>new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result.split(',')[1]);fr.readAsDataURL(f)});
$('img').onchange=async e=>{const f=e.target.files[0];if(f)imgB64=await b64(f);};
$('ref').onchange=async e=>{const f=e.target.files[0];if(f){refB64=await b64(f);$('refok').textContent='referência: '+f.name;}};
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',
  headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  const j=await r.json();if(!r.ok)throw new Error(j.erro||r.status);return j;}
function thumbs(sprites){$('thumbs').innerHTML=sprites.map(s=>
  `<img class="thumb ${selecionadas.has(s.id)?'sel':''}" data-id="${s.id}" src="/sprite/${s.id}.png">`).join('');
  document.querySelectorAll('.thumb').forEach(el=>el.onclick=()=>{const id=+el.dataset.id;
   selecionadas.has(id)?selecionadas.delete(id):selecionadas.add(id);el.classList.toggle('sel');
   api('/api/selecionar',{ids:[...selecionadas]}).catch(()=>{});});}
$('analisar').onclick=async()=>{if(!imgB64)return alert('escolha uma imagem');
  $('analisar').disabled=true;try{const r=await api('/api/analisar',{img:imgB64});
   $('aninfo').textContent=`${r.analise.tipo} · ${r.analise.tamanho[0]}x${r.analise.tamanho[1]} · ${r.analise.celulas} células`+
     (r.analise.ia&&r.analise.ia.nota?` · MiMo: ${r.analise.ia.nota}`:'');
   selecionadas=new Set(r.tipo=='tilesheet'?[0]:[0]);thumbs(r.sprites);
   $('orig').src='/sprite/0.png';$('gerar').disabled=false;}catch(e){alert('Erro: '+e.message)}
  $('analisar').disabled=false;};
$('gerar').onclick=async()=>{if(!refB64)return alert('carregue a imagem de referência');
  $('gerar').disabled=true;try{const r=await api('/api/gerar',{mudanca:$('mudanca').value});
   $('gerada').src='/ficheiros/'+r.imagem+'?t='+Date.now();$('tent').textContent=r.tentativa;
   $('orig').src='/sprite/'+r.sprite+'.png';$('rejeitar').disabled=false;$('aprovar').disabled=false;
   $('converter').disabled=true;}catch(e){alert('Erro: '+e.message)}$('gerar').disabled=false;};
$('rejeitar').onclick=async()=>{$('rejeitar').disabled=true;try{
  const r=await api('/api/gerar',{mudanca:$('mudanca').value,consideracao:$('cons').value});
  $('gerada').src='/ficheiros/'+r.imagem+'?t='+Date.now();$('tent').textContent=r.tentativa;
  $('cons').value='';}catch(e){alert('Erro: '+e.message)}$('rejeitar').disabled=false;};
$('aprovar').onclick=async()=>{try{await api('/api/aprovar',{});$('converter').disabled=false;
  $('aprovar').disabled=$('rejeitar').disabled=true;}catch(e){alert('Erro: '+e.message)}};
$('converter').onclick=async()=>{$('converter').disabled=true;
  try{await api('/api/converter',{});}catch(e){alert('Erro: '+e.message)}
  const t=setInterval(async()=>{try{await estado();}catch(e){}
   if($('prog').style.width=='100%'){clearInterval(t);resultado();}},2000);};
async function estado(){const s=await api('/api/estado');const p=s.progresso;
  $('prog').style.width=(p.total?100*p.ok/p.total:0)+'%';
  $('progtext').textContent=p.total?`${p.ok}/${p.total} ajustadas · ${p.erros} erros`:'–';}
async function resultado(){const r=await api('/api/resultado');
  $('galeria').innerHTML=(r.galeria||[]).map(g=>
   `<div><p class="small">sprite ${g.id}</p><a href="/ficheiros/${g.comparacao}" target="_blank">
    <img src="/ficheiros/${g.comparacao}"></a></div>`).join('');}
estado().catch(()=>{});
</script></body></html>"""


def fazer_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, status=200):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _erro(self, e):
            self._json({"erro": str(getattr(e, "what", None) or e)}, 500)

        def _png(self, data: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    data = HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith("/sprite/"):
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
            except Exception as e:                       # noqa: BLE001
                self._erro(e)

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


def servir(entrada: Path, out_dir: Path, *, model: str = openrouter.MODELO_IMAGEM,
           mudanca: str = "", sem_ia: bool = False, port: int = 8770,
           host: str = "127.0.0.1") -> None:
    studio = Studio(entrada, out_dir, model=model, mudanca=mudanca, sem_ia=sem_ia)
    httpd = ThreadingHTTPServer((host, port), fazer_handler(studio))
    print(f"pixel-art-replace → http://{host}:{port}/  (modelo de imagem: {studio.estado['model']})")
    print(f"entrada: {studio.entrada.name} · análise: {studio.estado['analise']['tipo']} "
          f"({studio.estado['analise']['celulas']} sprites) · Ctrl+C para sair")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
