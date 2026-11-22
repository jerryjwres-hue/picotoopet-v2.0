"""CPU-only exact output evidence tests; synthetic images and Comfy histories."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from collect_local_keyframe_outputs import (  # noqa: E402
    collect, file_sha, main, png_chunks_checked, safe_components,
)
from recover_comfy_keyframe_workflow import canonical_bytes  # noqa: E402


def png(width: int, height: int) -> bytes:
    def chunk(name: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + name + value + struct.pack(
            ">I", zlib.crc32(name + value) & 0xffffffff
        )
    pixels = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def fixture(root: Path):
    batch_dir = root / "batch"
    batch_dir.mkdir()
    output_root = root / "comfy-output"
    output_root.mkdir()
    history_dir = root / "history"
    history_dir.mkdir()
    records, ids, histories = [], [], {}
    for i in range(1, 4):
        shot = f"shot-{i}"
        prompt_id = f"00000000-0000-4000-8000-{i:012d}"
        graph = {
            "1": {"class_type": "SyntheticText", "inputs": {"text": shot}},
            "2": {"class_type": "SyntheticSave", "inputs": {"filename_prefix": shot}},
        }
        graph_bytes = canonical_bytes(graph)
        filename = f"{i:02d}-{shot}.json"
        (batch_dir / filename).write_bytes(graph_bytes)
        (output_root / f"{shot}.png").write_bytes(png(16, 9))
        records.append({"shot_id": shot, "order": i, "graph_file": filename,
                        "graph_sha256": file_sha(graph_bytes)})
        ids.append({"shot_id": shot, "prompt_id": prompt_id})
        histories[prompt_id] = {
            prompt_id: {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "prompt": [i, prompt_id, graph, {}, ["2"]],
                "outputs": {"2": {"images": [
                    {"type": "output", "subfolder": "", "filename": f"{shot}.png"}
                ]}},
            }
        }
        (history_dir / f"{prompt_id}.json").write_bytes(canonical_bytes(histories[prompt_id]))
    batch = {
        "schema": "picotoo.local-keyframe-batch-dry-run.v1",
        "creative_package_id": "22222222-2222-4222-8222-222222222222",
        "creative_package_sha256": "a" * 64, "source_graph_sha256": "b" * 64,
        "keyframe_kit_digest": "c" * 64, "slot_map_sha256": "d" * 64,
        "shots": records, "production_authorized": False,
        "source_inputs_verified": False, "gpu_post": 0,
    }
    identities = {"schema": "picotoo.keyframe-prompt-identities.v1", "shots": ids}
    (batch_dir / "batch_manifest.json").write_bytes(canonical_bytes(batch))
    (root / "prompt_ids.json").write_bytes(canonical_bytes(identities))
    return batch, batch_dir, identities, histories, output_root, history_dir


class CandidateTests(unittest.TestCase):
    def test_complete_images_match_exact_histories_without_any_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            result = collect(batch, folder, ids, histories, output)
            self.assertEqual(len(result["shots"]), 3)
            self.assertEqual(result["review_status"], "NEEDS_HUMAN_REVIEW")
            self.assertFalse(result["reference_approved"])
            self.assertFalse(result["candidate_files_staged"])
            self.assertFalse(result["source_rights_confirmed"])
            self.assertEqual(result["gpu_post"], 0)
            for item in result["shots"]:
                self.assertEqual(len(item["candidates"]), 1)
                candidate = item["candidates"][0]
                self.assertEqual((candidate["width"], candidate["height"]), (16, 9))
                self.assertEqual(candidate["visual_review"], "UNREVIEWED")
                self.assertFalse(candidate["pixels_decoded"])
                self.assertIsNone(item["selected_reference"])

    def test_negative_wrong_graph_status_and_shot_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = fixture(Path(tmp))
            batch, folder, ids, histories, output, _ = args
            for bad in ("graph", "status", "wrong_id", "short", "duplicate"):
                b, mapping, logs = copy.deepcopy(batch), copy.deepcopy(ids), copy.deepcopy(histories)
                target = mapping["shots"][1]["prompt_id"]
                if bad == "graph":
                    logs[target][target]["prompt"][2]["1"]["inputs"]["text"] = "modified"
                elif bad == "status":
                    logs[target][target]["status"]["completed"] = False
                elif bad == "wrong_id":
                    logs[target][target]["prompt"][1] = mapping["shots"][0]["prompt_id"]
                elif bad == "short":
                    b["shots"].pop()
                else:
                    mapping["shots"][1]["prompt_id"] = mapping["shots"][0]["prompt_id"]
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    collect(b, folder, mapping, logs, output)

    def test_image_bytes_missing_crc_and_cross_shot_reuse_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            second = output / "shot-2.png"
            original = second.read_bytes()
            for bad in ("missing", "corrupt", "reused"):
                if bad == "missing":
                    second.unlink()
                elif bad == "corrupt":
                    second.write_bytes(original[:-5] + b"broken")
                else:
                    second.write_bytes((output / "shot-1.png").read_bytes())
                with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                    collect(batch, folder, ids, histories, output)
                second.write_bytes(original)

    def test_path_escape_symlink_and_animated_png_reject(self):
        for value in ("../escape", "C:/Users/secret", "/root", "a\\b", "a//b", "a/./b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_components(value, filename=False)
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            first = ids["shots"][0]["prompt_id"]
            histories[first][first]["outputs"]["2"]["images"][0]["filename"] = "../bad.png"
            with self.assertRaises(ValueError):
                collect(batch, folder, ids, histories, output)
            histories[first][first]["outputs"]["2"]["images"][0]["filename"] = "shot-1.png"
            target = output / "shot-1.png"
            target.unlink()
            try:
                target.symlink_to(output / "shot-2.png")
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks not available on runner")
            with self.assertRaises(ValueError):
                collect(batch, folder, ids, histories, output)
        animated = png(1, 1)
        # Add APNG control chunk before IDAT with a valid CRC; still must reject.
        header = animated[:33]
        name, data = b"acTL", struct.pack(">II", 2, 0)
        chunk = struct.pack(">I", len(data)) + name + data + struct.pack(
            ">I", zlib.crc32(name + data) & 0xffffffff
        )
        with self.assertRaises(ValueError):
            png_chunks_checked(header + chunk + animated[33:])

    def test_offline_cli_never_overwrites_or_accesses_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, batch_dir, _, _, output, history_dir = fixture(root)
            args = ["--batch-dir", str(batch_dir), "--prompt-ids", str(root / "prompt_ids.json"),
                    "--history-dir", str(history_dir), "--comfy-output-root", str(output),
                    "--output-dir", str(root / "evidence")]
            with patch("collect_local_keyframe_outputs.fetch_history") as network:
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
                network.assert_not_called()
            saved = json.loads((root / "evidence" / "candidate_manifest.json").read_bytes())
            self.assertFalse(saved["reference_approved"])


if __name__ == "__main__":
    unittest.main()
