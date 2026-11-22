"""CPU-only 6-PNG inspection, security and private-prompt omission."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.audit_local_qwen_pngs import inspect_directory, main
from scripts.recover_comfy_keyframe_workflow import canonical_bytes
from test_comfy_png_embedded_evidence import GRAPH, png


def fixtures(root: Path, count: int = 6) -> None:
    for index in range(count):
        graph = copy.deepcopy(GRAPH)
        graph["1"]["inputs"]["image"] = f"private-input-{index}.png"
        graph["7"]["inputs"]["prompt"] = f"PRIVATE_CREATIVE_PROMPT_{index}"
        (root / f"PVP_SHOT_{index+1:03d}.png").write_bytes(png(graph))


class ExistingQwenPngAuditTests(unittest.TestCase):
    def test_six_realistic_pngs_without_history_or_prompt_export(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "Comfy-output"
            root.mkdir()
            fixtures(root)
            with patch("urllib.request.build_opener") as network:
                result = inspect_directory(root, expected_count=6)
                network.assert_not_called()
            self.assertEqual(result["status"], "OBSERVED_NEEDS_REVIEW")
            self.assertEqual(result["candidate_count"], 6)
            self.assertEqual(len(result["files"]), 6)
            self.assertTrue(all(item["history_status"] == "PNG_EMBEDDED_NO_HISTORY"
                                and item["prompt_id"] is None for item in result["files"]))
            self.assertTrue(all(item["has_qwen_binding_shape"] for item in result["files"]))
            self.assertFalse(result["comfy_history_success_verified"])
            self.assertFalse(result["production_authorized"])
            self.assertFalse(result["raw_prompt_text_exported"])
            self.assertNotIn("PRIVATE_CREATIVE_PROMPT", canonical_bytes(result).decode())

            output = Path(folder) / "inspection.json"
            self.assertEqual(main(["--output-root", str(root), "--expected-count", "6",
                                   "--report-file", str(output)]), 0)
            self.assertEqual(main(["--output-root", str(root), "--expected-count", "6",
                                   "--report-file", str(output)]), 1)
            self.assertEqual(json.loads(output.read_bytes()), result)

    def test_no_silent_missing_png_or_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures(root, 5)
            result = inspect_directory(root, expected_count=6)
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertIn("QWEN_EXPECTED_COUNT_MISMATCH",
                          [item["reason"] for item in result["errors"]])
            (root / "PVP_SHOT_005.png").write_bytes(b"not a PNG")
            result = inspect_directory(root, expected_count=5)
            self.assertEqual(result["verified_png_count"], 4)
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertFalse(result["production_authorized"])

    def test_reject_duplicate_bytes_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "output"
            root.mkdir()
            fixtures(root, 2)
            (root / "PVP_SHOT_002.png").write_bytes(
                (root / "PVP_SHOT_001.png").read_bytes()
            )
            result = inspect_directory(root, expected_count=2)
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertIn("QWEN_DUPLICATED_IMAGE_BYTES",
                          [item["reason"] for item in result["errors"]])
            (root / "PVP_SHOT_002.png").unlink()
            try:
                (root / "PVP_SHOT_002.png").symlink_to(
                    root / "PVP_SHOT_001.png"
                )
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unsupported")
            result = inspect_directory(root, expected_count=2)
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertTrue(any(x["reason"] == "QWEN_PNG_NOT_ORDINARY_BOUNDED_FILE"
                                for x in result["errors"]))

    def test_report_cannot_be_written_into_comfy_output(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures(root, 1)
            self.assertEqual(main(["--output-root", str(root),
                                   "--report-file", str(root / "audit.json")]), 1)
            self.assertFalse((root / "audit.json").exists())


if __name__ == "__main__":
    unittest.main()
