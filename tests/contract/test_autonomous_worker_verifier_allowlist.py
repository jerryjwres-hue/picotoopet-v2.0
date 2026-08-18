"""Packaged Worker verification must accept only the explicitly registered autonomous task types."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command"
WORKER_LIB = ROOT / "deploy/macos/phase23-worker/worker-lib.sh"

_AUTONOMOUS_TASK_TYPES = (
    "autonomous.local_analysis.v1",
    "autonomous.discovery.v1",
    "autonomous.storage_maintenance.v1",
)


def test_packaged_worker_verifier_accepts_explicit_autonomous_task_types() -> None:
    verify_source = VERIFY.read_text(encoding="utf-8")
    worker_lib_source = WORKER_LIB.read_text(encoding="utf-8")

    for task_type in _AUTONOMOUS_TASK_TYPES:
        assert task_type in worker_lib_source
        assert task_type in verify_source


def test_packaged_worker_verifier_never_allows_autonomous_wildcard() -> None:
    verify_source = VERIFY.read_text(encoding="utf-8")
    worker_lib_source = WORKER_LIB.read_text(encoding="utf-8")

    assert '"autonomous.*"' not in verify_source
    assert '"autonomous.*"' not in worker_lib_source
    assert "startswith(\"autonomous.\")" not in verify_source
    assert "startswith(\"autonomous.\")" not in worker_lib_source
