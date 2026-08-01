from pathlib import Path

from picotoopet_core.audit.verifier import verify_audit_chain
from picotoopet_core.audit.writer import AuditWriter
from picotoopet_core.db.database import Database


def test_audit_chain_redacts_secret_and_detects_tampering(tmp_path: Path) -> None:
    """审计链不得泄露秘密，且任意篡改都必须可检测。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    writer = AuditWriter(database)

    writer.append(
        trace_id="trace-1",
        actor_type="mac_agent",
        actor_id="core",
        action="task.create",
        resource_type="task",
        resource_id="task-1",
        decision="allow",
        reason_code=None,
        details={"api_token": "secret-value", "safe": "ok"},
    )
    writer.append(
        trace_id="trace-2",
        actor_type="mcp_tool",
        actor_id="create_report",
        action="result.create",
        resource_type="result",
        resource_id="result-1",
        decision="allow",
        reason_code=None,
        details={"count": 1},
    )

    assert verify_audit_chain(database).valid is True
    stored = database.scalar("SELECT details_redacted_json FROM audit_events ORDER BY created_at LIMIT 1")
    assert "secret-value" not in stored
    assert "***REDACTED***" in stored

    database.execute(
        "UPDATE audit_events SET action = 'tampered' WHERE resource_id = 'task-1'"
    )
    assert verify_audit_chain(database).valid is False
    database.close()
