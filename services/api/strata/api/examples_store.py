"""Loads precomputed example analyses from data/examples/<slug>/ (real outputs of the data
pipeline with provenance). Layout: example.json, or meta.json + result.json + provenance.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
_cache: dict[Path, tuple[float, dict[str, Any]]] = {}


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def load_example(directory: Path) -> dict[str, Any] | None:
    main = directory / "example.json"
    files = [main] if main.exists() else [directory / f for f in
                                          ("meta.json", "result.json", "provenance.json")]
    existing = [f for f in files if f.exists()]
    if not existing:
        return None
    mtime = max(f.stat().st_mtime for f in existing)
    hit = _cache.get(directory)
    if hit and hit[0] == mtime:
        return hit[1]
    if main.exists():
        data = _read_json(main)
    else:
        data = {}
        for f in existing:
            body = _read_json(f)
            if f.name == "meta.json":
                data.update(body)
            else:
                data[f.stem] = body
    if not isinstance(data, dict) or "result" not in data:
        return None
    data.setdefault("slug", directory.name)
    data.setdefault("title", directory.name.replace("-", " ").title())
    data.setdefault("summary", "")
    res = data["result"] if isinstance(data["result"], dict) else {}
    data.setdefault("kind", res.get("type") or data.get("analysis_kind") or "unknown")
    data.setdefault("result_kind", res.get("kind", "exploratory"))
    _cache[directory] = (mtime, data)
    return data


def list_examples(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and _SLUG.match(p.name)):
        try:
            ex = load_example(d)
        except (OSError, ValueError):
            continue
        if ex is not None:
            out.append(ex)
    return out


def get_example(root: Path, slug: str) -> dict[str, Any] | None:
    if not _SLUG.match(slug):
        return None
    d = root / slug
    return load_example(d) if d.is_dir() else None
