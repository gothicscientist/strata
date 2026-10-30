"""Retrieval over the Strata methods corpus and reference-library metadata.

Corpus:
* ``docs/methods/*.md`` chunked by heading (## / ###). Chunk id: ``methods/<file>#<slug>``.
* Population / publication metadata records supplied by the reference library (optional).
  Chunk id: ``population/<id>`` or ``publication/<id>``.

Retrievers: BM25 (default, no external services), optional dense retrieval through an
embedding function (+ pgvector when configured), and reciprocal-rank fusion of the two.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "which",
        "with",
        "not",
        "but",
        "can",
        "may",
        "we",
        "our",
    ]
)


def default_methods_dir() -> Path:
    env = os.environ.get("STRATA_METHODS_DIR")
    if env:
        return Path(env)
    # services/api/strata/agent/rag.py -> repo root is four parents up from the package dir.
    return Path(__file__).resolve().parents[4] / "docs" / "methods"


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "section"


@dataclass
class Chunk:
    id: str
    title: str
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_result(self, score: float, max_chars: int = 1800) -> dict[str, Any]:
        body = self.text if len(self.text) <= max_chars else self.text[:max_chars] + " ..."
        return {
            "chunk_id": self.id,
            "title": self.title,
            "source": self.source,
            "score": round(float(score), 4),
            "text": body,
        }


def chunk_markdown(path: Path, *, prefix: str = "methods") -> list[Chunk]:
    """Split a markdown file into chunks at ## and ### headings.

    The document title (# heading) is prepended to each chunk's title for context. Text above
    the first ## heading becomes an ``#overview`` chunk.
    """
    raw = path.read_text(encoding="utf-8")
    stem = path.stem
    doc_title = stem
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    buf: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*\S)\s*$", line)
        if m and len(m.group(1)) == 1:
            doc_title = m.group(2)
            continue
        if m:
            if any(s.strip() for s in buf):
                sections.append((current_title, buf))
            current_title = m.group(2)
            buf = []
            continue
        buf.append(line)
    if any(s.strip() for s in buf):
        sections.append((current_title, buf))

    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    for title, lines in sections:
        slug = slugify(title)
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        if n:
            slug = f"{slug}-{n + 1}"
        text = "\n".join(lines).strip()
        chunks.append(
            Chunk(
                id=f"{prefix}/{stem}#{slug}",
                title=f"{doc_title} - {title}",
                text=text,
                source=f"docs/methods/{path.name}",
            )
        )
    return chunks


def load_methods_corpus(directory: Path | None = None) -> list[Chunk]:
    directory = directory or default_methods_dir()
    if not directory.is_dir():
        return []
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(chunk_markdown(path))
    return chunks


def metadata_chunks(records: Iterable[dict[str, Any]]) -> list[Chunk]:
    """Turn reference-library metadata records into retrievable chunks.

    Each record needs ``kind`` ("population" or "publication") and ``id``; other keys are
    rendered as ``key: value`` lines. Only descriptive metadata belongs here, never genotypes.
    """
    out: list[Chunk] = []
    for rec in records:
        kind = str(rec.get("kind", "population"))
        rid = str(rec.get("id", "")).strip()
        if not rid:
            continue
        title = str(rec.get("name") or rec.get("title") or rid)
        lines = [
            f"{k}: {v}"
            for k, v in rec.items()
            if k not in {"kind", "id"} and v not in (None, "", [], {})
        ]
        out.append(
            Chunk(
                id=f"{kind}/{rid}",
                title=f"{kind.capitalize()}: {title}",
                text="\n".join(lines),
                source="reference-library",
                metadata={"kind": kind},
            )
        )
    return out


class BM25Retriever:
    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = list(chunks)
        docs = [tokenize(f"{c.title} {c.title} {c.text}") for c in self.chunks]
        self._bm25 = BM25Okapi(docs) if docs else None

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        if self._bm25 is None:
            return []
        q = tokenize(query)
        if not q:
            return []
        scores = self._bm25.get_scores(q)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [(self.chunks[i], float(scores[i])) for i in order[:k] if scores[i] > 0]


EmbedFn = Callable[[list[str]], list[list[float]]]


class DenseRetriever:
    """Cosine-similarity retrieval over chunk embeddings.

    With ``pg_search`` set, the query vector is sent to a pgvector-backed function
    ``(vector, k) -> [(chunk_id, similarity)]`` instead of scoring in memory.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        embed: EmbedFn,
        *,
        pg_search: Callable[[list[float], int], list[tuple[str, float]]] | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self._by_id = {c.id: c for c in self.chunks}
        self._embed = embed
        self._pg_search = pg_search
        self._vectors: list[list[float]] | None = None

    def _ensure_vectors(self) -> list[list[float]]:
        if self._vectors is None:
            texts = [f"{c.title}\n{c.text}" for c in self.chunks]
            self._vectors = self._embed(texts) if texts else []
        return self._vectors

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        qv = self._embed([query])[0]
        if self._pg_search is not None:
            hits = self._pg_search(qv, k)
            return [(self._by_id[cid], s) for cid, s in hits if cid in self._by_id]
        vecs = self._ensure_vectors()
        qn = math.sqrt(sum(x * x for x in qv)) or 1.0
        scored: list[tuple[int, float]] = []
        for i, v in enumerate(vecs):
            vn = math.sqrt(sum(x * x for x in v)) or 1.0
            scored.append((i, sum(a * b for a, b in zip(qv, v, strict=False)) / (qn * vn)))
        scored.sort(key=lambda t: (-t[1], t[0]))
        return [(self.chunks[i], s) for i, s in scored[:k]]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[tuple[Chunk, float]]], k: int = 5, c: int = 60
) -> list[tuple[Chunk, float]]:
    """Standard RRF: score(d) = sum over rankings of 1 / (c + rank)."""
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, (chunk, _) in enumerate(ranking, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (c + rank)
            chunks[chunk.id] = chunk
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [(chunks[cid], scores[cid]) for cid in order[:k]]


def openai_embedder(model: str = "text-embedding-3-small") -> EmbedFn:
    import openai

    client = openai.OpenAI()

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 256):
            resp = client.embeddings.create(model=model, input=texts[i : i + 256])
            out.extend(d.embedding for d in resp.data)
        return out

    return embed


def voyage_embedder(model: str = "voyage-3") -> EmbedFn:
    import httpx

    key_env = "VOYAGE_API_KEY"

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):
            r = httpx.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {os.environ[key_env]}"},
                json={"model": model, "input": texts[i : i + 128]},
                timeout=60,
            )
            r.raise_for_status()
            out.extend(d["embedding"] for d in r.json()["data"])
        return out

    return embed


def embedder_from_env() -> EmbedFn | None:
    """STRATA_EMBEDDINGS=openai|voyage enables dense retrieval; unset means BM25 only."""
    choice = (os.environ.get("STRATA_EMBEDDINGS") or "").lower()
    if choice == "openai" and os.environ.get("OPENAI_API_KEY"):
        return openai_embedder(os.environ.get("STRATA_EMBEDDING_MODEL", "text-embedding-3-small"))
    if choice == "voyage" and os.environ.get("VOYAGE_API_KEY"):
        return voyage_embedder(os.environ.get("STRATA_EMBEDDING_MODEL", "voyage-3"))
    return None


class KnowledgeBase:
    """Hybrid retriever facade used by the ``retrieve_knowledge`` tool."""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        embed: EmbedFn | None = None,
        pg_search: Callable[[list[float], int], list[tuple[str, float]]] | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.bm25 = BM25Retriever(self.chunks)
        self.dense = DenseRetriever(self.chunks, embed, pg_search=pg_search) if embed else None
        self._ids = {c.id for c in self.chunks}

    @classmethod
    def from_sources(
        cls,
        methods_dir: Path | None = None,
        metadata: Iterable[dict[str, Any]] | None = None,
        *,
        embed: EmbedFn | None = None,
    ) -> KnowledgeBase:
        chunks = load_methods_corpus(methods_dir)
        if metadata is not None:
            chunks.extend(metadata_chunks(metadata))
        return cls(chunks, embed=embed)

    def has(self, chunk_id: str) -> bool:
        return chunk_id in self._ids

    def search(
        self, query: str, k: int = 5, *, source: str | None = None
    ) -> list[tuple[Chunk, float]]:
        pool = max(k * 4, 20)
        sparse = self.bm25.search(query, pool)
        if self.dense is not None:
            try:
                dense = self.dense.search(query, pool)
            except Exception:  # noqa: BLE001 - dense retrieval is best-effort
                dense = []
            hits = reciprocal_rank_fusion([sparse, dense], k=pool)
        else:
            hits = sparse
        if source == "methods":
            hits = [h for h in hits if h[0].id.startswith("methods/")]
        elif source == "reference":
            hits = [h for h in hits if not h[0].id.startswith("methods/")]
        return hits[:k]


_DEFAULT_KB: KnowledgeBase | None = None


def default_knowledge_base(metadata: Iterable[dict[str, Any]] | None = None) -> KnowledgeBase:
    """Process-wide knowledge base, built lazily on first use."""
    global _DEFAULT_KB
    if _DEFAULT_KB is None:
        _DEFAULT_KB = KnowledgeBase.from_sources(metadata=metadata, embed=embedder_from_env())
    return _DEFAULT_KB


def reset_default_knowledge_base() -> None:
    global _DEFAULT_KB
    _DEFAULT_KB = None
