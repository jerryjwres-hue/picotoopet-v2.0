from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from materialize_n6d4_core_bundle import materialize_core_bundle


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"  # Frozen Director Core extraction boundary.


class MaterializeN6D4CoreBundleTests(unittest.TestCase):
    def _write_pinned_bundle(self, root: Path) -> dict[str, bytes]:
        files = {
            f"{CORE_PREFIX}VERSION": b"N6D4\n",
            f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py": b"print('server')\n",
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(name, data)
        bundle = buffer.getvalue()
        encoded = base64.b64encode(bundle).decode("ascii")
        midpoint = ((len(encoded) // 2) // 4) * 4                                      # Keep both synthetic chunks valid Base64 quartets.
        chunks = [encoded[:midpoint], encoded[midpoint:]]
        for index, chunk in enumerate(chunks):
            (root / f"core.part{index:02d}.b64").write_text(chunk + "\n", encoding="ascii")

        bundle_sha = hashlib.sha256(bundle).hexdigest()
        (root / "CORE_BUNDLE.sha256").write_text(f"{bundle_sha}  PVP_DirectorConsole_Core_N6D4.zip\n", encoding="ascii")
        manifest = {
            "schema_version": "1.0",
            "source_checkpoint": "N6D4",
            "core_prefix": CORE_PREFIX,
            "core_bundle_sha256": bundle_sha,
            "core_file_count": len(files),
            "files": [
                {
                    "path": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
                for name, data in sorted(files.items())
            ],
        }
        (root / "CORE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (root / "SOURCE_PROVENANCE.txt").write_text("N6D4_SCRIPT_SHA256=test\nN6D4_ARCHIVE_SHA256=test\n", encoding="ascii")
        return files

    def test_materializes_verified_core_and_removes_stale_core_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap"
            target = root / "source"
            bootstrap.mkdir()
            expected_files = self._write_pinned_bundle(bootstrap)
            stale = target / CORE_PREFIX / "stale.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale\n", encoding="utf-8")

            result = materialize_core_bundle(bootstrap_dir=bootstrap, target_root=target)

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["file_count"], len(expected_files))
            self.assertFalse(stale.exists())
            for name, expected in expected_files.items():
                self.assertEqual((target / name).read_bytes(), expected)

    def test_rejects_bundle_hash_mismatch_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap"
            target = root / "source"
            bootstrap.mkdir()
            self._write_pinned_bundle(bootstrap)
            (bootstrap / "CORE_BUNDLE.sha256").write_text(f"{'0' * 64}  bad.zip\n", encoding="ascii")

            with self.assertRaisesRegex(ValueError, "Core bundle SHA-256 mismatch"):
                materialize_core_bundle(bootstrap_dir=bootstrap, target_root=target)
            self.assertFalse((target / CORE_PREFIX).exists())

    def test_rejects_manifest_file_hash_mismatch_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap"
            target = root / "source"
            bootstrap.mkdir()
            self._write_pinned_bundle(bootstrap)
            manifest_path = bootstrap / "CORE_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["sha256"] = "f" * 64
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Core file SHA-256 mismatch"):
                materialize_core_bundle(bootstrap_dir=bootstrap, target_root=target)
            self.assertFalse((target / CORE_PREFIX).exists())

    def test_rejects_archive_member_outside_frozen_core_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap"
            target = root / "source"
            bootstrap.mkdir()
            self._write_pinned_bundle(bootstrap)

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"{CORE_PREFIX}VERSION", "N6D4\n")
                archive.writestr("payload/outside.txt", "outside\n")                  # A pinned Core bundle may never write outside the frozen subtree.
            bundle = buffer.getvalue()
            encoded = base64.b64encode(bundle).decode("ascii")
            for part in bootstrap.glob("core.part*.b64"):
                part.unlink()
            (bootstrap / "core.part00.b64").write_text(encoded + "\n", encoding="ascii")
            bundle_sha = hashlib.sha256(bundle).hexdigest()
            (bootstrap / "CORE_BUNDLE.sha256").write_text(f"{bundle_sha}  bad.zip\n", encoding="ascii")
            manifest = {
                "schema_version": "1.0",
                "source_checkpoint": "N6D4",
                "core_prefix": CORE_PREFIX,
                "core_bundle_sha256": bundle_sha,
                "core_file_count": 2,
                "files": [
                    {
                        "path": f"{CORE_PREFIX}VERSION",
                        "sha256": hashlib.sha256(b"N6D4\n").hexdigest(),
                        "size_bytes": len(b"N6D4\n"),
                    },
                    {
                        "path": "payload/outside.txt",
                        "sha256": hashlib.sha256(b"outside\n").hexdigest(),
                        "size_bytes": len(b"outside\n"),
                    },
                ],
            }
            (bootstrap / "CORE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside frozen Core prefix"):
                materialize_core_bundle(bootstrap_dir=bootstrap, target_root=target)
            self.assertFalse((target / "payload/outside.txt").exists())

    def test_rejects_windows_drive_qualified_member_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap"
            target = root / "source"
            bootstrap.mkdir()

            unsafe_name = "C:\\escape.txt"                                                     # A drive-qualified member must never be interpreted relative to target_root.
            data = b"escape\n"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(unsafe_name, data)
            bundle = buffer.getvalue()
            encoded = base64.b64encode(bundle).decode("ascii")
            (bootstrap / "core.part00.b64").write_text(encoded + "\n", encoding="ascii")
            bundle_sha = hashlib.sha256(bundle).hexdigest()
            (bootstrap / "CORE_BUNDLE.sha256").write_text(f"{bundle_sha}  bad.zip\n", encoding="ascii")
            manifest = {
                "schema_version": "1.0",
                "source_checkpoint": "N6D4",
                "core_prefix": CORE_PREFIX,
                "core_bundle_sha256": bundle_sha,
                "core_file_count": 1,
                "files": [{"path": unsafe_name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}],
            }
            (bootstrap / "CORE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            (bootstrap / "SOURCE_PROVENANCE.txt").write_text("N6D4_ARCHIVE_SHA256_VERIFIED=YES\n", encoding="ascii")

            with self.assertRaisesRegex(ValueError, "unsafe Core bundle path"):
                materialize_core_bundle(bootstrap_dir=bootstrap, target_root=target)
            self.assertFalse((target / "C:" / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
