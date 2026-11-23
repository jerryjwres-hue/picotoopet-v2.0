"""End-to-end Qwen still source -> three frozen graphs -> exact PNG review.

Only synthetic PNGs and an isolated Core-shaped Creative ZIP are exercised.
No live GPU, Comfy HTTP, device, model file, lease or production authorization.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from comfy_png_embedded_evidence import recover_embedded_png  # noqa: E402
from prepare_local_keyframe_batch import prepare, read_package, sha  # noqa: E402
from offline_png_output_collector import collect_embedded_outputs  # noqa: E402
from recover_comfy_keyframe_workflow import canonical_bytes  # noqa: E402
from test_offline_png_output_collector import with_embedded_graph  # noqa: E402
from test_qwen_reference_bindings import qwen_fixture  # noqa: E402


class QwenCompleteLocalChain(unittest.TestCase):
    def test_local_source_three_shots_and_review_without_prompt_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "comfy-input"
            output_root = root / "comfy-output"
            batch_dir = root / "prepared"
            for path in (input_root, output_root, batch_dir):
                path.mkdir()
            original, _, bindings, package = qwen_fixture(input_root)
            # 01. Qwen's historical 14-node family uses core SaveImage, not
            #     the synthetic legacy Save node of the old test fixture.
            original["5"]["class_type"] = "SaveImage"
            bindings["output_prefix"]["class_type"] = "SaveImage"
            source_png = with_embedded_graph(original, 1280)
            source_graph, source_proof = recover_embedded_png(source_png, "source.png")
            self.assertEqual(source_proof["history_status"], "PNG_EMBEDDED_NO_HISTORY")
            self.assertIsNone(source_proof["prompt_id"])
            self.assertEqual(json.loads(source_graph), original)
            bindings["graph_sha256"] = source_proof["graph_sha256"]

            # 02. Use the exact one-member Creative ZIP intake, no fake hash.
            archive_path = root / "creative.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    package["creative_package_id"] + "/creative-package.json",
                    canonical_bytes(package)
                )
            package_sha = sha(archive_path.read_bytes())
            frozen_package = read_package(archive_path, package_sha)
            prepared, batch = prepare(
                original, source_proof, bindings, frozen_package, package_sha, 7,
                input_root
            )
            self.assertEqual(len(prepared), 3)
            self.assertEqual(batch["history_provenance"], "PNG_EMBEDDED_NO_HISTORY")
            self.assertFalse(batch["source_inputs_verified"])
            self.assertFalse(batch["production_authorized"])

            # 03. New output must contain the exact prepared API graph. Old
            #     Qwen source PNG can only recover a workflow, not fulfill a shot.
            selected = {
                "schema": "picotoo.local-keyframe-embedded-output-map.v1",
                "shots": [],
            }
            for index, record in enumerate(batch["shots"], 1):
                filename = record["graph_file"]
                (batch_dir / filename).write_bytes(prepared[filename])
                prepared_graph = json.loads(prepared[filename])
                output_name = f"render-shot-{index}.png"
                (output_root / output_name).write_bytes(
                    with_embedded_graph(prepared_graph, 80 + index)
                )
                selected["shots"].append({
                    "shot_id": record["shot_id"], "files": [output_name],
                })
            review = collect_embedded_outputs(batch, batch_dir, selected, output_root)
            self.assertEqual([x["prompt_id"] for x in review["shots"]], [None, None, None])
            self.assertEqual(len(review["shots"]), 3)
            self.assertFalse(review["comfy_history_success_verified"])
            self.assertTrue(all(x["candidates"][0]["embedded_prompt_graph_verified"]
                                for x in review["shots"]))
            self.assertEqual(review["gpu_post"], 0)
            self.assertFalse(review["reference_approved"])

            # 04. Hash changes or using the historical source PNG as a new
            #     output must fail before any UI approval or production attempt.
            forged = copy.deepcopy(selected)
            forged["shots"][0]["files"] = ["source.png"]
            (output_root / "source.png").write_bytes(source_png)
            with self.assertRaises(ValueError):
                collect_embedded_outputs(batch, batch_dir, forged, output_root)
            (batch_dir / batch["shots"][1]["graph_file"]).write_bytes(b"{}")
            with self.assertRaises(ValueError):
                collect_embedded_outputs(batch, batch_dir, selected, output_root)


if __name__ == "__main__":
    unittest.main()
