"""Packaged Worker verification must accept only explicitly registered autonomous task types."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command"
WORKER_LIB = ROOT / "deploy/macos/phase23-worker/worker-lib.sh"
FIXTURE = ROOT / "scripts/mac/phase23-worker/Test-MacWorkerSliceCFixture.sh"

_AUTONOMOUS_TASK_TYPES = (
    "autonomous.local_analysis.v1",
    "autonomous.discovery.v1",
    "autonomous.storage_maintenance.v1",
)


def test_packaged_worker_verifier_accepts_explicit_autonomous_task_types() -> None:
    sources = [
        WORKER_LIB.read_text(encoding="utf-8"),
        VERIFY.read_text(encoding="utf-8"),
        FIXTURE.read_text(encoding="utf-8"),
    ]

    for task_type in _AUTONOMOUS_TASK_TYPES:
        for source in sources:
            assert task_type in source


def test_packaged_worker_verifier_never_allows_autonomous_wildcard() -> None:
    sources = [
        WORKER_LIB.read_text(encoding="utf-8"),
        VERIFY.read_text(encoding="utf-8"),
        FIXTURE.read_text(encoding="utf-8"),
    ]

    for source in sources:
        assert '"autonomous.*"' not in source
        assert "startswith(\"autonomous.\")" not in source
