"""Native HTTP transport regression for diagnostic idempotency keys and audit JSON."""
from pathlib import Path
import subprocess
import sys

import pytest


def test_diagnostics_key_real_windows_http_transport() -> None:
    if sys.platform != "win32":
        pytest.skip("Actual SocketsHttpHandler transport is verified on native Windows")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(Path(__file__).with_name(
            "diagnostics_ascii_idempotency_native.ps1")), "-RepoRoot", str(root)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DIAGNOSTIC_ASCII_HTTP_TRANSPORT=PASS" in result.stdout
