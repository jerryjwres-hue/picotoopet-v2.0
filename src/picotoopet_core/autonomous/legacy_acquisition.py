"""Safe deterministic acquisition primitives migrated from Maotai OS 4.1."""

from __future__ import annotations

import math
import re

_WHITESPACE_RE = re.compile(r"\s+")
_MAX_QUERY_CHARS = 240
_MAX_DISCOVERY_QUERIES = 4
_QUERY_INTENTS = (
    "consumer pain points reviews recent",
    "creator content trends high engagement recent",
    "comparison purchase intent recent",
    "recent discussions",
)


def adaptive_interval_minutes(*, base_minutes: int, change_rate: float, failure_count: int) -> int:
    """Port the bounded 4.1 acquisition cadence without importing its scheduler or database."""

    base = max(15, int(base_minutes))
    failures = max(0, int(failure_count))
    if failures:
        # Legacy behavior caps exponential retry growth after six doublings and
        # never lets a failed source sleep longer than 30 days.
        return min(60 * 24 * 30, base * (2 ** min(failures, 6)))

    rate = max(0.0, min(1.0, float(change_rate)))
    if rate >= 0.5:
        return max(60, int(base * 0.5))
    if rate <= 0.05:
        return min(60 * 24 * 14, max(base + 60, int(base * 2.0)))
    return base


def information_gain_score(*, products: int, signals: int, opportunities: int) -> float:
    """Return the legacy monotonic gain score without treating it as factual evidence."""

    product_count = max(0, int(products))
    signal_count = max(0, int(signals))
    opportunity_count = max(0, int(opportunities))
    score = (
        math.log1p(product_count) * 2.0
        + math.log1p(signal_count)
        + opportunity_count * 1.5
    )
    return round(score, 4)


def build_discovery_queries(objective: str, *, max_queries: int = 4) -> tuple[str, ...]:
    """Expand one human objective into a tiny deterministic, tool-first search plan."""

    normalized = _normalize_objective(objective)
    limit = max(1, min(int(max_queries), _MAX_DISCOVERY_QUERIES))
    queries: list[str] = []
    for intent in _QUERY_INTENTS:
        query = _bounded_query(normalized, intent)
        if query not in queries:
            queries.append(query)
        if len(queries) >= limit:
            break
    return tuple(queries)


def _normalize_objective(objective: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", str(objective or "").strip())
    if not normalized:
        normalized = "current product and content opportunity"
    return normalized


def _bounded_query(objective: str, intent: str) -> str:
    suffix = f" {intent}"
    available = max(1, _MAX_QUERY_CHARS - len(suffix))
    objective_part = objective[:available].rstrip()
    query = f"{objective_part}{suffix}".strip()
    return query[:_MAX_QUERY_CHARS].rstrip()
