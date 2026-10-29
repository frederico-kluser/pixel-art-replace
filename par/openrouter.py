"""Cliente OpenRouter: análise com o MiMo v2.6 Pro e geração de imagem com o melhor modelo.

Formato confirmado ao vivo (2026-10):
- texto+imagem: `POST /chat/completions` com content parts `{"type":"image_url","image_url":{"url":"data:…"}}`;
- geração de imagem: `modalities:["image","text"]` e as imagens saem em `message.images[].image_url.url`
  (data URI);
- ARMADILHA: o array `models` (fallbacks) só aceita **3 itens** no total — HTTP 400
  "'models' array must have 3 items or fewer".
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .util import ParError

API = "https://openrouter.ai/api/v1/chat/completions"
API_IMAGENS = "https://openrouter.ai/api/v1/images"
MODELO_ANALISE = "xiaomi/mimo-v2.6-pro"                  # o MiMo analisa a imagem (sprite vs tilesheet)

# 3 CAMPEÕES (estudo 2026-10, benchmark próprio em trabalho-ken/benchmark.json):
#   riverflow-v2.5-pro  — #1 em qualidade/edição (77/81), juiz interno · /images (limite 4.5 MB)
#   gpt-image-2.5-flare — #2 global (75/81), lote rápido (P50 13 s)        · /images
#   gpt-image-2         — #3 global (74/81), #1 em Minimal Diff (2/3)      · /images
MODELOS = {
    "sourceful/riverflow-v2.5-pro": {"endpoint": "images",
                                     "params": {"output_format": "png", "aspect_ratio": "1:1"}},
    "openai/gpt-image-2.5-flare": {"endpoint": "images",
                                   "params": {"output_format": "png", "quality": "auto", "size": "1024x1024"}},
    "openai/gpt-image-2": {"endpoint": "images",
                           "params": {"output_format": "png", "quality": "high", "size": "1024x1024"}},
    "openai/gpt-5.4-image-2": {"endpoint": "chat", "params": {}},
    "google/gemini-nano-banana-2.1": {"endpoint": "chat", "params": {}},
    "google/gemini-3-pro-image": {"endpoint": "chat", "params": {}},
    "google/gemini-3.1-flash-image": {"endpoint": "chat", "params": {}},
}
MODELO_IMAGEM = "openai/gpt-image-2"                      # confirmado pelo benchmark (critérios: aferição)
FALLBACK_IMAGEM = ["openai/gpt-image-2.5-flare", "sourceful/riverflow-v2.5-pro"]
RETRIES = 4

ERROS = {
    401: "chave OpenRouter inválida/revogada — Solução: ver https://openrouter.ai/settings/keys",
    402: "créditos insuficientes — Solução: adicione créditos em https://openrouter.ai/credits",
    404: "modelo indisponível — Solução: use --model com outro id do catálogo (/models?output_modalities=image)",
    429: "rate limit — Solução: o cliente já retenta com backoff; aguarde ou troque de modelo",
    503: "sem provider disponível — Solução: tente de novo em instantes",
}


def openrouter_key() -> str:
    """Chave da conta: ambiente → ~/.dsh/.credentials.yaml (nunca se pede se já existe)."""
    import os
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    if cred.exists():
        m = re.search(r"OPENROUTER_API_KEY:\s*(\S+)", cred.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    raise ParError("sem OPENROUTER_API_KEY", "guarde a chave (sk-or-v1-…) em ~/.dsh/.credentials.yaml ou no ambiente")


def data_uri(img: bytes, tipo: str = "image/png") -> str:
    return f"data:{tipo};base64," + base64.b64encode(img).decode()


def parse_data_uri(url: str) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def _post(body: dict, api_key: str | None = None, url: str = API) -> dict:
    key = api_key or openrouter_key()
    ultimo = ""
    for tentativa in range(RETRIES):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/frederico-kluser/pixel-art-replace",
            "X-OpenRouter-Title": "pixel-art-replace",
        })
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detalhe = ""
            try:
                detalhe = str(json.loads(e.read()).get("error", {}).get("message", ""))[:160]
            except Exception as e2:                        # noqa: BLE001 - corpo não-JSON é comum em gateways
                detalhe = f"(sem detalhe: {type(e2).__name__})"
            ultimo = ERROS.get(e.status, f"HTTP {e.status}") + (f" — {detalhe}" if detalhe else "")
            if e.status in (429, 500, 502, 503, 520, 522, 524):
                time.sleep(min(float(e.headers.get("Retry-After") or 2 ** tentativa * 5), 60))
                continue
            raise ParError(f"OpenRouter recusou: {ultimo}", "corrija e repita; nada foi gasto desta vez") from None
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo = f"rede: {e}"
            time.sleep(2 ** tentativa * 3)
    raise ParError(f"OpenRouter falhou após {RETRIES} tentativas: {ultimo}", "tente mais tarde ou troque o modelo")


def analisar_ia(png: bytes, *, model: str = MODELO_ANALISE, api_key: str | None = None) -> dict:
    """O MiMo v2.6 Pro analisa a imagem e classifica: sprite única ou tilesheet (com grelha estimada)."""
    prompt = ("Analise esta imagem de pixel art. Ela é UMA SPRITE única (um só personagem/objeto) "
              "ou uma TILESHEET (uma grelha de várias sprites/células)?\n"
              'Responda APENAS com JSON: {"tipo": "sprite"|"tilesheet", "colunas": <int>, "linhas": <int>, '
              '"celula": [w, h], "confianca": 0.0-1.0, "nota": "<uma frase>"}')
    body = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_uri(png)}}]}]}
    resp = _post(body, api_key)
    texto = (resp.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        raise ParError("o modelo não devolveu JSON na análise", "repita; se insistir use --sem-ia (só algoritmo)")
    try:
        out = json.loads(m.group(0))
        out.setdefault("tipo", "sprite")
        out["modelo"] = resp.get("model", model)
        return out
    except json.JSONDecodeError as e:
        raise ParError(f"JSON de análise inválido: {e}", "repita a análise") from None


def _comprimir_refs(imagens: list[bytes], limite: int = 3_500_000) -> list[bytes]:
    """Guarda de payload: alguns providers (Sourceful) impõem ~4.5 MB por pedido. Se o total em base64
    passar o limite, as imagens são reduzidas para ≤1024 px e reencodadas em JPEG (só a referência)."""
    total = sum(len(base64.b64encode(i)) for i in imagens)
    if total <= limite:
        return imagens
    from io import BytesIO

    from PIL import Image
    out = []
    for img in imagens:
        if len(base64.b64encode(img)) < 700_000:
            out.append(img)
            continue
        im = Image.open(BytesIO(img)).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=85)
        out.append(buf.getvalue())
    return out


def _gerar_images(prompt: str, imagens: list[bytes], modelo: str,
                  api_key: str | None = None, stats: dict | None = None) -> tuple[bytes, str]:
    """Endpoint DEDICADO de imagens: input_references + output_format png. Cobre os campeões
    (riverflow, gpt-image-2, flare…). Faturação all-or-nothing: erro não cobra."""
    cfg = MODELOS.get(modelo, {"params": {"output_format": "png"}})
    refs = [{"type": "image_url", "image_url": {"url": data_uri(i)}} for i in _comprimir_refs(imagens)]
    body = {"model": modelo, "prompt": prompt, "input_references": refs,
            **cfg.get("params", {})}
    resp = _post(body, api_key, url=API_IMAGENS)
    if stats is not None:
        stats.update({"cost": (resp.get("usage") or {}).get("cost"), "usage": resp.get("usage")})
    itens = resp.get("data") or []
    if not itens:
        raise ParError(f"resposta sem imagem: {str(resp)[:200]}",
                       "confirme o modelo no catálogo (/models?output_modalities=image)")
    d = itens[0]
    if d.get("b64_json"):
        return base64.b64decode(d["b64_json"]), resp.get("model", modelo)
    if d.get("url"):
        return parse_data_uri(d["url"]), resp.get("model", modelo)
    raise ParError("resposta de imagem sem conteúdo", "repita; se persistir troque de modelo")


def _gerar_chat(prompt: str, imagens: list[bytes], modelo: str, extra_models: list[str] | None,
                api_key: str | None = None, stats: dict | None = None) -> tuple[bytes, str]:
    """Endpoint /chat/completions com modalities image+text (famílias Google e gpt-5.4-image)."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": data_uri(img)}} for img in imagens]
    body = {"model": modelo, "modalities": ["image", "text"],
            "messages": [{"role": "user", "content": content}]}
    if extra_models:
        body["models"] = ([modelo] + [m for m in extra_models if m != modelo])[:3]   # teto do OpenRouter: 3
    resp = _post(body, api_key)
    if stats is not None:
        stats.update({"cost": (resp.get("usage") or {}).get("cost"), "usage": resp.get("usage")})
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ParError(f"resposta inesperada do OpenRouter: {str(resp)[:200]}",
                       "confirme que o modelo gera imagem (output_modalities=image)") from None
    if msg.get("images"):
        url = msg["images"][0].get("image_url", {}).get("url") or msg["images"][0].get("url")
        if url:
            return parse_data_uri(url), resp.get("model", modelo)
    if isinstance(msg.get("content"), list):
        for part in msg["content"]:
            if part.get("type") == "image_url":
                return parse_data_uri(part["image_url"]["url"]), resp.get("model", modelo)
    raise ParError("resposta sem imagem (o modelo só descreveu?)",
                   'confirme modalities:["image","text"] e que o modelo gera imagem')


def gerar_imagem(prompt: str, imagens: list[bytes], *, model: str = MODELO_IMAGEM,
                 extra_models: list[str] | None = FALLBACK_IMAGEM, api_key: str | None = None) -> tuple[bytes, str]:
    """Gera/edita imagem. Cada modelo vai pelo SEU endpoint (chat ou /images); os fallbacks tentam-se
    em sequência. Devolve (png, modelo_efetivo)."""
    candidatos = [model] + [m for m in (extra_models or []) if m != model]
    erros = []
    for modelo in candidatos:
        cfg = MODELOS.get(modelo, {"endpoint": "chat", "params": {}})
        try:
            if cfg["endpoint"] == "images":
                return _gerar_images(prompt, imagens, modelo, api_key)
            return _gerar_chat(prompt, imagens, modelo,
                               [m for m in candidatos if m != modelo][:2] if model == modelo else None,
                               api_key)
        except ParError as e:
            erros.append(f"{modelo}: {e.args[0] if e.args else e}")
    raise ParError("todos os modelos falharam — " + " · ".join(erros)[:400],
                   "verifique créditos/rate limit e o catálogo de modelos")
