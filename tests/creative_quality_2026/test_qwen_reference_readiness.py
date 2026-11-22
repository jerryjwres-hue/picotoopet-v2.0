"""Synthetic CPU-only Qwen readiness: existing JPEGs but two missing compositions."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from qwen_reference_readiness import inspect_readiness  # noqa: E402
from prepare_local_keyframe_batch import prepare, sha  # noqa: E402
from test_qwen_reference_bindings import jpeg, qwen_fixture  # noqa: E402


def observed_fixture(root: Path):
    graph, recovery, _, package = qwen_fixture(root)
    for node, name, marker in (
        ("7", "REF_DOG_A_001.jpg", 1), ("8", "REF_DOG_A_002.jpg", 2),
    ):
        (root / name).write_bytes(jpeg(marker))
        graph[node]["inputs"]["image"] = name
    # 01. Mirror source node numbering proven by the real six-PNG audit.
    graph = {
        "1": graph["6"],
        "2": graph["7"],
        "3": graph["8"],
        "4": graph["3"],
        "7": graph["1"],
        "8": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"prompt": "negative unchanged"}},
        "12": {"class_type": "KSampler",
               "inputs": {"seed": 11, "positive": ["7", 0],
                          "negative": ["8", 0]}},
        "14": {"class_type": "SaveImage",
               "inputs": {"filename_prefix": "PVP", "images": ["12", 0]}},
    }
    # 02. The positive node must follow the same load image linkage as
    #     the observed source, while the negative prompt stays frozen.
    graph["7"]["inputs"]["image1"] = ["1", 0]
    graph["7"]["inputs"]["image2"] = ["2", 0]
    graph["7"]["inputs"]["image3"] = ["3", 0]
    recovery["graph_sha256"] = sha(json.dumps(
        graph, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
    return graph, recovery, package


class ThreeShotReadinessTests(unittest.TestCase):
    def test_two_compositions_missing_are_reported_without_fabrication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            original = copy.deepcopy(graph)
            plan = inspect_readiness(
                graph, recovery, package, "a" * 64, root,
                composition_node="1", fixed_nodes=("2", "3"),
            )
            self.assertEqual(plan["status"], "BLOCKED_MISSING_REFERENCES")
            self.assertEqual(plan["shot_ids"], ["shot-1", "shot-2", "shot-3"])
            self.assertEqual([i["shot_id"] for i in plan["missing"]], ["shot-2", "shot-3"])
            self.assertEqual([i["reason"] for i in plan["missing"]],
                             ["MISSING_SHOT_COMPOSITION"] * 2)
            self.assertIsNone(plan["binding_proposal"])
            self.assertEqual(len(plan["inventory"]), 3)
            self.assertEqual(len([i for i in plan["inventory"] if i["format"] == "jpeg"]), 2)
            self.assertFalse(plan["production_authorized"])
            self.assertFalse(plan["source_rights_confirmed"])
            self.assertEqual(plan["gpu_post"], 0)
            self.assertEqual(graph, original)
            self.assertNotIn("old positive", json.dumps(plan))
            self.assertNotIn("negative unchanged", json.dumps(plan))

    def test_distinct_new_compositions_produce_unapproved_strict_slot_map(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            plan = inspect_readiness(
                graph, recovery, package, "a" * 64, root,
                composition_node="1", fixed_nodes=("2", "3"),
                shot_2="s02-composition.png", shot_3="s03-composition.png",
            )
            self.assertEqual(plan["status"], "READY_FOR_OWNER_BINDING_REVIEW")
            binding = plan["binding_proposal"]
            self.assertEqual([x["mode"] for x in binding["reference_images"]],
                             ["per_shot", "fixed", "fixed"])
            self.assertEqual(binding["positive_prompt"]["node_id"], "7")
            self.assertEqual(binding["seed"]["node_id"], "12")
            self.assertEqual(binding["output_prefix"]["node_id"], "14")
            frozen = copy.deepcopy(graph)
            prepared, manifest = prepare(
                graph, recovery, binding, package, "a" * 64, 0, root
            )
            self.assertEqual(len(prepared), 3)
            for i, entry in enumerate(manifest["shots"], 1):
                output = json.loads(prepared[entry["graph_file"]])
                self.assertEqual(output["1"]["inputs"]["image"],
                                 ["old-composition.png", "s02-composition.png",
                                  "s03-composition.png"][i - 1])
                self.assertEqual(output["2"]["inputs"]["image"], "REF_DOG_A_001.jpg")
                self.assertEqual(output["3"]["inputs"]["image"], "REF_DOG_A_002.jpg")
                self.assertEqual(output["8"], frozen["8"])
            self.assertFalse(manifest["source_inputs_verified"])
            self.assertFalse(manifest["production_authorized"])
            self.assertEqual(graph, frozen)

    def test_missing_real_filename_and_duplicate_composition_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            cases = [
                ("nonexistent.png", "s03-composition.png", "BLOCKED_MISSING_REFERENCES"),
                ("old-composition.png", "s03-composition.png", "BLOCKED_INVALID_REFERENCE"),
                ("../escape.jpg", "s03-composition.png", "BLOCKED_INVALID_REFERENCE"),
            ]
            for shot2, shot3, status in cases:
                with self.subTest(shot2=shot2):
                    plan = inspect_readiness(
                        graph, recovery, package, "a" * 64, root,
                        composition_node="1", fixed_nodes=("2", "3"),
                        shot_2=shot2, shot_3=shot3,
                    )
                    self.assertEqual(plan["status"], status)
                    self.assertIsNone(plan["binding_proposal"])

    def test_untrusted_roles_and_missing_recovery_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            with self.assertRaises(ValueError):
                inspect_readiness(
                    graph, recovery, package, "a" * 64, root,
                    composition_node="2", fixed_nodes=("2", "3"),
                )
            recovery["source_image_container_crc_verified"] = False
            with self.assertRaises(ValueError):
                inspect_readiness(
                    graph, recovery, package, "a" * 64, root,
                    composition_node="1", fixed_nodes=("2", "3"),
                )


if __name__ == "__main__":
    unittest.main()
