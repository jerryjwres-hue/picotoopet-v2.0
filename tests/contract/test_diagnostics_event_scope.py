"""Unrelated replay must not block the bounded diagnostic task-event channel."""
from pathlib import Path
import subprocess
import sys

import pytest


def test_diagnostics_probe_scope_ignores_history_without_dropping_target_event() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs").read_text(
        encoding="utf-8"
    )
    assert "internal static class DiagnosticTaskScope" in source, (
        "Historical task replay can block the diagnostic channel before its consumer starts"
    )
    assert 'DiagnosticTaskScope.BelongsToProbe(envelope.Payload, probeId)' in source
    assert 'await responsive.Task.WaitAsync(options.ConnectTimeout, cancellationToken)' in source
    if sys.platform != "win32":
        pytest.skip("The actual bounded-channel fixture requires native Windows pwsh")
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(Path(__file__).with_name(
            "diagnostics_event_scope_native.ps1")), "-RepoRoot", str(root)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DIAGNOSTIC_EVENT_SCOPE=PASS" in result.stdout
