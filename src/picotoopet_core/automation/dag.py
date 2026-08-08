"""Deterministic DAG validation for durable workflows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def topological_order(graph: Mapping[str, Iterable[str]]) -> list[str]:
    """Return deterministic topological order and reject malformed dependency graphs."""

    normalized = {key: tuple(dependencies) for key, dependencies in graph.items()}
    keys = set(normalized)
    for key, dependencies in normalized.items():
        if key in dependencies:
            raise ValueError(f"self dependency is not allowed: {key}")
        missing = sorted(set(dependencies) - keys)
        if missing:
            raise ValueError(f"missing workflow dependency for {key}: {', '.join(missing)}")

    indegree = {key: len(set(dependencies)) for key, dependencies in normalized.items()}
    children: dict[str, set[str]] = {key: set() for key in normalized}
    for key, dependencies in normalized.items():
        for dependency in dependencies:
            children[dependency].add(key)

    ready = sorted(key for key, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()

    if len(ordered) != len(normalized):
        cyclic = sorted(key for key, degree in indegree.items() if degree > 0)
        raise ValueError(f"workflow dependency cycle detected: {', '.join(cyclic)}")
    return ordered
