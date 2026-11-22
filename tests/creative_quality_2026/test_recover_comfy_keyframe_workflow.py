"""Synthetic recovery regression: no real ComfyUI, GPU, models or user data."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.recover_comfy_keyframe_workflow import (
    canonical_bytes,
    fetch_history,
    main,
    parse_history,
    recover,
)

PROMPT_ID = "0fb84d1d-9430-44c9-b1a5-94daa750ff9a"
OTHER_ID = "11111111-1111-4111-8111-111111111111"


def fixture() -> dict:
    # Synthetic class names: never claim this is the actual installed FLUX graph.
    return {
        PROMPT_ID: {
            "status": {"status_str": "success", "completed": True},
            "prompt": [1, PROMPT_ID, {
                "1": {"class_type": "SyntheticImageModel",
                      "inputs": {"unet_name": "synthetic.safetensors"}},
                "2": {"class_type": "SyntheticText",
                      "inputs": {"text": "private synthetic prompt", "model": ["1", 0]}},
                "3": {"class_type": "SyntheticOutput",
                      "inputs": {"images": ["2", 0], "filename_prefix": "fixture"}},
            }, {}, ["3"]],
            "outputs": {"3": {"images": [{"filename": "fixture.png", "type": "output"}]}},
        },
    }


class RecoveryTests(unittest.TestCase):
    def test_exact_graph_and_no_authority(self) -> None:
        history = fixture()
        data, manifest = recover(history, PROMPT_ID)
        self.assertEqual(data, canonical_bytes(history[PROMPT_ID]["prompt"][2]))
        self.assertEqual(manifest["graph_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest["node_inventory"][1]["candidate_input_slots"], ["text"])
        self.assertNotIn("private synthetic prompt", json.dumps(manifest))
        for flag in ("image_bytes_verified", "model_bytes_verified", "binding_reviewed",
                     "workflow_registered", "production_authorized"):
            self.assertIs(manifest[flag], False)
        self.assertEqual(manifest["gpu_post"], 0)

    def test_wrong_id_failed_job_and_nonimage_reject(self) -> None:
        with self.assertRaises(ValueError):
            recover(fixture(), OTHER_ID)
        for variant in ("failed", "mismatch", "video", "no_output", "unknown_node"):
            with self.subTest(variant=variant):
                history = fixture()
                entry = history[PROMPT_ID]
                if variant == "failed":
                    entry["status"]["status_str"] = "error"
                elif variant == "mismatch":
                    entry["prompt"][1] = OTHER_ID
                elif variant == "video":
                    entry["outputs"]["3"]["images"][0]["filename"] = "fixture.webm"
                elif variant == "no_output":
                    entry["outputs"] = {}
                else:
                    entry["outputs"]["999"] = entry["outputs"].pop("3")
                with self.assertRaises(ValueError):
                    recover(history, PROMPT_ID)

    def test_malformed_or_duplicate_json_reject(self) -> None:
        for raw in (b"", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_history(raw)

    def test_offline_export_no_network_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            history.write_bytes(canonical_bytes(fixture()))
            target = root / "export"
            args = ["--prompt-id", PROMPT_ID, "--history-file", str(history),
                    "--output-dir", str(target)]
            with patch("scripts.recover_comfy_keyframe_workflow.fetch_history") as network:
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
                network.assert_not_called()
            original, manifest = recover(fixture(), PROMPT_ID)
            self.assertEqual((target / "workflow_api.json").read_bytes(), original)
            self.assertEqual(json.loads((target / "recovery_manifest.json").read_bytes()), manifest)

    def test_live_client_fixed_loopback_get(self) -> None:
        with patch("scripts.recover_comfy_keyframe_workflow.urllib.request.build_opener") as build:
            opener = build.return_value
            opener.open.return_value.__enter__.return_value.read.return_value = b"{}"
            self.assertEqual(fetch_history(PROMPT_ID), b"{}")
            req = opener.open.call_args.args[0]
            self.assertEqual(req.full_url, "http://127.0.0.1:8188/history/" + PROMPT_ID)
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(build.call_args.args[0].proxies, {})
            with self.assertRaises(ValueError):
                fetch_history("../../prompt")
            self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
