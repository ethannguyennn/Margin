"""Revision-pinned visual references shipped with the synthetic SOP corpus."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .config import REPO_ROOT
from .pipeline.sanitize import sanitize


@lru_cache
def catalog() -> list[dict]:
    return json.loads((REPO_ROOT / "corpus/illustrations.json").read_text(encoding="utf-8"))


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key)


def _text(value: str) -> str:
    return " ".join(sanitize(value).casefold().split())


def available_graphics(chunks: list[Any]) -> list[dict]:
    by_id = {_get(c, "chunk_id"): c for c in chunks}
    available = []
    for graphic in catalog():
        references = [ref for ref in graphic["references"] if ref["chunk_id"] in by_id and
                      _text(ref["quote"]) in _text(_get(by_id[ref["chunk_id"]], "text"))]
        if references:
            available.append({"id": graphic["id"], "title": graphic["title"],
                              "references": references})
    return available


def verify_graphic(graphic_id: str, citations: list[dict], chunks: list[Any]) -> bool:
    return any(graphic["id"] == graphic_id and any(
        cite["chunk_id"] == ref["chunk_id"] and _text(ref["quote"]) in _text(cite["quote"])
        for cite in citations for ref in graphic["references"]
    ) for graphic in available_graphics(chunks))


def graphic_for_chunk(chunk: dict) -> str | None:
    available = available_graphics([chunk])
    return available[0]["id"] if available else None
