#!/usr/bin/env python3
"""Deterministic child-process fixture for isolated local-model runner tests."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def _bump_counter(path: Path | None) -> int:
    """Persist attempt count across child processes without shared in-memory state."""

    if path is None:
        return 1
    previous = int(path.read_text(encoding="utf-8")) if path.exists() else 0
    current  = previous + 1
    path.write_text(str(current), encoding="utf-8")
    return current


def _result_document() -> dict[str, object]:
    return {
        "summary": "fixture-result",
        "confidence": 0.81,
        "findings": ["bounded finding"],
        "recommended_actions": ["bounded action"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--counter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request_path = Path(args.request)
    output_path  = Path(args.output)
    counter_path = Path(args.counter) if args.counter else None

    # ── Force the parent to supply a real request file instead of leaking prompt text in argv. ──
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request.get("prompt"), str):
        return 9

    attempt = _bump_counter(counter_path)
    if args.mode == "hang":
        time.sleep(60)
        return 0
    if args.mode == "fail":
        return 7
    if args.mode == "fail-once" and attempt == 1:
        return 7
    if args.mode == "missing":
        return 0
    if args.mode == "invalid-json":
        output_path.write_text("{not-json", encoding="utf-8")
        return 0
    if args.mode == "oversized":
        output_path.write_bytes(b"x" * (512 * 1024))
        return 0
    if args.mode != "success" and args.mode != "fail-once":
        return 8

    output_path.write_text(
        json.dumps(_result_document(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
