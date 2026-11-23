"""Full offline recovery -> frozen keyframes -> actual PNG evidence handoff.

Synthetic Comfy history and local image bytes only. No UI authorization,
Owner decision, local model, GPU submission, Comfy POST, or production Job.
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from collect_local_keyframe_outputs import collect  # noqa: E402
from prepare_local_keyframe_batch import prepare, read_package, sha  # noqa: E402
from recover_comfy_keyframe_workflow import canonical_bytes, recover  # noqa: E402

PACKAGE_ID = "22222222-2222-4222-8222-222222222222"
RECOVERY_PROMPT = "c424e4f0-d722-456c-a0fb-40bb02cfd91f"


def png(width: int) -> bytes:
    """Deterministic, independently decodable valid PNG for a synthetic still."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff))

    rows = b"".join(b"\x00" + b"\x55\x99\xee" * width for _ in range(9))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 9, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


def creative() -> dict:
    bible = {"schema_version": "fixture", "subject": "not-a-real-pet"}
    bible["bible_digest"] = sha(canonical_bytes(bible))
    frames = [
        {"shot_id": f"shot-{i}", "order": i, "still_prompt": f"state and camera for shot-{i}",
         "approval_status": "PENDING_HUMAN_REVIEW", "review_checklist": ["stable scene", "stable dog"]}
        for i in range(1, 4)
    ]
    kit = {
        "schema_version": "keyframe_kit.v1", "bible_digest": bible["bible_digest"],
        "keyframes": frames, "kit_digest": None,
    }
    kit["kit_digest"] = sha(canonical_bytes(
        {key: value for key, value in kit.items() if key != "bible_digest"}
    ))
    return {
        "schema_version": "1.0", "creative_package_id": PACKAGE_ID,
        "creative_profile": "creative.content_plan.v2", "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": {"output_profile_id": "video.landscape.v1"},
            "video_bible.v1": bible, "keyframe_kit.v1": kit,
            "shot_plan.v1": {"shots": [
                {"shot_id": f["shot_id"], "order": f["order"],
                 "duration_seconds": 4, "render_intent": "GENERATIVE_VIDEO"}
                for f in frames
            ]},
        },
    }


class FullOfflineHandoffTests(unittest.TestCase):
    def test_recovery_preparation_and_observation_share_exact_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_graph = {
                "1": {"class_type": "SyntheticText", "inputs": {"text": "old source"}},
                "2": {"class_type": "SyntheticSampler", "inputs": {"seed": 10}},
                "3": {"class_type": "SyntheticSaveImage", "inputs": {
                    "filename_prefix": "old/legacy", "image": ["2", 0],
                }},
                "4": {"class_type": "SyntheticReference", "inputs": {"image": "fixed.png"}},
            }
            # 01. Recover a successful still-producing historical Comfy prompt.
            historical = {
                RECOVERY_PROMPT: {
                    "status": {"status_str": "success", "completed": True},
                    "prompt": [1, RECOVERY_PROMPT, original_graph, {}, ["3"]],
                    "outputs": {"3": {"images": [
                        {"filename": "old.png", "subfolder": "", "type": "output"}
                    ]}},
                },
            }
            recovered_bytes, recovery = recover(historical, RECOVERY_PROMPT)
            self.assertEqual(recovered_bytes, canonical_bytes(original_graph))
            self.assertEqual(recovery["history_status"], "RECORDED_SUCCESS")
            self.assertFalse(recovery["production_authorized"])

            # 02. Freeze an actual ZIP with the same one-member Core layout.
            archive_path = root / "creative.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"{PACKAGE_ID}/creative-package.json", canonical_bytes(creative()))
            package_sha = sha(archive_path.read_bytes())
            package = read_package(archive_path, package_sha)
            bindings = {
                "schema": "picotoo.local-keyframe-slot-map.v1",
                "graph_sha256": recovery["graph_sha256"],
                "positive_prompt": {
                    "node_id": "1", "class_type": "SyntheticText", "input_name": "text",
                },
                "seed": {"node_id": "2", "class_type": "SyntheticSampler", "input_name": "seed"},
                "output_prefix": {
                    "node_id": "3", "class_type": "SyntheticSaveImage",
                    "input_name": "filename_prefix",
                },
            }
            graphs, batch = prepare(
                original_graph, recovery, bindings, package, package_sha, variant=4
            )
            self.assertEqual(len(graphs), 3)
            self.assertEqual(batch["creative_package_sha256"], package_sha)
            self.assertFalse(batch["source_inputs_verified"])
            self.assertEqual(original_graph["1"]["inputs"]["text"], "old source")

            # 03. Observe only exact completed Comfy histories and existing PNG bytes.
            batch_dir = root / "batch"
            output_dir = root / "comfy-output"
            batch_dir.mkdir()
            output_dir.mkdir()
            identity = {"schema": "picotoo.keyframe-prompt-identities.v1", "shots": []}
            histories = {}
            for number, record in enumerate(batch["shots"], 1):
                shot_id = record["shot_id"]
                prompt_id = f"00000000-0000-4000-8000-{number:012d}"
                identity["shots"].append({"shot_id": shot_id, "prompt_id": prompt_id})
                (batch_dir / record["graph_file"]).write_bytes(graphs[record["graph_file"]])
                prepared = json.loads(graphs[record["graph_file"]])
                image_path = f"{shot_id}.png"
                (output_dir / image_path).write_bytes(png(8 + number))
                histories[prompt_id] = {
                    prompt_id: {
                        "status": {"status_str": "success", "completed": True},
                        "prompt": [number, prompt_id, prepared, {}, ["3"]],
                        "outputs": {"3": {"images": [
                            {"filename": image_path, "subfolder": "", "type": "output"}
                        ]}},
                    },
                }
            evidence = collect(batch, batch_dir, identity, histories, output_dir)
            self.assertEqual(len(evidence["shots"]), 3)
            self.assertEqual(
                [shot["shot_id"] for shot in evidence["shots"]],
                ["shot-1", "shot-2", "shot-3"],
            )
            self.assertEqual(evidence["creative_package_sha256"], package_sha)
            self.assertEqual(evidence["keyframe_kit_digest"], batch["keyframe_kit_digest"])
            self.assertTrue(evidence["recorded_image_bytes_observed"])
            self.assertFalse(evidence["candidate_files_staged"])
            self.assertFalse(evidence["reference_approved"])
            self.assertFalse(evidence["source_rights_confirmed"])
            self.assertEqual(evidence["gpu_post"], 0)
            self.assertEqual(
                evidence, collect(batch, batch_dir, identity, histories, output_dir)
            )

            # 04. Changing one frozen graph invalidates the end-to-end link.
            first_graph = batch_dir / batch["shots"][0]["graph_file"]
            first_graph.write_bytes(canonical_bytes({"1": {"class_type": "forged"}}))
            with self.assertRaises(ValueError):
                collect(batch, batch_dir, identity, histories, output_dir)


if __name__ == "__main__":
    unittest.main()
