"""审计模型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuditVerification:
    valid: bool
    checked_events: int
    failed_audit_id: str | None = None
