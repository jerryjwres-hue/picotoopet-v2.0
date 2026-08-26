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


class RecoverN6D4CoreEntrySpanTests(unittest.TestCase):
    def test_rejects_overlapping_minimum_local_entry_spans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence_dir = root / "evidence"
            output_dir = root / "out"
            evidence_dir.mkdir()

            files = [
                (f"{CORE_PREFIX}VERSION", b"N6D4\n"),
                (f"{CORE_PREFIX}src/pvp_director_native_v2/server_v2.py", b"print('server')\n"),
            ]
            inventory_entries = []
            evidence_entries = []
            offsets = [1000, 1050]                                                         # Second local header begins before the first entry's minimum physical end.

            for index, ((name, data), offset) in enumerate(zip(files, offsets, strict=True)):
                compressor = zlib.compressobj(level=9, wbits=-15)
                compressed = compressor.compress(data) + compressor.flush()
                evidence_name = f"entry{index:02d}.deflate.b64"
                (evidence_dir / evidence_name).write_text(
                    base64.b64encode(compressed).decode("ascii") + "\n",
                    encoding="ascii",
                )
                metadata = {
                    "path": name,
                    "compression_method": 8,
                    "crc32": f"{binascii.crc32(data) & 0xffffffff:08x}",
                    "compressed_size": len(compressed),
                    "uncompressed_size": len(data),
                    "local_header_offset": offset,
                }
                inventory_entries.append(dict(metadata))
                evidence_entries.append({**metadata, "evidence_file": evidence_name})

            inventory = {
                "schema_version": "1.0",
                "source_checkpoint": "N6D4",
                "inventory_status": "complete",
                "core_prefix": CORE_PREFIX,
                "core_entry_count": len(inventory_entries),
                "entries": inventory_entries,
            }
            (evidence_dir / "N6D4_CORE_ENTRY_INVENTORY.json").write_text(
                json.dumps(inventory, indent=2) + "\n",
                encoding="utf-8",
            )

            evidence = {
                "schema_version": "1.0",
                "source_checkpoint": "N6D4",
                "source_mode": "n6d4_zip_entries_crc32",
                "source_archive_sha256_pin": "e" * 64,
                "source_archive_sha256_verified": False,
                "source_script_sha256_pin": "6" * 64,
                "source_script_sha256_verified": False,
                "core_prefix": CORE_PREFIX,
                "complete_core_entry_count": len(evidence_entries),
                "entries": evidence_entries,
            }
            (evidence_dir / "N6D4_CORE_ENTRY_EVIDENCE.json").write_text(
                json.dumps(evidence, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "overlapping Core ZIP entry spans"):
                recover_core_entries(evidence_dir=evidence_dir, output_dir=output_dir)
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
