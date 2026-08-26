from __future__ import annotations

import base64
import binascii
import json
import tempfile
import unittest
import zlib
from pathlib import Path

from recover_n6d4_core_entries import recover_core_entries


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"                    # Frozen Director Core subtree.


class RecoverN6D4CoreEntriesTests(unittest.TestCase):
    def _write_evidence(self, root: Path) -> dict[str, bytes]:
        files = {
            f"{CORE_PREFIX}VERSION": b"N6D4\n",
            f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py": b"print('server')\n",
        }
        entries = []
        inventory_entries = []
        for index, (name, data) in enumerate(sorted(files.items())):
            compressor = zlib.compressobj(level=9, wbits=-15)                              # ZIP method 8 stores raw DEFLATE, not zlib framing.
            compressed = compressor.compress(data) + compressor.flush()
            evidence_name = f"entry{index:02d}.deflate.b64"
            (root / evidence_name).write_text(base64.b64encode(compressed).decode("ascii") + "\n", encoding="ascii")
            metadata = {
                "path": name,
                "compression_method": 8,
                "crc32": f"{binascii.crc32(data) & 0xffffffff:08x}",
                "compressed_size": len(compressed),
                "uncompressed_size": len(data),
                "local_header_offset": 1000 + index * 100,
            }
            inventory_entries.append(dict(metadata))                                       # Inventory is independent of recovered payload evidence.
            entries.append({**metadata, "evidence_file": evidence_name})

        inventory = {
            "schema_version": "1.0",
            "source_checkpoint": "N6D4",
            "inventory_status": "complete",
            "core_prefix": CORE_PREFIX,
            "core_entry_count": len(inventory_entries),
            "entries": inventory_entries,
        }
        (root / "N6D4_CORE_ENTRY_INVENTORY.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

        manifest = {
            "schema_version": "1.0",
            "source_checkpoint": "N6D4",
            "source_mode": "n6d4_zip_entries_crc32",
            "source_archive_sha256_pin": "e" * 64,
            "source_archive_sha256_verified": False,
            "source_script_sha256_pin": "6" * 64,
            "source_script_sha256_verified": False,
            "core_prefix": CORE_PREFIX,
            "complete_core_entry_count": len(entries),
            "entries": entries,
        }
        (root / "N6D4_CORE_ENTRY_EVIDENCE.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return files

    def test_recovers_complete_core_from_verified_zip_entry_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            expected = self._write_evidence(evidence)

            result = recover_core_entries(evidence_dir=evidence, output_dir=output, chunk_chars=96)

            self.assertEqual(result["source_mode"], "n6d4_zip_entries_crc32")
            self.assertEqual(result["core_file_count"], len(expected))
            self.assertFalse(result["source_archive_sha256_verified"])
            self.assertTrue(result["source_zip_entries_verified"])
            self.assertEqual(result["source_zip_entry_count"], len(expected))
            provenance = (output / "SOURCE_PROVENANCE.txt").read_text(encoding="ascii")
            self.assertIn("SOURCE_MODE=n6d4_zip_entries_crc32", provenance)
            self.assertIn("N6D4_ARCHIVE_SHA256_VERIFIED=NO", provenance)
            self.assertIn("N6D4_ZIP_ENTRIES_VERIFIED=YES", provenance)

    def test_rejects_corrupted_compressed_payload_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            payload = evidence / "entry00.deflate.b64"
            compressed = bytearray(base64.b64decode(payload.read_text(encoding="ascii")))
            compressed[-1] ^= 0x01                                                         # Preserve length while invalidating DEFLATE/CRC semantics.
            payload.write_text(base64.b64encode(compressed).decode("ascii") + "\n", encoding="ascii")

            with self.assertRaises((ValueError, zlib.error)):
                recover_core_entries(evidence_dir=evidence, output_dir=output)
            self.assertFalse((output / "CORE_BUNDLE.sha256").exists())

    def test_rejects_missing_entry_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            (evidence / "entry01.deflate.b64").unlink()

            with self.assertRaisesRegex(ValueError, "entry evidence is missing"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)
            self.assertFalse(output.exists())

    def test_reports_all_missing_entry_evidence_in_one_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            (evidence / "entry00.deflate.b64").unlink()
            (evidence / "entry01.deflate.b64").unlink()

            with self.assertRaises(ValueError) as context:
                recover_core_entries(evidence_dir=evidence, output_dir=output)

            self.assertEqual(
                str(context.exception),
                "entry evidence is missing: entry00.deflate.b64, entry01.deflate.b64",
            )
            self.assertFalse(output.exists())

    def test_rejects_incomplete_or_duplicate_core_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            manifest_path = evidence / "N6D4_CORE_ENTRY_EVIDENCE.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"].append(dict(manifest["entries"][0]))                       # Duplicate path must never satisfy completeness by count alone.
            manifest["complete_core_entry_count"] = len(manifest["entries"])
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate Core entry path"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)

    def test_rejects_entry_outside_frozen_core_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            manifest_path = evidence / "N6D4_CORE_ENTRY_EVIDENCE.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"][0]["path"] = "payload/outside.txt"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside frozen Core prefix"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)

    def test_rejects_partial_authoritative_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            inventory_path = evidence / "N6D4_CORE_ENTRY_INVENTORY.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["inventory_status"] = "partial"                                      # Recovery research may be partial; production materialization may not.
            inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "authoritative Core inventory is not complete"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)
            self.assertFalse(output.exists())

    def test_rejects_evidence_path_set_that_differs_from_authoritative_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            manifest_path = evidence / "N6D4_CORE_ENTRY_EVIDENCE.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"] = manifest["entries"][:1]                                 # Self-declared count must not redefine the frozen Core file set.
            manifest["complete_core_entry_count"] = 1
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "evidence path set does not match authoritative Core inventory"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)
            self.assertFalse(output.exists())

    def test_rejects_evidence_metadata_that_differs_from_authoritative_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            output = root / "out"
            evidence.mkdir()
            self._write_evidence(evidence)
            manifest_path = evidence / "N6D4_CORE_ENTRY_EVIDENCE.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entries"][0]["crc32"] = "00000000"                                  # Payload metadata is pinned by inventory, not trusted from evidence.
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "evidence metadata does not match authoritative Core inventory"):
                recover_core_entries(evidence_dir=evidence, output_dir=output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
