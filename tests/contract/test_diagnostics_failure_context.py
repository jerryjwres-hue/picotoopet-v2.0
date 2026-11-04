"""Focused native negative fixture for the existing Diagnostics sidecar only."""
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / "windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs"


def test_diagnostics_failure_context_native_negatives() -> None:
    source = PROGRAM.read_text(encoding="utf-8")
    assert "internal sealed class DiagnosticFailureContext" in source, (
        "Original Diagnostics loses phase and inner socket errors; sidecar is absent"
    )
    for stage in (
        "credential_read", "rest_health", "websocket_connect", "cpu_task_submit",
        "cpu_task_event_wait", "websocket_ping", "report_write",
    ):
        assert f'EnterStage("{stage}"' in source
    if sys.platform != "win32":
        pytest.skip("The disposable socket-error fixture requires native Windows pwsh")
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(Path(__file__).with_name(
            "diagnostics_failure_context_negative.ps1")), "-RepoRoot", str(ROOT)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DIAGNOSTICS_FAILURE_CONTEXT_NATIVE_NEGATIVES=PASS" in result.stdout
