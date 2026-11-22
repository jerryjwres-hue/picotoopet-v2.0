"""Exact synthetic Comfy PNG metadata recovery, no model and no GPU."""
from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from scripts.comfy_png_embedded_evidence import recover_embedded_png
from scripts.recover_comfy_keyframe_workflow import canonical_bytes, main

GRAPH = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "old-scene.png"}},
    "7": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
        "prompt": "private original prompt", "image1": ["1", 0],
    }},
    "12": {"class_type": "KSampler", "inputs": {"seed": 1}},
    "14": {"class_type": "SaveImage", "inputs": {"filename_prefix": "PVP", "images": ["12", 0]}},
}


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload)) + kind + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    )


def png(graph: dict | None = GRAPH) -> bytes:
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 704, 8, 2, 0, 0, 0))
    metadata = [] if graph is None else [chunk(b"tEXt", b"prompt\x00" + canonical_bytes(graph))]
    return (b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(metadata)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff"))
            + chunk(b"IEND", b""))


class EmbeddedPngTests(unittest.TestCase):
    def test_extracts_graph_not_fictitious_history_or_rights(self) -> None:
        raw = png()
        graph_data, manifest = recover_embedded_png(raw, "observed.png")
        self.assertEqual(graph_data, canonical_bytes(GRAPH))
        self.assertEqual(manifest["source_image_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(manifest["source_image_dimensions"], [1280, 704])
        self.assertEqual(manifest["history_status"], "PNG_EMBEDDED_NO_HISTORY")
        self.assertIsNone(manifest["prompt_id"])
        self.assertTrue(manifest["source_image_container_crc_verified"])
        for key in ("production_authorized", "workflow_registered", "model_bytes_verified",
                    "binding_reviewed", "image_pixels_decoded"):
            self.assertFalse(manifest[key])
        self.assertNotIn("private original prompt", json.dumps(manifest))

    def test_corrupt_missing_duplicate_and_ui_only_rejected(self) -> None:
        for variant in ("tamper", "no_prompt", "duplicate", "ui_only",
                        "no_save", "trailing", "apng", "compressed"):
            with self.subTest(variant=variant):
                raw = png()
                if variant == "tamper":
                    raw = raw[:-9] + b"X" + raw[-8:]
                elif variant == "no_prompt":
                    raw = png(None)
                elif variant == "duplicate":
                    raw = (raw[:-12] + chunk(b"tEXt", b"prompt\x00" + canonical_bytes(GRAPH))
                           + raw[-12:])
                elif variant == "ui_only":
                    raw = png(None)[:-12] + chunk(b"tEXt", b"workflow\x00{}") + png(None)[-12:]
                elif variant == "no_save":
                    raw = png({"1": GRAPH["1"]})
                elif variant == "trailing":
                    raw += b"tail"
                elif variant == "apng":
                    raw = raw[:-12] + chunk(b"acTL", b"\x00" * 8) + raw[-12:]
                else:
                    raw = raw[:-12] + chunk(b"zTXt", b"prompt\x00rest") + raw[-12:]
                with self.assertRaises(ValueError):
                    recover_embedded_png(raw, "observed.png")

    def test_cli_requires_explicit_existing_png_and_never_posts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "original.png"
            source.write_bytes(png())
            output = root / "candidate"
            with patch("scripts.recover_comfy_keyframe_workflow.fetch_history") as network:
                self.assertEqual(main(["--png-file", str(source), "--output-dir", str(output)]), 0)
                self.assertEqual(main(["--png-file", str(source), "--output-dir", str(output)]), 1)
                network.assert_not_called()
            report = json.loads((output / "recovery_manifest.json").read_bytes())
            self.assertIsNone(report["prompt_id"])
            self.assertFalse(report["production_authorized"])
            self.assertEqual((output / "workflow_api.json").read_bytes(), canonical_bytes(GRAPH))
            self.assertEqual(len(list(output.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
