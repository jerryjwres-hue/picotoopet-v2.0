from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.db.database import Database
from picotoopet_core.providers.models import ProviderReadinessStatus
from picotoopet_core.providers.readiness import ProviderReadinessProjection


def _projection(tmp_path: Path) -> tuple[Database, CapabilityRouter, ProviderReadinessProjection]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database), stale_after=timedelta(seconds=60))
    return database, router, ProviderReadinessProjection(router)


def test_worker_projection_publishes_only_redacted_status_facts(tmp_path: Path) -> None:
    database, router, projection = _projection(tmp_path)

    codex = projection.publish(
        worker_id="mac-worker-a",
        provider="codex",
        status=ProviderReadinessStatus.READY,
        task_type="provider.codex.handoff-v1",
    )
    claude = projection.publish(
        worker_id="mac-worker-a",
        provider="claude_code",
        status=ProviderReadinessStatus.NOT_AUTHENTICATED,
        task_type="provider.claude-code.handoff-v1",
    )

    assert codex.healthy is True
    assert claude.healthy is False
    assert codex.metadata == {
        "runtime": "mac-worker",
        "provider": "codex",
        "readiness": "ready",
    }
    assert claude.metadata == {
        "runtime": "mac-worker",
        "provider": "claude_code",
        "readiness": "not_authenticated",
    }
    serialized = str(router.list()).lower()
    for forbidden in ("token", "cookie", "credential", "stdout", "stderr", "executable"):
        assert forbidden not in serialized
    database.close()


def test_core_projection_reads_fresh_status_and_stale_is_unavailable(tmp_path: Path) -> None:
    database, router, projection = _projection(tmp_path)
    now = datetime(2026, 8, 19, 3, 30, tzinfo=UTC)

    router.register(
        CapabilityRegistration(
            worker_id="stale-worker",
            capability=projection.capability_for("codex"),
            task_types=["provider.codex.handoff-v1"],
            healthy=True,
            metadata={
                "runtime": "mac-worker",
                "provider": "codex",
                "readiness": "ready",
            },
            heartbeat_at=now - timedelta(seconds=61),
        )
    )
    assert projection.status("codex", now=now) is ProviderReadinessStatus.UNAVAILABLE

    projection.publish(
        worker_id="fresh-worker",
        provider="claude_code",
        status=ProviderReadinessStatus.POLICY_BLOCKED,
        task_type="provider.claude-code.handoff-v1",
        heartbeat_at=now,
    )
    assert projection.status("claude_code", now=now) is ProviderReadinessStatus.POLICY_BLOCKED
    database.close()


def test_core_services_read_projection_instead_of_running_provider_cli() -> None:
    root = Path(__file__).resolve().parents[2]
    services = (root / "src/picotoopet_core/services.py").read_text(encoding="utf-8")

    assert "ProviderReadinessProjection" in services
    assert "readiness_by_provider=provider_readiness.status" in services
    assert "CodexReadinessProbe(settings.codex_executable)" not in services
