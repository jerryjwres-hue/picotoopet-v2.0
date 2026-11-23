"""Synthetic PNG evidence: offline output recovery without Comfy history IDs."""
from __future__ import annotations

import copy
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from collect_local_keyframe_outputs import main, file_sha  # noqa: E402
from offline_png_output_collector import collect_embedded_outputs  # noqa: E402
from recover_comfy_keyframe_workflow import canonical_bytes  # noqa: E402
from test_collect_local_keyframe_outputs import fixture  # noqa: E402


def chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def with_embedded_graph(graph: dict, width: int) -> bytes:
    # Pixel payload is synthetic; metadata graph must match exact prepared JSON.
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 3, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"prompt\x00" + canonical_bytes(graph))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff\x00\x00" * width) * 3))
            + chunk(b"IEND", b""))


class OfflineImagesTests(unittest.TestCase):
    def test_exact_three_output_graphs_without_any_fictitious_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch, folder, _, _, output, _ = fixture(root)
            batch["history_provenance"] = "PNG_EMBEDDED_NO_HISTORY"
            selection = {"schema": "picotoo.local-keyframe-embedded-output-map.v1",
                         "shots": []}
            for order, shot in enumerate(batch["shots"], 1):
                graph = json.loads((folder / shot["graph_file"]).read_bytes())
                graph["2"]["class_type"] = "SaveImage"
                # Exact modified prepared graph is frozen before image embedding.
                graph_bytes = canonical_bytes(graph)
                (folder / shot["graph_file"]).write_bytes(graph_bytes)
                shot["graph_sha256"] = file_sha(graph_bytes)
                file = f"shot-{order}.png"
                (output / file).write_bytes(with_embedded_graph(graph, 20 + order))
                selection["shots"].append({"shot_id": shot["shot_id"], "files": [file]})
            (folder / "batch_manifest.json").write_bytes(canonical_bytes(batch))
            (root / "selected.json").write_bytes(canonical_bytes(selection))
            evidence = collect_embedded_outputs(batch, folder, selection, output)
            self.assertEqual(len(evidence["shots"]), 3)
            self.assertEqual([x["prompt_id"] for x in evidence["shots"]], [None] * 3)
            self.assertFalse(evidence["comfy_history_success_verified"])
            self.assertFalse(evidence["reference_approved"])
            self.assertEqual(evidence["history_provenance"], "PNG_EMBEDDED_NO_HISTORY")
            self.assertTrue(all(x["candidates"][0]["embedded_prompt_graph_verified"]
                                for x in evidence["shots"]))
            self.assertEqual(evidence["gpu_post"], 0)
            argv = ["--batch-dir", str(folder),
                    "--embedded-png-map", str(root / "selected.json"),
                    "--comfy-output-root", str(output),
                    "--output-dir", str(root / "review")]
            self.assertEqual(main(argv), 0)
            self.assertEqual(main(argv), 1)
            report = json.loads((root / "review" / "candidate_manifest.json").read_bytes())
            self.assertEqual(report, evidence)

            # 01. Tampered exact-graph metadata is not historical completion.
            data = (output / "shot-2.png").read_bytes()
            (output / "shot-2.png").write_bytes(data[:-6] + b"badend")
            with self.assertRaises(ValueError):
                collect_embedded_outputs(batch, folder, selection, output)

    def test_reused_image_missing_metadata_and_wrong_shot_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch, folder, _, _, output, _ = fixture(root)
            batch["history_provenance"] = "PNG_EMBEDDED_NO_HISTORY"
            selection = {"schema": "picotoo.local-keyframe-embedded-output-map.v1",
                         "shots": []}
            for order, shot in enumerate(batch["shots"], 1):
                graph = json.loads((folder / shot["graph_file"]).read_bytes())
                graph["2"]["class_type"] = "SaveImage"
                raw = canonical_bytes(graph)
                (folder / shot["graph_file"]).write_bytes(raw)
                shot["graph_sha256"] = file_sha(raw)
                (output / f"ff-{order}.png").write_bytes(with_embedded_graph(graph, 20 + order))
                selection["shots"].append({"shot_id": shot["shot_id"], "files": [f"ff-{order}.png"]})
            with self.assertRaises(ValueError):
                wrong = copy.deepcopy(selection)
                wrong["shots"][1]["files"] = wrong["shots"][0]["files"]
                collect_embedded_outputs(batch, folder, wrong, output)
            with self.assertRaises(ValueError):
                wrong = copy.deepcopy(selection)
                wrong["shots"][1]["files"] = ["ff-1.png"]
                collect_embedded_outputs(batch, folder, wrong, output)
            with self.assertRaises(ValueError):
                wrong = copy.deepcopy(selection)
                wrong["shots"][0]["files"] = ["../outside.png"]
                collect_embedded_outputs(batch, folder, wrong, output)


if __name__ == "__main__":
    unittest.main()
