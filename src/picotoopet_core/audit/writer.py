"""追加式审计写入器。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from picotoopet_core.db.database import Database

_SECRET_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")


def redact_details(value: Any, key: str = "") -> Any:
    """递归移除可能包含秘密的字段值。"""

    if any(marker in key.lower() for marker in _SECRET_MARKERS):
        return "***REDACTED***"
    if isinstance(value, dict):
        return {str(item_key): redact_details(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_details(item) for item in value]
    if isinstance(value, tuple):
        return [redact_details(item) for item in value]
    return value


def canonical_hash(payload: dict[str, Any]) -> str:
    """对规范化 JSON 计算 SHA-256。"""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


class AuditWriter:
    """将安全脱敏后的事件追加到哈希链。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def append(
        self,
        *,
        trace_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        decision: str,
        reason_code: str | None,
        details: dict[str, Any],
    ) -> str:
        """追加事件并返回审计 ID。"""

        audit_id       = str(uuid4())
        created_at     = datetime.now(UTC).isoformat()
        redacted       = redact_details(details)
        details_json   = json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        with self.database.transaction() as connection:
            previous_row = connection.execute(
                "SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            previous_hash = None if previous_row is None else previous_row[0]
            hash_payload = {
                "audit_id": audit_id,
                "trace_id": trace_id,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "decision": decision,
                "reason_code": reason_code,
                "details_redacted_json": details_json,
                "previous_hash": previous_hash,
                "created_at": created_at,
            }
            event_hash = canonical_hash(hash_payload)
            connection.execute(
                """
                INSERT INTO audit_events(
                    audit_id, trace_id, actor_type, actor_id, action,
                    resource_type, resource_id, decision, reason_code,
                    details_redacted_json, previous_hash, event_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    trace_id,
                    actor_type,
                    actor_id,
                    action,
                    resource_type,
                    resource_id,
                    decision,
                    reason_code,
                    details_json,
                    previous_hash,
                    event_hash,
                    created_at,
                ),
            )
        return audit_id
