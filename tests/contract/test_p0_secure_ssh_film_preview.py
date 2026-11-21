"""Film-only preview must include verified OpenSSH bootstrap without changing authorization."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/p0-three-shot-developer-preview.yml"
LEGACY_RELEASE = ROOT / ".github/workflows/windows-phase2-release.yml"
SSH = ROOT / "windows/desktop/release/Start-SecureMacTunnel.ps1"
VBS = ROOT / "windows/desktop/release/CONNECT_MAC_SECURE.vbs"
VERIFIER = ROOT / "scripts/ci/verify_p0_developer_preview.py"


class SecureSshFilmPreviewContracts(unittest.TestCase):
    """Use the existing 2.3 Core route; do not start SSH or a video Worker."""

    def test_ssh_launcher_is_credential_free_strict_and_loopback_only(self):
        """SSH uses trusted known_hosts and public keys; never fallback to LAN HTTP."""
        script = SSH.read_text(encoding="utf-8-sig")
        vbs = VBS.read_text(encoding="utf-8")
        for key in (
            "StrictHostKeyChecking=yes",
            "BatchMode=yes",
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "PreferredAuthentications=publickey",
            "PubkeyAuthentication=yes",
            "ExitOnForwardFailure=yes",
            "127.0.0.1:18766:127.0.0.1:",
            "System32\\OpenSSH\\ssh.exe",
            "SECURE_MAC_TUNNEL_SELFTEST=PASS_NO_NETWORK_NO_GPU",
        ):
            self.assertIn(key, script)
        self.assertIn("Start-SecureMacTunnel.ps1", vbs)
        for secret in ("Bearer ", "Authorization:", "PICOTOO_WORKER_ATTEST_KEY"):
            self.assertNotIn(secret, script)

    def test_health_requires_original_core_and_database_not_arbitrary_200(self):
        """An unrelated localhost service cannot satisfy the no-token readiness check."""
        script = SSH.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$health.status -eq 'ok'", script)
        self.assertIn("[string]$health.database -eq 'ok'", script)
        self.assertIn(r"[string]$health.version -match '^2\.3\.'", script)
        self.assertIn('http://127.0.0.1:18766/api/v1/health', script)
        self.assertIn("if (-not $ready)", script)

    def test_preview_packages_both_sha_verified_ssh_files_and_retains_hold(self):
        """Actual ZIP must include all named members before an artifact is uploaded."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        verifier = VERIFIER.read_text(encoding="utf-8")
        for name in (
            "CONNECT_MAC_SECURE.vbs",
            "Start-SecureMacTunnel.ps1",
            "Prepare-P0ThreeShotHold.ps1",
        ):
            self.assertIn(name, workflow)
            self.assertIn(name, verifier)
        self.assertIn("P0_SECURE_SSH_NATIVE_SELFTEST_FAILED", workflow)
        self.assertIn("P0_PREVIEW_ZIP_BYTES_UNVERIFIED", workflow)
        self.assertLess(
            workflow.index("Verify ZIP bytes, complete manifest and permanent production HOLD"),
            workflow.index("Upload internal portable developer-preview evidence"),
        )

    def test_optional_desktop_pet_and_gpu_release_still_not_auto_enabled(self):
        """No film helper can reintroduce the parked desktop pet or claim approval."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        optional = LEGACY_RELEASE.read_text(encoding="utf-8")
        self.assertIn("user_install_allowed = $false", workflow)
        self.assertIn("formal_release_pass = $false", workflow)
        self.assertIn("P0_DESKTOP_PET_DORMANCY_CONTRACT_FAILED", workflow)
        self.assertIn("workflow_dispatch:", optional)
        self.assertNotIn("pull_request:", optional)


if __name__ == "__main__":
    unittest.main()
