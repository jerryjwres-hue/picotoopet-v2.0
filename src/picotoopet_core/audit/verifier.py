"""审计哈希链验证。"""

from __future__ import annotations

from picotoopet_core.db.database import Database

from .models import AuditVerification
from .writer import canonical_hash


def verify_audit_chain(database: Database) -> AuditVerification:
    """逐事件重算哈希并验证前序引用。"""

    rows = database.fetchall("SELECT * FROM audit_events ORDER BY rowid")
    previous_hash: str | None = None

    for index, row in enumerate(rows, start=1):
        payload = {
            "audit_id": row["audit_id"],
            "trace_id": row["trace_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "decision": row["decision"],
            "reason_code": row["reason_code"],
            "details_redacted_json": row["details_redacted_json"],
            "previous_hash": row["previous_hash"],
            "created_at": row["created_at"],
        }
        if row["previous_hash"] != previous_hash or canonical_hash(payload) != row["event_hash"]:
            return AuditVerification(False, index, row["audit_id"])
        previous_hash = row["event_hash"]

    return AuditVerification(True, len(rows), None)
