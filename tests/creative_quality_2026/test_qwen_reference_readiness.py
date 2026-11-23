"""Synthetic CPU-only Qwen readiness: existing JPEGs but two missing compositions."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from qwen_reference_readiness import inspect_readiness  # noqa: E402
from prepare_local_keyframe_batch import (  # noqa: E402
    bootstrap_compositions, canonical_bytes, keyframes, main as prepare_main, prepare, sha,
)
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
            # 01. Existing source kit automatically supplies precise prompts,
            #     framing, shot order and review criteria for S2/S3, without
            #     generating or approving a picture.
            work = plan["composition_work_order"]
            self.assertEqual(work["shot_count"], 3)
            self.assertFalse(work["source_workflow_modified"])
            self.assertFalse(work["all_images_approved"])
            self.assertEqual(work["gpu_post"], 0)
            self.assertEqual([x["composition_status"] for x in work["items"]], [
                "OBSERVED_UNAPPROVED",
                "NEEDS_DISTINCT_COMPOSITION",
                "NEEDS_DISTINCT_COMPOSITION",
            ])
            for frame, item in zip(
                package["stage_results"]["keyframe_kit.v1"]["keyframes"],
                work["items"], strict=True
            ):
                self.assertEqual(item["creative_still_prompt"], frame["still_prompt"])
                self.assertEqual(item["creative_still_prompt_sha256"],
                                 sha(frame["still_prompt"].encode("utf-8")))
                self.assertEqual(item["review_checklist"], frame["review_checklist"])
                self.assertFalse(item["new_image_created"])
                self.assertFalse(item["owner_approved"])
                self.assertTrue(item["prompt_text_local_only"])
            self.assertIsNone(plan["binding_proposal"])
            self.assertEqual(len(plan["inventory"]), 3)
            self.assertEqual(len([i for i in plan["inventory"] if i["format"] == "jpeg"]), 2)
            self.assertFalse(plan["production_authorized"])
            self.assertFalse(plan["source_rights_confirmed"])
            self.assertEqual(plan["gpu_post"], 0)
            self.assertEqual(graph, original)
            self.assertNotIn("old positive", json.dumps(plan))
            self.assertNotIn("negative unchanged", json.dumps(plan))

    def test_real_kit_shared_scene_lock_is_not_lost_in_shot_work_orders(self):
        # 01. Real KeyframeSpec contains camera_framing but not scene_id.
        #     The frozen scene comes from keyframe_kit.v1.locks instead.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            bible = package["stage_results"]["video_bible.v1"]
            bible["shots"] = [
                {
                    "shot_id": f"shot-{index}", "order": index,
                    "scene_id": "kitchen-scene",
                    "opening_state": opening, "closing_state": closing,
                    "handoff_to_next": "CONTINUOUS",
                }
                for index, (opening, closing) in enumerate((
                    ("pet waits by the door", "pet approaches the bowl"),
                    ("pet approaches the bowl", "pet touches the bowl"),
                    ("pet touches the bowl", "pet settles beside the bowl"),
                ), 1)
            ]
            bible["bible_digest"] = sha(canonical_bytes({
                key: value for key, value in bible.items()
                if key != "bible_digest"
            }))
            kit = package["stage_results"]["keyframe_kit.v1"]
            kit["bible_digest"] = bible["bible_digest"]
            kit["locks"] = {"scene_id": "kitchen-scene"}
            kit["kit_digest"] = None
            kit["kit_digest"] = sha(canonical_bytes({
                key: value for key, value in kit.items()
                if key != "bible_digest"
            }))
            plan = inspect_readiness(
                graph, recovery, package, "a" * 64, root,
                composition_node="1", fixed_nodes=("2", "3"),
            )
            self.assertEqual(plan["status"], "BLOCKED_MISSING_REFERENCES")
            self.assertEqual([
                item["scene_id"] for item in plan["composition_work_order"]["items"]
            ], ["kitchen-scene"] * 3)
            self.assertFalse(plan["production_authorized"])
            self.assertEqual(plan["gpu_post"], 0)
            items = plan["composition_work_order"]["items"]
            self.assertEqual(
                [item["opening_state"] for item in items],
                [shot["opening_state"] for shot in bible["shots"]],
            )
            self.assertEqual(
                [item["closing_state"] for item in items],
                [shot["closing_state"] for shot in bible["shots"]],
            )
            self.assertEqual(
                [item["handoff_to_next"] for item in items], ["CONTINUOUS"] * 3
            )
            self.assertEqual(items[1]["closing_state"], items[2]["opening_state"])

            # 02. A contradicting shot-local scene must never override locks.
            kit["keyframes"][1]["scene_id"] = "unrelated-room"
            kit["kit_digest"] = None
            kit["kit_digest"] = sha(canonical_bytes({
                key: value for key, value in kit.items()
                if key != "bible_digest"
            }))
            with self.assertRaisesRegex(ValueError, "SCENE_LOCK_CONFLICT"):
                inspect_readiness(
                    graph, recovery, package, "a" * 64, root,
                    composition_node="1", fixed_nodes=("2", "3"),
                )

    def test_creative_bootstrap_unblocks_first_drafts_without_fake_compositions(self):
        # 01. Historical S1 guidance can be used to *prepare* three distinct
        #     prompts, but cannot satisfy strict S2/S3 readiness or approval.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            original = copy.deepcopy(graph)
            before = inspect_readiness(
                graph, recovery, package, "a" * 64, root,
                composition_node="1", fixed_nodes=("2", "3"),
            )
            self.assertEqual(before["status"], "BLOCKED_MISSING_REFERENCES")
            prepared, manifest = bootstrap_compositions(
                graph, recovery, package, "a" * 64, 0, root,
            )
            self.assertEqual(len(prepared), 3)
            self.assertEqual(manifest["schema"],
                             "picotoo.local-composition-bootstrap-dry-run.v1")
            self.assertEqual(len(manifest["historical_reference_inputs"]), 3)
            self.assertTrue(manifest["historical_composition_reused_as_guidance_only"])
            for key in ("source_inputs_verified", "reference_approved",
                        "production_authorized", "workflow_registered",
                        "distinct_shot_compositions_observed"):
                self.assertFalse(manifest[key])
            self.assertEqual(manifest["gpu_post"], 0)
            self.assertEqual(len({entry["seed"] for entry in manifest["shots"]}), 3)
            for entry in manifest["shots"]:
                payload = prepared[entry["graph_file"]]
                draft = json.loads(payload)
                self.assertEqual(sha(payload), entry["graph_sha256"])
                self.assertEqual(draft["7"]["inputs"]["prompt"],
                                 f"Opening state {entry['order']}")
                self.assertIn("/composition_bootstrap/",
                              draft["14"]["inputs"]["filename_prefix"])
                for frozen in ("1", "2", "3", "4", "8"):
                    self.assertEqual(draft[frozen], original[frozen])
                self.assertIsNone(entry["generated_composition"])
                self.assertEqual(entry["human_visual_review"], "NOT_PERFORMED")
            self.assertEqual(graph, original)
            after = inspect_readiness(
                graph, recovery, package, "a" * 64, root,
                composition_node="1", fixed_nodes=("2", "3"),
            )
            self.assertEqual(after["status"], "BLOCKED_MISSING_REFERENCES")
            self.assertIsNone(after["binding_proposal"])
            (root / "REF_DOG_A_001.jpg").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                bootstrap_compositions(graph, recovery, package, "a" * 64, 0, root)

    def test_bootstrap_cli_multi_seed_is_offline_unapproved_and_nonoverwriting(self):
        # 02. Reuse the existing producer and CLI. The output schema is
        #     deliberately NOT accepted as a strict production keyframe batch.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            archive = root / "creative.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(f"{package['creative_package_id']}/creative-package.json",
                           canonical_bytes(package))
            digest = sha(archive.read_bytes())
            (root / "workflow_api.json").write_bytes(canonical_bytes(graph))
            (root / "recovery_manifest.json").write_bytes(canonical_bytes(recovery))
            args = [
                "--package", str(archive), "--package-sha256", digest,
                "--recovery-dir", str(root), "--composition-bootstrap",
                "--input-root", str(root), "--variant", "5",
                "--variant-count", "2",
            ]
            output = root / "bootstrap_variants"
            self.assertEqual(prepare_main(args + ["--output-dir", str(output)]), 0)
            self.assertEqual(prepare_main(args + ["--output-dir", str(output)]), 1)
            index = json.loads((output / "variant_index.json").read_bytes())
            self.assertEqual(index["schema"],
                             "picotoo.local-composition-bootstrap-index.v1")
            self.assertEqual(index["variant_count"], 2)
            self.assertFalse(index["production_authorized"])
            self.assertEqual(index["gpu_post"], 0)
            self.assertEqual(
                sorted(x.name for x in output.iterdir()),
                ["v0005", "v0006", "variant_index.json"],
            )
            seeds = set()
            for item in index["variants"]:
                folder_path = output / item["relative_directory"]
                manifest_bytes = (folder_path / "batch_manifest.json").read_bytes()
                self.assertEqual(item["batch_manifest_sha256"], sha(manifest_bytes))
                manifest = json.loads(manifest_bytes)
                self.assertEqual(manifest["schema"],
                                 "picotoo.local-composition-bootstrap-dry-run.v1")
                self.assertFalse(manifest["distinct_shot_compositions_observed"])
                self.assertFalse(manifest["production_authorized"])
                self.assertEqual(manifest["gpu_post"], 0)
                self.assertEqual(len(manifest["shots"]), 3)
                for shot in manifest["shots"]:
                    seeds.add(shot["seed"])
                    raw = (folder_path / shot["graph_file"]).read_bytes()
                    self.assertEqual(sha(raw), shot["graph_sha256"])
            self.assertEqual(len(seeds), 6)

            # 03. An invalid mixing of bootstrap and strict bindings cannot
            #     write any directory or accidentally create approved assets.
            for name, extra in (
                ("wrong_args", ["--slot-map", str(root / "unknown.json")]),
                ("bad_variant", ["--variant-count", "9"]),
            ):
                with self.subTest(name=name):
                    target = root / name
                    self.assertEqual(
                        prepare_main(args + extra + ["--output-dir", str(target)]),
                        1,
                    )
                    self.assertFalse(target.exists())

    def test_vertical_pass_kit_guidance_requires_explicit_bootstrap_opt_in(self):
        # 04. A real Core PASS vertical ZIP can guide creative sketches,
        #     but it is never silently upgraded to a landscape PASS package.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            original = copy.deepcopy(graph)
            package["stage_results"]["creative_brief.v1"]["output_profile_id"] = (
                "video.vertical.v1"
            )
            with self.assertRaisesRegex(ValueError, "KEYFRAME_KIT_LINEAGE_INVALID"):
                keyframes(package)
            with self.assertRaisesRegex(ValueError, "KEYFRAME_KIT_LINEAGE_INVALID"):
                bootstrap_compositions(graph, recovery, package, "a" * 64, 0, root)
            files, manifest = bootstrap_compositions(
                graph, recovery, package, "a" * 64, 0, root,
                allow_vertical_guidance=True,
            )
            self.assertEqual(len(files), 3)
            self.assertEqual(manifest["creative_package_sha256"], "a" * 64)
            self.assertEqual(manifest["source_output_profile_id"], "video.vertical.v1")
            self.assertEqual(manifest["intended_later_output_profile_id"],
                             "video.landscape.v1")
            self.assertFalse(manifest["source_output_profile_matches_intent"])
            self.assertFalse(manifest["source_profile_conversion_performed"])
            self.assertFalse(manifest["target_geometry_verified"])
            self.assertFalse(manifest["production_authorized"])
            self.assertFalse(manifest["reference_approved"])
            self.assertFalse(manifest["distinct_shot_compositions_observed"])
            self.assertEqual(manifest["gpu_post"], 0)
            for item in manifest["shots"]:
                decoded = json.loads(files[item["graph_file"]])
                self.assertEqual(decoded["1"], original["1"])
                self.assertEqual(decoded["2"], original["2"])
                self.assertEqual(decoded["3"], original["3"])
                self.assertEqual(decoded["4"], original["4"])
                self.assertEqual(decoded["8"], original["8"])
                self.assertIsNone(item["generated_composition"])
            self.assertEqual(graph, original)
            with self.assertRaisesRegex(ValueError, "VERTICAL_OPT_IN_INVALID"):
                bootstrap_compositions(
                    graph, recovery, package, "a" * 64, 0, root,
                    allow_vertical_guidance="yes",
                )
            # 05. Restrict the exception to vertical source only:
            #     a true landscape kit must use the usual bootstrap path.
            package["stage_results"]["creative_brief.v1"]["output_profile_id"] = (
                "video.landscape.v1"
            )
            with self.assertRaisesRegex(ValueError, "VERTICAL_OPT_IN_INVALID"):
                bootstrap_compositions(
                    graph, recovery, package, "a" * 64, 0, root,
                    allow_vertical_guidance=True,
                )

    def test_vertical_pass_kit_cli_stays_offline_and_strict_batch_stays_closed(self):
        # 06. Exercise the authentic one-member Core ZIP read/check path,
        #     including the explicit flag; source is NEVER repackaged.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph, recovery, package = observed_fixture(root)
            package["stage_results"]["creative_brief.v1"]["output_profile_id"] = (
                "video.vertical.v1"
            )
            archive = root / "original-vertical-core.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(
                    f"{package['creative_package_id']}/creative-package.json",
                    canonical_bytes(package),
                )
            digest = sha(archive.read_bytes())
            (root / "workflow_api.json").write_bytes(canonical_bytes(graph))
            (root / "recovery_manifest.json").write_bytes(canonical_bytes(recovery))
            base = [
                "--package", str(archive), "--package-sha256", digest,
                "--recovery-dir", str(root), "--input-root", str(root),
                "--variant-count", "2",
            ]
            without = root / "without_ack"
            self.assertEqual(
                prepare_main(base + ["--composition-bootstrap",
                                     "--output-dir", str(without)]), 1,
            )
            self.assertFalse(without.exists())
            selected = root / "vertical_guidance"
            ack = "--allow-vertical-guidance-for-landscape-drafts"
            opts = base + ["--composition-bootstrap", ack, "--output-dir",
                           str(selected)]
            self.assertEqual(prepare_main(opts), 0)
            self.assertEqual(prepare_main(opts), 1)
            self.assertEqual(sha(archive.read_bytes()), digest)
            index = json.loads((selected / "variant_index.json").read_bytes())
            self.assertEqual(index["schema"],
                             "picotoo.local-composition-bootstrap-index.v1")
            self.assertEqual(index["source_output_profile_id"], "video.vertical.v1")
            self.assertFalse(index["source_profile_conversion_performed"])
            self.assertFalse(index["target_geometry_verified"])
            for item in index["variants"]:
                manifest = json.loads((
                    selected / item["relative_directory"] / "batch_manifest.json"
                ).read_bytes())
                self.assertEqual(manifest["schema"],
                                 "picotoo.local-composition-bootstrap-dry-run.v1")
                self.assertFalse(manifest["source_output_profile_matches_intent"])
                self.assertEqual(manifest["gpu_post"], 0)
                self.assertEqual(len(manifest["shots"]), 3)
            # 07. No flag can bypass the production keyframe preparation;
            #     the normal strict path continues to reject vertical kits.
            strict = root / "wrong_strict"
            self.assertEqual(
                prepare_main(base + [ack, "--output-dir", str(strict)]), 1
            )
            self.assertFalse(strict.exists())
            wrong_hash = root / "wrong_hash"
            self.assertEqual(
                prepare_main(
                    base + ["--package-sha256", "f" * 64,
                            "--composition-bootstrap", ack,
                            "--output-dir", str(wrong_hash)]
                ), 1,
            )
            self.assertFalse(wrong_hash.exists())

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
            # 02. Even after three distinct real inputs are found, the work
            #     order remains unapproved, and no AI/GPU operation is run.
            self.assertEqual(
                [x["composition_status"]
                 for x in plan["composition_work_order"]["items"]],
                ["OBSERVED_UNAPPROVED"] * 3,
            )
            self.assertFalse(plan["composition_work_order"]["all_images_approved"])
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
                    self.assertEqual(len(plan["composition_work_order"]["items"]), 3)
                    self.assertFalse(plan["composition_work_order"]["all_images_approved"])

    def test_renamed_byte_identical_composition_blocks_shot_2_or_3(self):
        # 03. Filename uniqueness must not allow copies of an earlier shot.
        #     Both SHOT_001→002 and SHOT_002→003 cases stay CPU-only.
        cases = (
            ("s02-composition.png", "old-composition.png", "shot-2", "shot-1"),
            ("s03-composition.png", "s02-composition.png", "shot-3", "shot-2"),
        )
        for target, source, duplicate_shot, original_shot in cases:
            with self.subTest(duplicate_shot=duplicate_shot):
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    graph, recovery, package = observed_fixture(root)
                    (root / target).write_bytes((root / source).read_bytes())
                    frozen = copy.deepcopy(graph)
                    plan = inspect_readiness(
                        graph, recovery, package, "a" * 64, root,
                        composition_node="1", fixed_nodes=("2", "3"),
                        shot_2="s02-composition.png",
                        shot_3="s03-composition.png",
                    )
                    self.assertEqual(plan["status"], "BLOCKED_INVALID_REFERENCE")
                    self.assertIsNone(plan["binding_proposal"])
                    self.assertEqual(len(plan["invalid"]), 1)
                    self.assertEqual(
                        plan["invalid"][0]["reason"],
                        "DUPLICATE_SHOT_COMPOSITION_BYTES",
                    )
                    self.assertEqual(plan["invalid"][0]["shot_id"], duplicate_shot)
                    self.assertEqual(
                        plan["invalid"][0]["duplicate_of_shot_id"], original_shot
                    )
                    self.assertEqual(
                        [x["composition_status"]
                         for x in plan["composition_work_order"]["items"]
                         if x["shot_id"] == duplicate_shot],
                        ["INVALID_REFERENCE"],
                    )
                    self.assertFalse(plan["production_authorized"])
                    self.assertEqual(plan["gpu_post"], 0)
                    self.assertEqual(graph, frozen)

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
