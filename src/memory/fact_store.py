"""
A tiny durable-fact store used by Labs 02, 04, and 05.

Why a sidecar instead of only ADK state?
  ADK state prefixes teach *scope*. Write-policy, supersession, and eval need a
  store that can hold many atomic facts with provenance and tombstones. Keeping
  that logic in one place lets every lab share the same vocabulary:

    ADD / UPDATE / DELETE(tombstone) / NOOP
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# Default MiniLM model: small, fast, good enough for fact-neighbour retrieval.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Soft floor for search(). Prefer top-k ranking for reconcile — a hard mid
# threshold drops true neighbours on paraphrase and keeps false ones on short
# "Ada …" sentences at similar scores. Use 0.0 so callers always get top-k;
# the LLM (or a scored prompt) decides ADD vs supersede.
DEFAULT_SIMILARITY_THRESHOLD = 0.0


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Fact:
    text: str
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    importance: float = 0.5
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    provenance: str = ""
    superseded: bool = False
    superseded_by: str | None = None
    superseded_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class FactStore:
    """In-process fact store with supersession-not-deletion."""

    def __init__(
        self,
        *,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._facts: dict[str, Fact] = {}
        self._embedding_model_name = embedding_model
        self.similarity_threshold = similarity_threshold
        self._encoder: SentenceTransformer | None = None
        # Cache keyed by fact id; dropped whenever that fact's text changes.
        self._embeddings: dict[str, object] = {}

    def __len__(self) -> int:
        return len(self._facts)

    def _get_encoder(self) -> SentenceTransformer:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self._embedding_model_name)
        return self._encoder

    def _embed(self, texts: list[str]):
        return self._get_encoder().encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

    def _embedding_for(self, fact: Fact):
        cached = self._embeddings.get(fact.id)
        if cached is not None:
            return cached
        vec = self._embed([fact.text])[0]
        self._embeddings[fact.id] = vec
        return vec

    def _drop_embedding(self, fact_id: str) -> None:
        self._embeddings.pop(fact_id, None)

    def all(self, *, include_superseded: bool = False) -> list[Fact]:
        facts = list(self._facts.values())
        if not include_superseded:
            facts = [f for f in facts if not f.superseded]
        return sorted(facts, key=lambda f: f.updated_at)

    def add(
        self,
        text: str,
        *,
        importance: float = 0.5,
        provenance: str = "",
    ) -> Fact:
        fact = Fact(text=text, importance=importance, provenance=provenance)
        self._facts[fact.id] = fact
        return fact

    def update(
        self,
        fact_id: str,
        new_text: str,
        *,
        importance: float = 0.5,
        provenance: str = "",
    ) -> Fact:
        """
        Replace a fact while keeping audit history.

        In-place rewrite would erase prior wording (e.g. "drinks tea"). Instead we
        tombstone ``fact_id`` and ADD a successor — same scar as DELETE+ADD.
        """
        successor = self.add(
            new_text, importance=importance, provenance=provenance
        )
        self.invalidate(fact_id, superseded_by=successor.id)
        return successor

    def invalidate(self, fact_id: str, *, superseded_by: str) -> Fact:
        """Tombstone a fact. History remains; retrieval should skip it by default."""
        fact = self._facts[fact_id]
        fact.superseded = True
        fact.superseded_by = superseded_by
        fact.superseded_at = _utcnow()
        fact.updated_at = fact.superseded_at
        return fact

    def search_scored(
        self,
        query: str,
        *,
        k: int = 5,
        include_superseded: bool = False,
        threshold: float | None = None,
    ) -> list[tuple[float, Fact]]:
        """Like ``search``, but returns ``(cosine_similarity, fact)`` pairs."""
        facts = self.all(include_superseded=include_superseded)
        if not facts:
            return []

        floor = self.similarity_threshold if threshold is None else threshold
        query_vec = self._embed([query])[0]
        scored: list[tuple[float, Fact]] = []
        for fact in facts:
            score = float(query_vec @ self._embedding_for(fact))
            if score >= floor:
                scored.append((score, fact))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        include_superseded: bool = False,
        threshold: float | None = None,
    ) -> list[Fact]:
        """
        Semantic neighbour retrieval via a sentence-transformer embedding.

        Returns the top-``k`` facts by cosine similarity (L2-normalised vectors).
        ``threshold`` drops weak hits; default is 0.0 so reconcile always sees
        near neighbours when the store is non-empty (LLM decides ADD vs supersede).
        """
        return [
            fact
            for _, fact in self.search_scored(
                query,
                k=k,
                include_superseded=include_superseded,
                threshold=threshold,
            )
        ]

    def render_for_prompt(self, facts: Iterable[Fact]) -> str:
        lines = [f"- ({f.id}) {f.text}" for f in facts]
        return "\n".join(lines) if lines else "(no memories)"

    def snapshot(self) -> list[dict]:
        return [f.to_dict() for f in self.all(include_superseded=True)]
