from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from recover_n6d4_core_bundle import recover_core_archive, recover_core_bundle


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"  # Authoritative Director Core subtree.


class RecoverN6D4CoreBundleTests(unittest.TestCase):
    def _build_all_in_one(self, *, include_core: bool = True) -> tuple[str, str]:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", "outside-core")
            if include_core:
                archive.writestr(f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py", "print('server')\n")
                archive.writestr(f"{CORE_PREFIX}tests/test_server.py", "def test_server():\n    assert True\n")

        archive_bytes = archive_buffer.getvalue()
        archive_sha = hashlib.sha256(archive_bytes).hexdigest()
        payload = base64.encodebytes(archive_bytes).decode("ascii")
        script = (
            '$ErrorActionPreference = "Stop"\n'
            f'$ExpectedSha256 = "{archive_sha}"\n'
            "$ArchiveBase64 = @'\n"
            f"{payload}"
            "'@\n"
        )
        return script, archive_sha

    def test_recovers_only_director_core_and_emits_verifiable_bundle(self) -> None:
        script, archive_sha = self._build_all_in_one()
        script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "out"
            result = recover_core_bundle(
                script_text=script,
                output_dir=output,
                expected_script_sha256=script_sha,
                expected_archive_sha256=archive_sha,
                chunk_chars=96,
            )

            self.assertEqual(result["source_archive_sha256"], archive_sha)
            self.assertEqual(result["source_script_sha256"], script_sha)
            self.assertEqual(result["core_file_count"], 2)

            manifest = json.loads((output / "CORE_MANIFEST.json").read_text(encoding="utf-8"))
            paths = [entry["path"] for entry in manifest["files"]]
            self.assertEqual(
                paths,
                [
                    f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py",
                    f"{CORE_PREFIX}tests/test_server.py",
                ],
            )
            self.assertNotIn("README.txt", paths)

            parts = sorted(output.glob("core.part*.b64"))
            rebuilt_b64 = "".join(path.read_text(encoding="ascii").strip() for path in parts)
            rebuilt = base64.b64decode(rebuilt_b64)
            expected_bundle_sha = (output / "CORE_BUNDLE.sha256").read_text(encoding="ascii").split()[0]
            self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), expected_bundle_sha)

            with zipfile.ZipFile(io.BytesIO(rebuilt)) as bundle:
                self.assertEqual(bundle.testzip(), None)
                self.assertEqual(sorted(bundle.namelist()), paths)

    def test_recovers_from_exact_embedded_archive_sha_without_script_reencoding(self) -> None:
        script, archive_sha = self._build_all_in_one()
        payload = script.split("$ArchiveBase64 = @'\n", 1)[1].split("'@\n", 1)[0]             # Reproduce the exact embedded ZIP bytes, not PowerShell text bytes.
        archive_bytes = base64.b64decode("".join(payload.split()), validate=True)                    # Archive SHA remains the authoritative payload identity.

        with tempfile.TemporaryDirectory() as temp_dir:
            result = recover_core_archive(
                archive_bytes=archive_bytes,
                output_dir=Path(temp_dir),
                expected_archive_sha256=archive_sha,
                source_script_sha256_pin="a" * 64,
            )

            self.assertEqual(result["source_mode"], "embedded_archive_sha256")
            self.assertEqual(result["source_archive_sha256"], archive_sha)
            self.assertEqual(result["source_script_sha256_pin"], "a" * 64)
            self.assertFalse(result["source_script_sha256_verified"])
            self.assertEqual(result["core_file_count"], 2)

    def test_archive_mode_rejects_wrong_embedded_archive_sha(self) -> None:
        script, _ = self._build_all_in_one()
        payload = script.split("$ArchiveBase64 = @'\n", 1)[1].split("'@\n", 1)[0]             # Keep the synthetic ZIP valid while deliberately supplying the wrong pin.
        archive_bytes = base64.b64decode("".join(payload.split()), validate=True)

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "archive SHA-256 mismatch"):
                recover_core_archive(
                    archive_bytes=archive_bytes,
                    output_dir=Path(temp_dir),
                    expected_archive_sha256="f" * 64,
                    source_script_sha256_pin="a" * 64,
                )

    def test_rejects_script_hash_mismatch_before_archive_processing(self) -> None:
        script, archive_sha = self._build_all_in_one()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "script SHA-256 mismatch"):
                recover_core_bundle(
                    script_text=script,
                    output_dir=Path(temp_dir),
                    expected_script_sha256="0" * 64,
                    expected_archive_sha256=archive_sha,
                )

    def test_rejects_archive_hash_mismatch(self) -> None:
        script, _ = self._build_all_in_one()
        script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "archive SHA-256 mismatch"):
                recover_core_bundle(
                    script_text=script,
                    output_dir=Path(temp_dir),
                    expected_script_sha256=script_sha,
                    expected_archive_sha256="f" * 64,
                )

    def test_rejects_source_without_director_core_subtree(self) -> None:
        script, archive_sha = self._build_all_in_one(include_core=False)
        script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "Director Core subtree is missing"):
                recover_core_bundle(
                    script_text=script,
                    output_dir=Path(temp_dir),
                    expected_script_sha256=script_sha,
                    expected_archive_sha256=archive_sha,
                )

    def test_hashes_exact_raw_script_bytes_before_decoding(self) -> None:
        script, archive_sha = self._build_all_in_one()
        script_bytes = b"\xef\xbb\xbf" + script.replace("\n", "\r\n").encode("utf-8")  # Preserve BOM + CRLF as authoritative bytes.
        script_sha = hashlib.sha256(script_bytes).hexdigest()                          # Sidecar hashes raw file bytes, not decoded text.

        with tempfile.TemporaryDirectory() as temp_dir:
            result = recover_core_bundle(
                script_bytes=script_bytes,
                output_dir=Path(temp_dir),
                expected_script_sha256=script_sha,
                expected_archive_sha256=archive_sha,
            )

        self.assertEqual(result["source_script_sha256"], script_sha)
        self.assertEqual(result["source_archive_sha256"], archive_sha)

    def test_rejects_unsafe_zip_member_even_outside_core_subtree(self) -> None:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../escape.txt", "escape")                               # Any unsafe source member invalidates the source archive.
            archive.writestr(f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py", "print('server')\n")

        archive_bytes = archive_buffer.getvalue()
        archive_sha = hashlib.sha256(archive_bytes).hexdigest()
        payload = base64.encodebytes(archive_bytes).decode("ascii")
        script = "$ArchiveBase64 = @'\n" + payload + "'@\n"
        script_bytes = script.encode("utf-8")
        script_sha = hashlib.sha256(script_bytes).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsafe ZIP member path"):
                recover_core_bundle(
                    script_bytes=script_bytes,
                    output_dir=Path(temp_dir),
                    expected_script_sha256=script_sha,
                    expected_archive_sha256=archive_sha,
                )

    def test_rejects_windows_style_traversal_and_drive_paths(self) -> None:
        for unsafe_name in ("..\\escape.txt", "C:\\escape.txt"):
            with self.subTest(unsafe_name=unsafe_name):
                archive_buffer = io.BytesIO()
                with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(unsafe_name, "escape")                                      # Windows separators and drive-qualified names are equally unsafe.
                    archive.writestr(f"{CORE_PREFIX}VERSION", "N6D4\n")

                archive_bytes = archive_buffer.getvalue()
                archive_sha = hashlib.sha256(archive_bytes).hexdigest()
                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(ValueError, "unsafe ZIP member path"):
                        recover_core_archive(
                            archive_bytes=archive_bytes,
                            output_dir=Path(temp_dir),
                            expected_archive_sha256=archive_sha,
                            source_script_sha256_pin="a" * 64,
                        )


if __name__ == "__main__":
    unittest.main()
