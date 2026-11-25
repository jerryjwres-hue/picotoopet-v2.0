"""Synthetic CPU-only acceptance for reuse of the existing real FLUX board runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_existing_flux_board_shot.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("_existing_flux_board_handoff", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

SYNTHETIC_BUILDER = '''# Synthetic only: matches the handoff API, never runs ComfyUI.
def build(job, seed, ref_names):
    # 01. Distinct fake nodes intentionally exercise the exact requested
    #     prompt/seed/model/LoadImage/SaveImage values without GPU.
    g = {
        "4": {"inputs": {"text": job["prompt"]}},
        "6": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "strength_model": job["lora"]["strength"]}},
        "20": {"inputs": {"width": job["w"], "height": job["h"]}},
        "23": {"inputs": {"noise_seed": seed}},
        "27": {"inputs": {"filename_prefix": "PTV2_" + job["id"]}},
    }
    for i, name in enumerate(ref_names):
        g[str(100+10*i)] = {"inputs": {"image": name}}
    return g
'''


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ExistingFluxBoardHandoffTests(unittest.TestCase):
    def setUp(self):
        # 02. Every CI file is synthetic and lives in a temporary folder.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / "run_flux_board.py"
        self.runner.write_text(SYNTHETIC_BUILDER, encoding="utf-8")
        (self.root / "refs_real").mkdir()
        (self.root / "refs").mkdir()
        self.character = self.root / "refs_real" / "synthetic_C8B.png"
        self.scene = self.root / "refs" / "synthetic_B1.png"
        self.character.write_bytes(b"synthetic-character-master-C8B")
        self.scene.write_bytes(b"synthetic-scene-master-B1")
        self.lora = self.root / "maotai_lora_v2.safetensors"
        self.lora.write_bytes(b"synthetic-lora-v2")
        self.request = self.root / "request.json"
        self.output = self.root / "handoff"
        self.output.mkdir()
        self.value = {
            "schema": module.REQUEST_SCHEMA,
            "source_storypack_sha256": "a" * 64,
            "source_output_profile": "p0_landscape",
            "shot_id": "S02",
            "seed": 2026112901,
            "prompt": "mtai_dog, adult malamute beside bowl in same room, single dog",
            "references": [
                {"role": "character_master", "relative_path": "refs_real/synthetic_C8B.png",
                 "sha256": _sha(self.character.read_bytes())},
                {"role": "scene_master", "relative_path": "refs/synthetic_B1.png",
                 "sha256": _sha(self.scene.read_bytes())},
            ],
        }
        self.patches = [
            patch.object(module, "RUNNER_SHA256", _sha(self.runner.read_bytes())),
            patch.object(module, "C8B_MASTER_SHA256", _sha(self.character.read_bytes())),
            patch.object(module, "LORA_V2_SHA256", _sha(self.lora.read_bytes())),
            patch.object(module, "LORA_V2_SIZE", len(self.lora.read_bytes())),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def run_prepare(self):
        self.request.write_text(json.dumps(self.value), encoding="utf-8")
        return module.prepare(
            request_file=self.request,
            runner_file=self.runner,
            lora_file=self.lora,
            output_dir=self.output,
        )

    def test_exact_legacy_build_is_reused_without_gpu_or_source_mutation(self):
        # 03. One caller-approved shot maps to one seed, one jobs spec, one
        #     embedded graph; no video, model start, network or Comfy POST.
        before = {
            p: p.read_bytes() for p in (self.runner, self.character, self.scene, self.lora)
        }
        result = self.run_prepare()
        self.assertEqual(len(list(self.output.iterdir())), 3)
        self.assertEqual(result["shot_id"], "S02")
        self.assertEqual(result["seed"], 2026112901)
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["owner_approved"])
        self.assertFalse(result["existing_runner_executed"])
        self.assertEqual(result["gpu_post"], 0)
        self.assertFalse(result["target_geometry_verified"])
        self.assertEqual(result["source_output_profile"], "p0_landscape")
        # 03b. Local scene bytes are real, but no Core artifact binding or
        #      Owner approval can be inferred from a request-supplied SHA.
        self.assertEqual(result["scene_source_sha256"], _sha(self.scene.read_bytes()))
        self.assertTrue(result["scene_local_bytes_verified"])
        self.assertFalse(result["scene_core_artifact_binding_verified"])
        self.assertFalse(result["scene_owner_approval_verified"])
        self.assertFalse(result["source_profile_conversion_performed"])
        self.assertEqual(result["draft_still_profile"], "flux2.still.864x1536.v1")
        jobs = json.loads((self.output / "flux_board_single_job.json").read_bytes())
        self.assertEqual(jobs["jobs"][0]["seeds"], [2026112901])
        self.assertEqual(jobs["jobs"][0]["lora"]["strength"], 0.9)
        self.assertEqual(jobs["jobs"][0]["refs"], [
            "refs_real/synthetic_C8B.png", "refs/synthetic_B1.png"
        ])
        graph = json.loads((self.output / "flux_board_candidate_api_graph.json").read_bytes())
        self.assertEqual(graph["100"]["inputs"]["image"], "PTV2_synthetic_C8B.png")
        self.assertEqual(graph["110"]["inputs"]["image"], "PTV2_synthetic_B1.png")
        self.assertEqual(graph["6"]["inputs"]["strength_model"], 0.9)
        self.assertEqual(graph["23"]["inputs"]["noise_seed"], 2026112901)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        for filename, field in [
            ("flux_board_single_job.json", "job_file_sha256"),
            ("flux_board_candidate_api_graph.json", "api_graph_sha256"),
        ]:
            self.assertEqual(_sha((self.output / filename).read_bytes()), result[field])

    def test_changed_source_or_lora_or_reference_stops_without_partial_output(self):
        # 04. A script change, wrong source reference, or LoRA mismatch
        #     must not create even one output file.
        for path, code in [
            (self.runner, "RUNNER_SOURCE_SHA_MISMATCH"),
            (self.character, "REFERENCE_SHA_MISMATCH"),
            (self.lora, "LORA_V2_SHA_MISMATCH"),
        ]:
            original = path.read_bytes()
            path.write_bytes(original + b"bad")
            with self.assertRaisesRegex(ValueError, code):
                self.run_prepare()
            self.assertEqual(list(self.output.iterdir()), [])
            path.write_bytes(original)

    def test_wrong_order_wrong_identity_and_untrusted_paths_fail_closed(self):
        # 05. Cannot accidentally train or generate from the old c001/v1,
        #     a forged SHA, a second dog, or relative path traversal.
        variations = [
            ("REFERENCE_ORDER_INVALID", lambda a: a["references"].reverse()),
            ("REFERENCE_RELATIVE_PATH_INVALID", lambda a: a["references"][0].update(
                relative_path="../private.png")),
            ("REFERENCE_RELATIVE_PATH_INVALID", lambda a: a["references"][0].update(
                relative_path=r"D:\private.png")),
            ("SHA256_REQUIRED", lambda a: a["references"][0].update(sha256="abcdef")),
            ("PROMPT_TRIGGER_INVALID", lambda a: a.update(prompt="dog by the bowl")),
            ("SHOT_ID_INVALID", lambda a: a.update(shot_id="SHOT_002")),
            ("SEED_INVALID", lambda a: a.update(seed=True)),
            ("SOURCE_PROFILE_UNKNOWN", lambda a: a.update(
                source_output_profile="invalid")),
        ]
        for code, change in variations:
            with self.subTest(code=code):
                original = json.loads(json.dumps(self.value))
                change(self.value)
                with self.assertRaisesRegex(ValueError, code):
                    self.run_prepare()
                self.assertEqual(list(self.output.iterdir()), [])
                self.value = original

    def test_deny_symlinks_reused_output_and_duplicates(self):
        # 06. Never overwrite a previous run or follow deceptive reference paths.
        self.run_prepare()
        with self.assertRaisesRegex(ValueError, "OUTPUT_DIR_MUST_BE_EMPTY"):
            self.run_prepare()
        self.output = self.root / "new-handoff"
        self.output.mkdir()
        link = self.root / "refs" / "alias.png"
        try:
            link.symlink_to(self.character)
        except (OSError, NotImplementedError):
            self.skipTest("Host cannot create symlinks")
        self.value["references"][0]["relative_path"] = "refs/alias.png"
        self.value["references"][0]["sha256"] = _sha(self.character.read_bytes())
        with self.assertRaisesRegex(ValueError, "REFERENCE_SYMLINK_DENIED"):
            self.run_prepare()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_duplicate_json_key_rejected(self):
        # 07. Duplicate keys cannot switch SHA or prompt after human review.
        self.request.write_text(
            '{"schema":"%s","schema":"bad"}' % module.REQUEST_SCHEMA,
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
            module.prepare(request_file=self.request, runner_file=self.runner,
                           lora_file=self.lora, output_dir=self.output)


    def test_core_batch_and_single_shot_reroll_use_frozen_kit(self):
        # 01. Real Core ZIP parser and existing frozen-kit checks, synthetic assets.
        from test_prepare_local_keyframe_batch import fixture, PACKAGE_ID
        from prepare_local_keyframe_batch import canonical_bytes
        _, _, _, package = fixture()
        package["stage_results"]["creative_brief.v1"]["output_profile_id"] = "video.vertical.v1"
        archive = self.root / "package.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(f"{PACKAGE_ID}/creative-package.json", canonical_bytes(package))
        digest = _sha(archive.read_bytes())
        bindings = self.root / "bindings.json"
        mapping = {"schema": "picotoo.flux-board-reference-map.v1", "creative_package_sha256": digest,
                   "shots": {f"shot-{i}": self.value["references"] for i in range(1, 4)}}
        bindings.write_text(json.dumps(mapping), encoding="utf-8")
        def run(name, variant, shot=None):
            return module.prepare_package_batch(package_file=archive, package_sha=digest,
                bindings_file=bindings, runner_file=self.runner, lora_file=self.lora,
                output_dir=self.root / name, variant=variant, selected_shot=shot)
        batch = run("batch", 0)
        self.assertEqual([x["shot_id"] for x in batch["shots"]], ["shot-1", "shot-2", "shot-3"])
        self.assertEqual(len({x["seed"] for x in batch["shots"]}), 3)
        self.assertFalse(batch["production_authorized"])
        for record in batch["shots"]:
            folder = self.root / "batch" / record["relative_directory"]
            raw = (folder / "flux_board_candidate_api_graph.json").read_bytes()
            self.assertEqual(_sha(raw), record["api_graph_sha256"])
            self.assertEqual(_sha(raw.rstrip(b"\n")), record["graph_canonical_sha256"])
            self.assertEqual(json.loads(raw)["4"]["inputs"]["text"],
                             f"mtai_dog, Opening state {record['order']}")
        reroll = run("reroll", 1, "shot-2")
        self.assertEqual(len(reroll["shots"]), 1)
        self.assertNotEqual(reroll["shots"][0]["seed"], batch["shots"][1]["seed"])
        before = (self.root / "batch" / "batch_manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "OUTPUT_DIR_MUST_BE_NEW"):
            run("batch", 1)
        self.assertEqual((self.root / "batch" / "batch_manifest.json").read_bytes(), before)
        del mapping["shots"]["shot-3"]
        bindings.write_text(json.dumps(mapping), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CORE_SHOT_REFERENCES_MISSING"):
            run("missing", 0)
        self.assertFalse((self.root / "missing").exists())
