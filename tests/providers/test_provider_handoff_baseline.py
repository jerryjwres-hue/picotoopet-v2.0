from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.queue.repository import QueueRepository


EXPECTED_PROVIDER_BASE_REF = "feature/autonomous-intelligence-e2e-goal-center-2.3.27.1"
EXPECTED_PROVIDER_BASE_COMMIT = "423f14ea549a3303137f4ab5ad99d2afb60dbded"


def test_coding_provider_handoffs_use_current_frugal_runtime_baseline(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    approvals = HandoffApprovalService(database, QueueRepository(database))
    handoffs = HandoffService(database, approvals)

    templates = {template.provider: template for template in handoffs.templates()}

    for provider in ("codex", "claude_code"):
        template = templates[provider]
        assert template.base_ref == EXPECTED_PROVIDER_BASE_REF
        assert template.base_commit == EXPECTED_PROVIDER_BASE_COMMIT

    database.close()
