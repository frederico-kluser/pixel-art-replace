"""Utilitários: erros no formato `Erro: … — Solução: …` e JSON com UTF-8."""

from __future__ import annotations

import json
from pathlib import Path


class ParError(Exception):
    def __init__(self, what: str, fix: str = ""):
        super().__init__(f"Erro: {what}" + (f" — Solução: {fix}" if fix else ""))
        self.what, self.fix = what, fix


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n",
                          encoding="utf-8", newline="\n")
