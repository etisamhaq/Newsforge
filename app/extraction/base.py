"""Extraction strategy interface, registry and field merging.

A strategy inspects a page and proposes values for any subset of ARTICLE_FIELDS, each with a
confidence in [0, 1]. The pipeline merges proposals field-by-field, picking the best-scored
candidate. To add a strategy: subclass `ExtractionStrategy` and `registry.register(...)` it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from selectolax.lexbor import LexborHTMLParser as HTMLParser

ARTICLE_FIELDS = (
    "title", "body", "authors", "published_at", "modified_at", "description", "image_url",
    "category", "tags", "language", "canonical_url", "site_name",
)


@dataclass
class ExtractionContext:
    url: str
    html: str
    headers: dict[str, str] = field(default_factory=dict)
    _tree: HTMLParser | None = None
    # Shared scratch space so strategies can reuse each other's work (e.g. parsed JSON-LD).
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def tree(self) -> HTMLParser:
        if self._tree is None:
            self._tree = HTMLParser(self.html)
        return self._tree


@dataclass
class Candidate:
    value: Any
    confidence: float
    source: str


@dataclass
class StrategyResult:
    strategy: str
    fields: dict[str, Candidate] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    def add(self, name: str, value: Any, confidence: float) -> None:
        if name not in ARTICLE_FIELDS:
            raise KeyError(name)
        if value is None or value == "" or value == []:
            return
        self.fields[name] = Candidate(value, max(0.0, min(1.0, confidence)), self.strategy)


class ExtractionStrategy(ABC):
    name: str = "base"
    # Lower runs first. Fallback strategies run only when confidence stays low.
    priority: int = 100
    is_fallback: bool = False

    @abstractmethod
    async def extract(self, ctx: ExtractionContext, merged: dict[str, Candidate]) -> StrategyResult: ...

    def enabled(self) -> bool:
        return True


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, ExtractionStrategy] = {}

    def register(self, strategy: ExtractionStrategy, *, replace: bool = False) -> ExtractionStrategy:
        if strategy.name in self._strategies and not replace:
            raise ValueError(f"strategy {strategy.name!r} already registered")
        self._strategies[strategy.name] = strategy
        return strategy

    def unregister(self, name: str) -> None:
        self._strategies.pop(name, None)

    def get(self, name: str) -> ExtractionStrategy | None:
        return self._strategies.get(name)

    def primary(self) -> list[ExtractionStrategy]:
        return sorted((s for s in self._strategies.values() if not s.is_fallback and s.enabled()), key=lambda s: s.priority)

    def fallbacks(self) -> list[ExtractionStrategy]:
        return sorted((s for s in self._strategies.values() if s.is_fallback and s.enabled()), key=lambda s: s.priority)

    def names(self) -> list[str]:
        return list(self._strategies)


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0


def candidate_score(name: str, cand: Candidate, all_cands: list[Candidate]) -> float:
    """Score used to choose between candidates of the same field."""
    if name == "body":
        longest = max((word_count(c.value) for c in all_cands), default=0) or 1
        # A body much shorter than the longest alternative is likely a teaser/summary.
        return cand.confidence * min(1.0, word_count(cand.value) / longest) ** 0.5
    return cand.confidence


def merge_results(results: list[StrategyResult]) -> dict[str, Candidate]:
    by_field: dict[str, list[Candidate]] = {}
    for r in results:
        for name, cand in r.fields.items():
            by_field.setdefault(name, []).append(cand)
    merged: dict[str, Candidate] = {}
    for name, cands in by_field.items():
        # stable: earlier (higher-priority) strategies win ties
        merged[name] = max(cands, key=lambda c: candidate_score(name, c, cands))
    return merged
