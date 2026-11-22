"""Qwen-Image-Edit-2511 graph with 3 LoadImage core nodes, synthetic CPU refs."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from prepare_local_keyframe_batch import prepare, sha  # noqa: E402
from test_prepare_local_keyframe_batch import fixture  # noqa: E402


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))


def png(n: int) -> bytes:
    data = b"\x00" + bytes([n, 40, 75]) * 4
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(data))
            + _chunk(b"IEND", b""))


def qwen_fixture(root: Path):
    graph, recovery, bindings, package = fixture()
    graph["1"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
        "prompt": "old positive", "image1": ["6", 0],
    }}
    graph["6"] = {"class_type": "LoadImage", "inputs": {"image": "old-composition.png"}}
    graph["7"] = {"class_type": "LoadImage", "inputs": {"image": "character.png"}}
    graph["8"] = {"class_type": "LoadImage", "inputs": {"image": "scene.png"}}
    bindings["positive_prompt"] = dict(
        node_id="1", class_type="TextEncodeQwenImageEditPlus", input_name="prompt"
    )
    files = {}
    for name, number in {
        "old-composition.png": 10, "character.png": 20, "scene.png": 30,
        "s01-composition.png": 1, "s02-composition.png": 2, "s03-composition.png": 3,
    }.items():
        value = png(number)
        (root / name).write_bytes(value)
        files[name] = {"filename": name, "sha256": hashlib.sha256(value).hexdigest(),
                       "bytes": len(value)}
    bindings["reference_images"] = [
        {"node_id": "6", "class_type": "LoadImage", "input_name": "image",
         "mode": "per_shot", "files": [
             {"shot_id": f"shot-{i}", **files[f"s0{i}-composition.png"]}
             for i in (1, 2, 3)
         ]},
        {"node_id": "7", "class_type": "LoadImage", "input_name": "image",
         "mode": "fixed", "file": files["character.png"]},
        {"node_id": "8", "class_type": "LoadImage", "input_name": "image",
         "mode": "fixed", "file": files["scene.png"]},
    ]
    recovery["graph_sha256"] = sha(
        json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    bindings["graph_sha256"] = recovery["graph_sha256"]
    # Preserve the fact that no recovered Comfy history ID exists.
    recovery["history_status"] = "PNG_EMBEDDED_NO_HISTORY"
    recovery["source_kind"] = "COMFY_PNG_TEXt_PROMPT"
    recovery["source_image_sha256"] = "f" * 64
    return graph, recovery, bindings, package


class QwenBindingsTests(unittest.TestCase):
    def test_exact_qwen_prompt_three_compositions_and_pinned_shared_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, bindings, package = qwen_fixture(root)
            before = copy.deepcopy(graph)
            args = graph, recovery, bindings, package, "a" * 64, 0, root
            files, report = prepare(*args)
            self.assertEqual(len(files), 3)
            self.assertEqual(report["history_provenance"], "PNG_EMBEDDED_NO_HISTORY")
            self.assertEqual(len(report["reference_inputs"]), 3)
            self.assertFalse(report["production_authorized"])
            self.assertFalse(report["source_inputs_verified"])
            for number, record in enumerate(report["shots"], 1):
                item = json.loads(files[record["graph_file"]])
                self.assertEqual(item["1"]["inputs"]["prompt"], f"Opening state {number}")
                self.assertEqual(item["6"]["inputs"]["image"], f"s0{number}-composition.png")
                self.assertEqual(item["7"]["inputs"]["image"], "character.png")
                self.assertEqual(item["8"]["inputs"]["image"], "scene.png")
                self.assertEqual(item["2"], before["2"])
                self.assertEqual(item["3"]["inputs"]["model"], before["3"]["inputs"]["model"])
            self.assertEqual(before, graph)

    def test_missing_ref_wrong_hash_unpinned_slot_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for failure in ("missing", "wrong_hash", "missing_slot", "wrong_prompt", "symlink"):
                graph, recovery, bindings, package = qwen_fixture(root)
                if failure == "missing":
                    bindings["reference_images"].pop()
                elif failure == "wrong_hash":
                    bindings["reference_images"][0]["files"][0]["sha256"] = "0" * 64
                elif failure == "missing_slot":
                    bindings["reference_images"][0]["node_id"] = "3"
                elif failure == "wrong_prompt":
                    bindings["positive_prompt"]["class_type"] = "Wrong"
                else:
                    target = root / "s01-composition.png"
                    target.unlink()
                    try:
                        target.symlink_to(root / "character.png")
                    except (OSError, NotImplementedError):
                        self.skipTest("No symlink support")
                with self.subTest(failure=failure), self.assertRaises((ValueError, OSError)):
                    prepare(graph, recovery, bindings, package, "a" * 64, 0, root)
                if failure == "symlink":
                    break

    def test_ref_root_mandatory_and_legacy_prompt_contract_unchanged(self):
        graph, recovery, bindings, package = fixture()
        self.assertEqual(len(prepare(graph, recovery, bindings, package, "a" * 64, 0)[0]), 3)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, bindings, package = qwen_fixture(root)
            with self.assertRaises(ValueError):
                prepare(graph, recovery, bindings, package, "a" * 64, 0, None)
            self.assertEqual(len(prepare(graph, recovery, bindings, package, "a" * 64, 0, root)[0]), 3)


if __name__ == "__main__":
    unittest.main()
