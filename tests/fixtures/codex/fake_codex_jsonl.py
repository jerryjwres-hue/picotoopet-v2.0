#!/usr/bin/env python3
"""CI 专用确定性 fake Codex JSONL；不联网、不读取凭据。"""

from __future__ import annotations

import json
import sys


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        return 2
    emit({"type": "thread.started", "thread_id": "fake-phase10d"})
    emit({"type": "turn.started", "turn": 1})
    emit(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "redacted-fixture-summary"},
        }
    )
    emit(
        {
            "type": "turn.completed",
            "turn": 1,
            "provider_usage_unknown": True,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
