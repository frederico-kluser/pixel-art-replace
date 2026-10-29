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
MODELO_ANALISE = "xiaomi/mimo-v2.6-pro"                  # o MiMo analisa a imagem (sprite vs tilesheet)
MODELO_IMAGEM = "google/gemini-3-pro-image"              # melhor modelo de imagem: edição com referências, 4K
FALLBACK_IMAGEM = ["google/gemini-3.1-flash-image", "google/gemini-nano-banana-2.1"]
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


def _post(body: dict, api_key: str | None = None) -> dict:
    key = api_key or openrouter_key()
    ultimo = ""
    for tentativa in range(RETRIES):
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
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
            if e.status in (429, 500, 502, 503):
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


def gerar_imagem(prompt: str, imagens: list[bytes], *, model: str = MODELO_IMAGEM,
                 extra_models: list[str] | None = FALLBACK_IMAGEM, api_key: str | None = None) -> tuple[bytes, str]:
    """Gera/edita imagem: modalities image+text. Devolve (png, modelo_efetivo)."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": data_uri(img)}} for img in imagens]
    body = {"model": model, "modalities": ["image", "text"],
            "messages": [{"role": "user", "content": content}]}
    if extra_models:
        body["models"] = ([model] + [m for m in extra_models if m != model])[:3]   # teto do OpenRouter: 3
    resp = _post(body, api_key)
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ParError(f"resposta inesperada do OpenRouter: {str(resp)[:200]}",
                       "confirme que o modelo gera imagem (output_modalities=image)") from None
    if msg.get("images"):
        url = msg["images"][0].get("image_url", {}).get("url") or msg["images"][0].get("url")
        if url:
            return parse_data_uri(url), resp.get("model", model)
    if isinstance(msg.get("content"), list):
        for part in msg["content"]:
            if part.get("type") == "image_url":
                return parse_data_uri(part["image_url"]["url"]), resp.get("model", model)
    raise ParError("resposta sem imagem (o modelo só descreveu?)",
                   'confirme modalities:["image","text"] e que o modelo gera imagem')
