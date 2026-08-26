from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from audit_n6d4_core_inventory import audit_inventory


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"


class AuditN6D4CoreInventoryTests(unittest.TestCase):
    def _write_inventory(self, root: Path, entries: list[dict[str, object]]) -> Path:
        inventory = {
            "schema_version": "1.0",
            "source_checkpoint": "N6D4",
            "inventory_status": "partial",
            "core_prefix": CORE_PREFIX,
            "core_entry_count": None,
            "verified_entry_count": len(entries),
            "entries": entries,
        }
        path = root / "N6D4_CORE_ENTRY_INVENTORY.json"
        path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
        return path

    def test_reports_unexplained_positive_gaps_in_offset_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = f"{CORE_PREFIX}src/pvp_director_native_v2/a.py"
            second = f"{CORE_PREFIX}src/pvp_director_native_v2/b.py"
            second_offset = 300                                                            # Deliberately beyond the first entry's minimum physical ZIP span.
            path = self._write_inventory(
                root,
                [
                    {
                        "path": first,
                        "compression_method": 8,
                        "crc32": "00000001",
                        "compressed_size": 10,
                        "uncompressed_size": 20,
                        "local_header_offset": 100,
                    },
                    {
                        "path": second,
                        "compression_method": 8,
                        "crc32": "00000002",
                        "compressed_size": 5,
                        "uncompressed_size": 10,
                        "local_header_offset": second_offset,
                    },
                ],
            )

            result = audit_inventory(path)

            expected_min_end = 100 + 30 + len(first.encode("utf-8")) + 10
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["verified_entry_count"], 2)
            self.assertEqual(result["unexplained_gap_count"], 1)
            self.assertEqual(result["gaps"][0]["after_path"], first)
            self.assertEqual(result["gaps"][0]["before_path"], second)
            self.assertEqual(result["gaps"][0]["gap_start"], expected_min_end)
            self.assertEqual(result["gaps"][0]["gap_end"], second_offset)
            self.assertEqual(result["gaps"][0]["gap_bytes"], second_offset - expected_min_end)

    def test_rejects_overlapping_minimum_local_spans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = f"{CORE_PREFIX}src/pvp_director_native_v2/a.py"
            second = f"{CORE_PREFIX}src/pvp_director_native_v2/b.py"
            path = self._write_inventory(
                root,
                [
                    {
                        "path": first,
                        "compression_method": 8,
                        "crc32": "00000001",
                        "compressed_size": 50,
                        "uncompressed_size": 60,
                        "local_header_offset": 100,
                    },
                    {
                        "path": second,
                        "compression_method": 8,
                        "crc32": "00000002",
                        "compressed_size": 5,
                        "uncompressed_size": 10,
                        "local_header_offset": 180,
                    },
                ],
            )

            with self.assertRaisesRegex(ValueError, "overlapping Core ZIP entry spans"):
                audit_inventory(path)

    def test_complete_inventory_requires_zero_internal_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = f"{CORE_PREFIX}src/pvp_director_native_v2/a.py"
            second = f"{CORE_PREFIX}src/pvp_director_native_v2/b.py"
            path = self._write_inventory(
                root,
                [
                    {
                        "path": first,
                        "compression_method": 8,
                        "crc32": "00000001",
                        "compressed_size": 10,
                        "uncompressed_size": 20,
                        "local_header_offset": 100,
                    },
                    {
                        "path": second,
                        "compression_method": 8,
                        "crc32": "00000002",
                        "compressed_size": 5,
                        "uncompressed_size": 10,
                        "local_header_offset": 300,
                    },
                ],
            )
            inventory = json.loads(path.read_text(encoding="utf-8"))
            inventory["inventory_status"] = "complete"
            inventory["core_entry_count"] = 2
            path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "complete Core inventory still has unexplained gaps"):
                audit_inventory(path)


if __name__ == "__main__":
    unittest.main()
