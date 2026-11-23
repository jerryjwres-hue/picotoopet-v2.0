"""Use synthetic ZIP and graph data; no network, user device or GPU."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# Keep the standalone Windows CLI import path identical to normal invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from prepare_local_keyframe_batch import (  # noqa: E402
    canonical_bytes, main, prepare, read_package, sha,
)

PACKAGE_ID = "22222222-2222-4222-8222-222222222222"


def fixture():
    graph = {
        "1": {"class_type": "SyntheticText", "inputs": {"text": "old positive"}},
        "2": {"class_type": "SyntheticText", "inputs": {"text": "negative locked"}},
        "3": {"class_type": "SyntheticSampler", "inputs": {"seed": 1, "model": ["4", 0]}},
        "4": {"class_type": "SyntheticModel", "inputs": {"unet_name": "model.safetensors"}},
        "5": {"class_type": "SyntheticSave", "inputs": {"filename_prefix": "old", "images": ["3", 0]}},
        "6": {"class_type": "SyntheticReference", "inputs": {"image": "identity.png"}},
    }
    digest = sha(canonical_bytes(graph))
    recovery = dict(schema="picotoo.local-keyframe-workflow-recovery.v1",
                    graph_sha256=digest, production_authorized=False,
                    history_status="RECORDED_SUCCESS", gpu_post=0)
    bindings = dict(schema="picotoo.local-keyframe-slot-map.v1", graph_sha256=digest,
                    positive_prompt=dict(node_id="1", class_type="SyntheticText", input_name="text"),
                    seed=dict(node_id="3", class_type="SyntheticSampler", input_name="seed"),
                    output_prefix=dict(node_id="5", class_type="SyntheticSave", input_name="filename_prefix"))
    bible = {"schema_version": "fixture", "subject": "synthetic"}
    bible["bible_digest"] = sha(canonical_bytes(bible))
    frames = [dict(shot_id=f"shot-{i}", order=i, still_prompt=f"Opening state {i}",
                   approval_status="PENDING_HUMAN_REVIEW", review_checklist=["Same subject"])
              for i in range(1, 4)]
    kit = dict(schema_version="keyframe_kit.v1", bible_digest=bible["bible_digest"],
               keyframes=frames, kit_digest=None)
    kit["kit_digest"] = sha(canonical_bytes({k: v for k, v in kit.items() if k != "bible_digest"}))
    package = dict(schema_version="1.0", creative_package_id=PACKAGE_ID,
                   quality_outcome="PASS", creative_profile="creative.content_plan.v2",
                   stage_results={"video_bible.v1": bible, "keyframe_kit.v1": kit,
                                  "creative_brief.v1": {"output_profile_id": "video.landscape.v1"},
                                  "shot_plan.v1": {"shots": [dict(shot_id=f["shot_id"], order=f["order"],
                                      duration_seconds=4, render_intent="GENERATIVE_VIDEO") for f in frames]}})
    return graph, recovery, bindings, package


class BatchTests(unittest.TestCase):
    def test_only_explicit_slots_change_and_variant_is_reproducible(self):
        graph, recovery, bindings, package = fixture()
        frozen = copy.deepcopy(graph)
        args = graph, recovery, bindings, package, "a" * 64
        files, manifest = prepare(*args, 0)
        self.assertEqual((files, manifest), prepare(*args, 0))
        self.assertEqual(len(files), 3)
        self.assertEqual(len({x["seed"] for x in manifest["shots"]}), 3)
        self.assertNotEqual(files, prepare(*args, 1)[0])
        for record in manifest["shots"]:
            data = files[record["graph_file"]]
            candidate = json.loads(data)
            self.assertEqual(sha(data), record["graph_sha256"])
            self.assertEqual(candidate["1"]["inputs"]["text"], f"Opening state {record['order']}")
            for unchanged in ("2", "4", "6"):
                self.assertEqual(candidate[unchanged], frozen[unchanged])
            self.assertEqual(candidate["3"]["inputs"]["model"], frozen["3"]["inputs"]["model"])
            self.assertEqual(candidate["5"]["inputs"]["images"], frozen["5"]["inputs"]["images"])
        self.assertEqual(graph, frozen)
        self.assertFalse(manifest["production_authorized"])
        self.assertFalse(manifest["source_inputs_verified"])
        self.assertEqual(manifest["gpu_post"], 0)

    def test_tamper_bad_slots_and_wrong_coverage_reject(self):
        for variant in ("graph", "slot", "class", "kit", "shot", "profile"):
            graph, recovery, bindings, package = fixture()
            if variant == "graph":
                graph["4"]["inputs"]["unet_name"] = "other"
            if variant == "slot":
                bindings["seed"]["input_name"] = "model"
            if variant == "class":
                bindings["positive_prompt"]["class_type"] = "Wrong"
            if variant == "kit":
                package["stage_results"]["keyframe_kit.v1"]["keyframes"][1]["still_prompt"] = "tampered"
            if variant == "shot":
                package["stage_results"]["shot_plan.v1"]["shots"][2]["shot_id"] = "other"
            if variant == "profile":
                package["stage_results"]["creative_brief.v1"]["output_profile_id"] = "vertical"
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                prepare(graph, recovery, bindings, package, "a" * 64, 0)

    def test_multi_variant_offline_export_is_deterministic_and_collector_compatible(self):
        # 04. Four seeds x three distinct frozen shots in one CPU-only
        #     operation. Every variant is an unchanged ordinary batch folder.
        graph, recovery, bindings, package = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(f"{PACKAGE_ID}/creative-package.json", canonical_bytes(package))
            digest = sha(archive.read_bytes())
            (root / "workflow_api.json").write_bytes(canonical_bytes(graph))
            (root / "recovery_manifest.json").write_bytes(canonical_bytes(recovery))
            (root / "map.json").write_bytes(canonical_bytes(bindings))
            opts = [
                "--package", str(archive), "--package-sha256", digest,
                "--recovery-dir", str(root), "--slot-map", str(root / "map.json"),
            ]
            target = root / "variants"
            args = opts + ["--variant", "7", "--variant-count", "4",
                           "--output-dir", str(target)]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 1)  # Never overwrite a completed export.
            index = json.loads((target / "variant_index.json").read_bytes())
            self.assertEqual(index["schema"], "picotoo.local-keyframe-variant-index.v1")
            self.assertEqual(index["variant_count"], 4)
            self.assertEqual(index["creative_package_sha256"], digest)
            self.assertFalse(index["production_authorized"])
            self.assertFalse(index["source_inputs_verified"])
            self.assertEqual(index["gpu_post"], 0)
            self.assertEqual(sorted(x.name for x in target.iterdir()),
                             ["v0007", "v0008", "v0009", "v0010", "variant_index.json"])
            variants = set()
            observed_seeds = set()
            for row in index["variants"]:
                version = row["variant"]
                variants.add(version)
                folder = target / row["relative_directory"]
                self.assertEqual(folder.name, f"v{version:04d}")
                self.assertEqual(len(list(folder.iterdir())), 4)
                raw = (folder / "batch_manifest.json").read_bytes()
                self.assertEqual(row["batch_manifest_sha256"], sha(raw))
                manifest = json.loads(raw)
                self.assertEqual(manifest["schema"], "picotoo.local-keyframe-batch-dry-run.v1")
                self.assertEqual(manifest["variant"], version)
                self.assertEqual([record["shot_id"] for record in manifest["shots"]],
                                 ["shot-1", "shot-2", "shot-3"])
                self.assertFalse(manifest["workflow_registered"])
                self.assertEqual(manifest["gpu_post"], 0)
                for record in manifest["shots"]:
                    candidate_bytes = (folder / record["graph_file"]).read_bytes()
                    candidate = json.loads(candidate_bytes)
                    self.assertEqual(record["graph_sha256"], sha(candidate_bytes))
                    self.assertEqual(candidate["1"]["inputs"]["text"],
                                     f"Opening state {record['order']}")
                    self.assertEqual(candidate["2"], graph["2"])
                    self.assertEqual(candidate["4"], graph["4"])
                    self.assertEqual(candidate["6"], graph["6"])
                    observed_seeds.add(candidate["3"]["inputs"]["seed"])
            self.assertEqual(variants, {7, 8, 9, 10})
            self.assertEqual(len(observed_seeds), 12)

            # 05. Bounds reject empty, excessive and overflow ranges
            #     BEFORE creating an output folder or writing any data.
            for bad_start, bad_count in [(0, 0), (0, 9), (10000, 2), (-1, 1)]:
                with self.subTest(start=bad_start, count=bad_count):
                    output = root / f"bad_{bad_start}_{bad_count}"
                    self.assertEqual(main(
                        opts + ["--variant", str(bad_start), "--variant-count",
                                str(bad_count), "--output-dir", str(output)]
                    ), 1)
                    self.assertFalse(output.exists())

            # 06. A single variant with an explicit count of one preserves
            #     the original 4-file layout (no index or nested folder).
            single = root / "single"
            self.assertEqual(main(
                opts + ["--variant", "7", "--variant-count", "1",
                        "--output-dir", str(single)]
            ), 0)
            self.assertEqual(len(list(single.iterdir())), 4)
            self.assertFalse((single / "variant_index.json").exists())
            self.assertEqual(
                (single / "batch_manifest.json").read_bytes(),
                (target / "v0007" / "batch_manifest.json").read_bytes()
            )

    def test_real_zip_digest_and_cli_no_overwrite(self):
        graph, recovery, bindings, package = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(f"{PACKAGE_ID}/creative-package.json", canonical_bytes(package))
            digest = sha(archive.read_bytes())
            self.assertEqual(read_package(archive, digest), package)
            with self.assertRaises(ValueError):
                read_package(archive, "b" * 64)
            (root / "workflow_api.json").write_bytes(canonical_bytes(graph))
            (root / "recovery_manifest.json").write_bytes(canonical_bytes(recovery))
            (root / "map.json").write_bytes(canonical_bytes(bindings))
            output = root / "batch"
            args = ["--package", str(archive), "--package-sha256", digest, "--recovery-dir", str(root),
                    "--slot-map", str(root / "map.json"), "--output-dir", str(output)]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 1)
            self.assertEqual(len(list(output.iterdir())), 4)
            self.assertFalse(json.loads((output / "batch_manifest.json").read_bytes())["production_authorized"])


if __name__ == "__main__":
    unittest.main()
