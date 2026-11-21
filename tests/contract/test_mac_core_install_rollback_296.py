"""#296 native macOS upgrade contract: failed Core replacement restores original service."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts/mac/INSTALL_MAC.command"


def _transaction_source() -> str:
    """Extract the ACTUAL installer rollback handler, not a reimplementation in tests."""

    source = INSTALL.read_text(encoding="utf-8")
    start = source.index("ROLLBACK_ARMED=0\nrollback_failed_core_install()")
    end = source.index('ln -sfn "$TARGET" "$CURRENT.next"', start)
    return source[start:end]


def test_upgrade_requires_real_http_version_and_can_rollback() -> None:
    """Static STOP ordering is verified on every platform, independently of launchd."""

    script = INSTALL.read_text(encoding="utf-8")
    assert "STOP=UNMANAGED_CURRENT_DIRECTORY" in script
    assert "STOP=PORT_STATE_CONFLICT" in script
    assert "STOP=UNSAFE_PREVIOUS_CORE_LINK" in script
    assert "STOP=UNMANAGED_RUNNING_CORE" in script
    assert "STOP=STALE_CURRENT_NEXT" in script
    assert "STOP=REAL_CORE_HTTP_VERSION_OR_DB_UNHEALTHY" in script
    assert "STOP=ROLLED_BACK_BUT_OLD_HTTP_UNVERIFIED" in script
    assert "ROLLBACK=RESTORED_PREVIOUS_CORE" in script
    assert "ROLLBACK=REMOVED_FAILED_FIRST_INSTALL" in script
    assert 'trap rollback_failed_core_install EXIT' in script
    assert script.index('trap rollback_failed_core_install EXIT') < script.index(
        'mv -h "$CURRENT.next" "$CURRENT"'
    )
    # The rollback handler has its own curl before activation; verify the NEW Core probe separately.
    assert script.index("SERVICE_READY=0\nfor attempt") > script.index(
        'mv -h "$CURRENT.next" "$CURRENT"'
    )
    assert script.index('ROLLBACK_ARMED=0\ntrap - EXIT\n') > script.index(
        'STOP=REAL_CORE_HTTP_VERSION_OR_DB_UNHEALTHY'
    )
    # Shell Rollback cannot launch Supervisor or Windows Worker.
    assert "launchctl bootstrap" in script
    assert "com.picotoopet.health-supervisor" not in script
    assert "comfyui serve" not in script.lower()


@pytest.mark.skipif(sys.platform != "darwin", reason="Actual BSD mv -h / Bash are tested on macOS")
@pytest.mark.parametrize("had_previous", [False, True])
def test_actual_bash_exit_trap_restores_symlink_and_original_plist(
    tmp_path: Path,
    had_previous: bool,
) -> None:
    """Real exit trap exercised with a mocked launchctl; no actual daemon or user home."""

    base = tmp_path / "User Library with spaces" / "PicotooPet"
    versions = base / "versions"
    target = versions / "new"
    old = versions / "old"
    target.mkdir(parents=True)
    old.mkdir(parents=True)
    (old / "src" / "picotoopet_core").mkdir(parents=True)
    (old / "src" / "picotoopet_core" / "product-version.txt").write_text(
        "2.3.27.1", encoding="utf-8"
    )
    current = base / "current"
    plist = base / "com.picotoopet.mac-core.plist"
    backup = base / "old-launchagent.plist"
    log = base / "mock-launchctl.log"

    if had_previous:
        current.symlink_to(old)
        plist.write_text("old-launchagent", encoding="utf-8")
        backup.write_text("old-launchagent", encoding="utf-8")

    args = {
        "VERSION": "test-rollback",
        "TARGET": str(target),
        "CURRENT": str(current),
        "CORE_PLIST": str(plist),
        "PLIST_BACKUP": str(backup),
        "PREVIOUS_TARGET": str(old) if had_previous else "",
        "PREVIOUS_EXISTS": "1" if had_previous else "0",
        "PLIST_WAS_PRESENT": "1" if had_previous else "0",
        "OLD_CORE_LOADED": "1" if had_previous else "0",
        "API_PORT": "8766",
        "TEST_LAUNCH_LOG": str(log),
    }
    variables = "\n".join(f"{name}={shlex.quote(value)}" for name, value in args.items())
    harness = (
        "set -euo pipefail\n"
        + variables
        + "\n"
        + "launchctl() { printf '%s\\n' \"$*\" >> \"$TEST_LAUNCH_LOG\"; return 0; }\n"
        + "curl() { printf '%s' '{\"status\":\"ok\",\"database\":\"ok\",\"version\":\"2.3.27.1\"}'; }\n"
        + _transaction_source()
        + '\nln -sfn "$TARGET" "$CURRENT.next"\n'
        + 'mv -h "$CURRENT.next" "$CURRENT"\n'
        + 'printf "%s" "new-launchagent" > "$CORE_PLIST"\n'
        + "false\n"
    )
    process = subprocess.run(
        ["/bin/bash", "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode != 0, process.stdout
    if had_previous:
        assert current.is_symlink()
        assert current.resolve() == old.resolve()
        assert plist.read_text(encoding="utf-8") == "old-launchagent"
        assert "ROLLBACK=RESTORED_PREVIOUS_CORE" in process.stderr
        assert "bootstrap" in log.read_text(encoding="utf-8")
    else:
        assert not current.exists() and not current.is_symlink()
        assert not plist.exists()
        assert "ROLLBACK=REMOVED_FAILED_FIRST_INSTALL" in process.stderr
