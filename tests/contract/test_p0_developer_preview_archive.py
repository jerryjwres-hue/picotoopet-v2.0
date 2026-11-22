"""CPU-only archive tamper tests; NEVER run Windows EXE or enable GPU."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.ci.verify_p0_developer_preview import (
    PreviewVerificationError,
    verify_preview_archive,
)

_SHA = "a" * 40
_RUN = "12345"
README = (
    b"NOT a formal Release Builder output.\n"
    b"Desktop pet is DEFERRED and excluded from film-production scope.\n"
    b"Only trusted SSH public-key authentication; no credentials in the archive.\n"
)


def _create_preview(
    root: Path,
    *,
    release_flag: bool = False,
    source_sha: str = _SHA,
    tamper: bool = False,
    missing_hold: bool = False,
    missing_tunnel: bool = False,
    tamper_tunnel: bool = False,
    duplicate: bool = False,
    unsafe_path: bool = False,
    include_offline_tools: bool = False,
    tool_body_tamper: bool = False,
    wrong_tool_manifest: bool = False,
) -> tuple[Path, Path]:
    """Synthetic ZIP resembles real preview metadata, never a runnable application."""

    archive = root / f"P0-ThreeShot-DeveloperPreview-{_SHA[:12]}.zip"
    receipt = root / "preview-sha256.txt"
    files = {
        "app/Picotoo Pet AI.exe": b"TEST-ONLY-NOT-A-REAL-EXE",
        "app/product-version.txt": b"2.3.27.1\n",
        "Prepare-P0ThreeShotHold.ps1": b"# TEST ONLY: persistent HOLD\n",
        "CONNECT_MAC_SECURE.vbs": b"' TEST ONLY: protected OpenSSH launcher\n",
        "Start-SecureMacTunnel.ps1": b"# TEST ONLY: SSH loopback strict keys\n",
        "README_P0_DEVELOPER_PREVIEW.txt": README,
    }
    if include_offline_tools:
        # 01. Fixture tools are static fake Python, never real Comfy programs.
        files.update({
            "scripts/recover_comfy_keyframe_workflow.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
            "scripts/comfy_png_embedded_evidence.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
            "scripts/prepare_local_keyframe_batch.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
            "scripts/qwen_reference_bindings.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
            "scripts/collect_local_keyframe_outputs.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
            "scripts/offline_png_output_collector.py": b"# SYNTHETIC CPU-ONLY QWEN TOOL\\n",
        })
    if missing_hold:
        files.pop("Prepare-P0ThreeShotHold.ps1")
    if missing_tunnel:
        files.pop("Start-SecureMacTunnel.ps1")
    manifest = {
        "schema_version": "p0-three-shot-developer-preview.v1",
        "source_sha": source_sha,
        "github_run_id": _RUN,
        "product_version": "2.3.27.1",
        "build_target": "win-x64-self-contained",
        "artifact_kind": "unsigned-portable-developer-preview",
        "formal_release_pass": release_flag,
        "user_install_allowed": False,
        "executable": "app/Picotoo Pet AI.exe",
        "hold_script": "Prepare-P0ThreeShotHold.ps1",
        "connection_launcher": "CONNECT_MAC_SECURE.vbs",
        "connection_script": "Start-SecureMacTunnel.ps1",
        **({"offline_keyframe_tools": sorted(
            name for name in files if name.startswith("scripts/")
        )} if include_offline_tools else {}),
        "files": [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in files.items()
        ],
    }
    if wrong_tool_manifest:
        manifest["offline_keyframe_tools"] = ["scripts/untrusted_gpu_post.py"]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        for name, data in files.items():
            changed = (tamper and name.endswith(".exe")) or (
                tamper_tunnel and name == "Start-SecureMacTunnel.ps1"
            ) or (tool_body_tamper and name == "scripts/recover_comfy_keyframe_workflow.py")
            package.writestr(name, data + (b"CHANGED" if changed else b""))
        if duplicate:
            # Duplicate basename under different case must not be extracted on Windows.
            package.writestr("APP/product-version.txt", b"2.3.27.1")
        if unsafe_path:
            package.writestr("../outside.txt", b"NO")
        package.writestr("preview-manifest.json", json.dumps(manifest).encode("utf-8"))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive, receipt


class PreviewArchiveContractTests(unittest.TestCase):
    """Protect the exact artifact ZIP, not a separate fake success marker."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def verify(self, archive: Path, receipt: Path, **overrides):
        return verify_preview_archive(
            archive, receipt, expected_source_sha=overrides.get("sha", _SHA),
            expected_run_id=overrides.get("run_id", _RUN),
        )

    def test_synthetic_hold_archive_passes_without_exe_execution(self):
        archive, receipt = _create_preview(self.root)
        result = self.verify(archive, receipt)
        self.assertEqual(result["files_verified"], 6)
        self.assertFalse(result["formal_release_pass"])
        self.assertFalse(result["user_install_allowed"])

    def test_rejects_formal_release_claim(self):
        archive, receipt = _create_preview(self.root, release_flag=True)
        with self.assertRaisesRegex(PreviewVerificationError, "UNAUTHORIZED_RELEASE_CLAIM"):
            self.verify(archive, receipt)

    def test_rejects_source_sha_mismatch(self):
        archive, receipt = _create_preview(self.root, source_sha="b" * 40)
        with self.assertRaisesRegex(PreviewVerificationError, "MANIFEST_IDENTITY_MISMATCH"):
            self.verify(archive, receipt)

    def test_rejects_body_tamper_even_if_zip_receipt_is_recomputed(self):
        archive, receipt = _create_preview(self.root, tamper=True)
        with self.assertRaisesRegex(PreviewVerificationError, "FILE_BYTES_OR_SHA256_MISMATCH"):
            self.verify(archive, receipt)

    def test_rejects_changed_zip_without_receipt_update(self):
        archive, receipt = _create_preview(self.root)
        receipt.write_text("0" * 64 + f"  {archive.name}\n", encoding="ascii")
        with self.assertRaisesRegex(PreviewVerificationError, "ARCHIVE_SHA256_RECEIPT_MISMATCH"):
            self.verify(archive, receipt)

    def test_rejects_missing_persistent_hold(self):
        archive, receipt = _create_preview(self.root, missing_hold=True)
        with self.assertRaisesRegex(PreviewVerificationError, "REQUIRED_PAYLOAD_MISSING"):
            self.verify(archive, receipt)

    def test_rejects_missing_trusted_ssh_script(self):
        archive, receipt = _create_preview(self.root, missing_tunnel=True)
        with self.assertRaisesRegex(PreviewVerificationError, "REQUIRED_PAYLOAD_MISSING"):
            self.verify(archive, receipt)

    def test_rejects_modified_trusted_ssh_script(self):
        archive, receipt = _create_preview(self.root, tamper_tunnel=True)
        with self.assertRaisesRegex(PreviewVerificationError, "FILE_BYTES_OR_SHA256_MISMATCH"):
            self.verify(archive, receipt)

    def test_rejects_case_collision(self):
        archive, receipt = _create_preview(self.root, duplicate=True)
        with self.assertRaisesRegex(PreviewVerificationError, "DUPLICATE_OR_CASE_COLLIDING_PATH"):
            self.verify(archive, receipt)

    def test_rejects_path_traversal(self):
        archive, receipt = _create_preview(self.root, unsafe_path=True)
        with self.assertRaisesRegex(PreviewVerificationError, "UNSAFE_ZIP_PATH"):
            self.verify(archive, receipt)

    def test_exact_cpu_only_qwen_toolset_verified_in_unsigned_archive(self):
        archive, receipt = _create_preview(self.root, include_offline_tools=True)
        result = self.verify(archive, receipt)
        self.assertEqual(result["files_verified"], 12)
        self.assertFalse(result["user_install_allowed"])

    def test_tampered_qwen_tool_bytes_rejected(self):
        archive, receipt = _create_preview(
            self.root, include_offline_tools=True, tool_body_tamper=True
        )
        with self.assertRaisesRegex(PreviewVerificationError, "FILE_BYTES_OR_SHA256_MISMATCH"):
            self.verify(archive, receipt)

    def test_undeclared_or_missing_qwen_toolset_rejected(self):
        archive, receipt = _create_preview(self.root, wrong_tool_manifest=True)
        with self.assertRaisesRegex(PreviewVerificationError, "OFFLINE_QWEN_TOOLSET_INCOMPLETE"):
            self.verify(archive, receipt)

    def test_rejects_wrong_run_id(self):
        archive, receipt = _create_preview(self.root)
        with self.assertRaisesRegex(PreviewVerificationError, "MANIFEST_IDENTITY_MISMATCH"):
            self.verify(archive, receipt, run_id="99999")


if __name__ == "__main__":
    unittest.main()
