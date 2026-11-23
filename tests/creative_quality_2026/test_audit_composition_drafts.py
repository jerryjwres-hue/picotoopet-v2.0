"""Synthetic offline contract tests; no user images, ComfyUI, or GPU."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.audit_composition_drafts import audit, main  # noqa: E402
from scripts.recover_comfy_keyframe_workflow import canonical_bytes  # noqa: E402


def digest(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def chunk(name: bytes, payload: bytes) -> bytes:
    # 01. Encode valid PNG chunks with CRCs and unmodified Comfy prompt JSON.
    body = name + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)


def png(graph: dict) -> bytes:
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"prompt\x00" + canonical_bytes(graph))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
            + chunk(b"IEND", b""))


def fixture(root: Path) -> tuple[Path, Path, Path]:
    bootstrap, review = root / "bootstrap", root / "review"
    bootstrap.mkdir()
    review.mkdir()
    entries = []
    for variant in (0, 1):
        folder = bootstrap / f"v{variant:04d}"
        folder.mkdir()
        shots = []
        for order in (1, 2, 3):
            shot_id = f"SHOT_{order:03d}"
            seed = 1234567890123400 + variant * 100 + order
            positive = f"Shot {order} creative draft"
            graph = {
                "8": {"class_type": "TextEncodeQwenImageEditPlus",
                      "inputs": {"prompt": positive}},
                "9": {"class_type": "TextEncodeQwenImageEditPlus",
                      "inputs": {"prompt": "negative prompt frozen"}},
                "10": {"class_type": "KSampler",
                       "inputs": {"seed": seed, "positive": ["8", 0],
                                  "negative": ["9", 0]}},
                "11": {"class_type": "SaveImage",
                       "inputs": {"filename_prefix":
                           f"PicotooPet/composition_bootstrap/{'a'*16}/{shot_id}/v{variant:04d}"}},
            }
            raw_graph = canonical_bytes(graph)
            graph_name = f"{order:02d}-{shot_id}.json"
            (folder / graph_name).write_bytes(raw_graph)
            shots.append({
                "shot_id": shot_id, "order": order,
                "graph_file": graph_name, "graph_sha256": digest(raw_graph),
                "seed": seed, "still_prompt_sha256": digest(positive.encode("utf-8")),
                "human_visual_review": "NOT_PERFORMED",
                "generated_composition": None,
            })
            (review / f"v{variant:04d}_{shot_id}_shot{order}.png").write_bytes(png(graph))
        manifest = {
            "schema": "picotoo.local-composition-bootstrap-dry-run.v1",
            "variant": variant, "creative_package_sha256": "a" * 64,
            "keyframe_kit_digest": "b" * 64,
            "source_graph_sha256": "c" * 64,
            "source_inputs_verified": False, "reference_approved": False,
            "workflow_registered": False,
            "historical_composition_reused_as_guidance_only": True,
            "distinct_shot_compositions_observed": False,
            "source_render_intents_converted": False,
            "production_authorized": False,
            "source_profile_conversion_performed": False,
            "target_geometry_verified": False,
            "gpu_post": 0, "shots": shots,
        }
        raw_manifest = canonical_bytes(manifest)
        (folder / "batch_manifest.json").write_bytes(raw_manifest)
        entries.append({"variant": variant, "relative_directory": folder.name,
                        "shot_count": 3,
                        "batch_manifest_sha256": digest(raw_manifest)})
    index = {"schema": "picotoo.local-composition-bootstrap-index.v1",
             "variant_count": 2, "variants": entries,
             "creative_package_sha256": "a" * 64, "keyframe_kit_digest": "b" * 64,
             "source_inputs_verified": False,
             "production_authorized": False, "gpu_post": 0}
    (bootstrap / "variant_index.json").write_bytes(canonical_bytes(index))
    (review / "creative_review_index.json").write_bytes(b"{}")
    return bootstrap, review, root / "audit.json"


class CompositionDraftAuditTests(unittest.TestCase):
    def test_six_images_grouped_by_shot_without_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            bootstrap, review, report = fixture(Path(temp))
            result = audit(bootstrap, review)
            self.assertEqual(result["candidate_count"], 6)
            self.assertEqual([x["shot_id"] for x in result["candidate_groups"]],
                             ["SHOT_001", "SHOT_002", "SHOT_003"])
            self.assertTrue(all([x["variant"] for x in group["candidates"]] == [0, 1]
                                for group in result["candidate_groups"]))
            self.assertFalse(result["production_authorized"])
            self.assertFalse(result["reference_approved"])
            self.assertFalse(result["comfy_history_independently_verified"])
            self.assertEqual(result["visual_review_status"], "NEEDS_HUMAN_REVIEW")
            args = ["--bootstrap-dir", str(bootstrap), "--review-dir", str(review),
                    "--report-file", str(report)]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 1)  # Never overwrite a report.
            self.assertEqual(json.loads(report.read_bytes()), result)

    def test_review_index_original_names_bind_to_staged_copies_by_sha(self):
        # 10. Render history uses original SHOT_001 labels; staged evidence
        #     can be named after an actual frozen shot ID like "shot1".
        #     Only exact PNG SHA256 equality makes that rename auditable.
        with tempfile.TemporaryDirectory() as temp:
            bootstrap, review, _ = fixture(Path(temp))
            originals = []
            for variant in (0, 1):
                for order in (1, 2, 3):
                    original_name = f"v{variant:04d}_SHOT_{order:03d}_shot{order}.png"
                    staged = review / original_name
                    raw = staged.read_bytes()
                    # 11. Rename only a synthetic evidence COPY, not a
                    #     Comfy output. The original owner-index label stays.
                    copy_name = f"v{variant:04d}_shot{order}_shot{order}.png"
                    staged.rename(review / copy_name)
                    originals.append({
                        "output_image": original_name,
                        "output_image_sha256": digest(raw),
                    })
                    folder = bootstrap / f"v{variant:04d}"
                    manifest_path = folder / "batch_manifest.json"
                    manifest = json.loads(manifest_path.read_bytes())
                    shot = manifest["shots"][order - 1]
                    new_graph_name = f"{order:02d}-shot{order}.json"
                    (folder / shot["graph_file"]).rename(folder / new_graph_name)
                    shot["shot_id"] = f"shot{order}"
                    shot["graph_file"] = new_graph_name
                    graph = json.loads((folder / new_graph_name).read_bytes())
                    graph["11"]["inputs"]["filename_prefix"] = (
                        f"PicotooPet/composition_bootstrap/{'a'*16}/shot{order}/v{variant:04d}"
                    )
                    raw_graph = canonical_bytes(graph)
                    (folder / new_graph_name).write_bytes(raw_graph)
                    shot["graph_sha256"] = digest(raw_graph)
                    (review / copy_name).write_bytes(png(graph))
                    # 12. The renamed synthetic graph changes actual PNG
                    #     bytes, so update the independent owner index SHA.
                    originals[-1]["output_image_sha256"] = digest((review / copy_name).read_bytes())
                    new_manifest = canonical_bytes(manifest)
                    manifest_path.write_bytes(new_manifest)
                    index_path = bootstrap / "variant_index.json"
                    index = json.loads(index_path.read_bytes())
                    index["variants"][variant]["batch_manifest_sha256"] = digest(new_manifest)
                    index_path.write_bytes(canonical_bytes(index))
            (review / "creative_review_index.json").write_bytes(
                canonical_bytes({"renders": originals})
            )
            result = audit(bootstrap, review)
            self.assertTrue(result["review_index_output_bindings_verified"])
            self.assertEqual(result["review_index_bound_image_count"], 6)
            self.assertEqual(len(result["review_index_image_bindings"]), 6)
            self.assertTrue(all(item["same_bytes_verified"]
                                for item in result["review_index_image_bindings"]))
            self.assertNotEqual(
                result["review_index_image_bindings"][0]["original_output_image"],
                result["review_index_image_bindings"][0]["staged_evidence_image"],
            )
            self.assertFalse(result["comfy_history_independently_verified"])
            self.assertFalse(result["production_authorized"])

            # 13. A claimed owner index hash cannot falsely bind different
            #     bytes, even when all six staged image graphs stay valid.
            originals[2]["output_image_sha256"] = "f" * 64
            (review / "creative_review_index.json").write_bytes(
                canonical_bytes({"renders": originals})
            )
            with self.assertRaisesRegex(
                ValueError, "COMPOSITION_REVIEW_INDEX_IMAGE_HASH_MISMATCH",
            ):
                audit(bootstrap, review)

    def test_partial_or_unrecognized_review_index_never_verified(self):
        # 14. A syntactically valid index alone does not prove any mapping.
        with tempfile.TemporaryDirectory() as temp:
            bootstrap, review, _ = fixture(Path(temp))
            result = audit(bootstrap, review)
            self.assertFalse(result["review_index_output_bindings_verified"])
            self.assertEqual(result["review_index_bound_image_count"], 0)
            self.assertEqual(
                result["review_index_binding_status"], "UNVERIFIED_SCHEMA_OR_COVERAGE",
            )

    def test_optional_source_graph_is_sha_pinned_and_frozen_nodes_match(self):
        # 15. "All six share one graph" alone does not prove they preserve
        #     the original recovered graph. Check the source when supplied.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bootstrap, review, report = fixture(root)
            source = bootstrap / "v0000" / "01-SHOT_001.json"
            raw = source.read_bytes()
            source_path = root / "workflow_api.json"
            source_path.write_bytes(raw)
            index_path = bootstrap / "variant_index.json"
            index = json.loads(index_path.read_bytes())
            for variant in (0, 1):
                manifest_path = bootstrap / f"v{variant:04d}" / "batch_manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                manifest["source_graph_sha256"] = digest(raw)
                raw_manifest = canonical_bytes(manifest)
                manifest_path.write_bytes(raw_manifest)
                index["variants"][variant]["batch_manifest_sha256"] = digest(raw_manifest)
            index_path.write_bytes(canonical_bytes(index))
            verified = audit(bootstrap, review, source_path)
            self.assertTrue(verified["source_graph_allowlist_independently_verified"])
            self.assertFalse(verified["review_index_output_bindings_verified"])
            self.assertEqual(main([
                "--bootstrap-dir", str(bootstrap),
                "--review-dir", str(review),
                "--source-graph-file", str(source_path),
                "--report-file", str(report),
            ]), 0)

            # 16. Even a source that shares the same positive prompt, Seed
            #     and prefix must fail if its frozen nodes were altered.
            forged = json.loads(raw)
            forged["9"]["inputs"]["prompt"] = "modified source negative"
            forged_raw = canonical_bytes(forged)
            source_path.write_bytes(forged_raw)
            for variant in (0, 1):
                manifest_path = bootstrap / f"v{variant:04d}" / "batch_manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                manifest["source_graph_sha256"] = digest(forged_raw)
                raw_manifest = canonical_bytes(manifest)
                manifest_path.write_bytes(raw_manifest)
                index["variants"][variant]["batch_manifest_sha256"] = digest(raw_manifest)
            index_path.write_bytes(canonical_bytes(index))
            with self.assertRaisesRegex(
                ValueError, "COMPOSITION_REVIEW_SOURCE_GRAPH_FROZEN_MISMATCH",
            ):
                audit(bootstrap, review, source_path)

    def test_missing_corrupt_and_wrong_embedded_graph_rejected(self):
        for failure in ("missing", "bad_crc", "wrong_graph"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                target = review / "v0000_SHOT_002_shot2.png"
                if failure == "missing":
                    target.unlink()
                elif failure == "bad_crc":
                    data = bytearray(target.read_bytes())
                    data[-5] ^= 1
                    target.write_bytes(data)
                else:
                    target.write_bytes(png({
                        "10": {"class_type": "KSampler", "inputs": {"seed": 987}},
                        "11": {"class_type": "SaveImage",
                               "inputs": {"filename_prefix": "test"}},
                    }))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    audit(bootstrap, review)

    def test_graph_tamper_and_fake_approval_rejected(self):
        for failure in ("graph", "approval"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                if failure == "graph":
                    path = bootstrap / "v0000" / "01-SHOT_001.json"
                    path.write_bytes(path.read_bytes() + b" ")
                else:
                    path = bootstrap / "v0000" / "batch_manifest.json"
                    document = json.loads(path.read_bytes())
                    document["reference_approved"] = True
                    path.write_bytes(canonical_bytes(document))
                with self.assertRaises(ValueError):
                    audit(bootstrap, review)

    def test_duplicate_json_fields_and_nonfinite_values_rejected(self):
        # 05. Duplicate keys and NaN must not alter approval interpretation.
        for alteration in ("duplicate", "nonfinite"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                manifest = bootstrap / "v0000" / "batch_manifest.json"
                raw = manifest.read_bytes()
                if alteration == "duplicate":
                    raw = raw.replace(b'"reference_approved":false,',
                                      b'"reference_approved":true,"reference_approved":false,')
                else:
                    raw = raw.replace(b'"gpu_post":0', b'"gpu_post":NaN')
                manifest.write_bytes(raw)
                # Attackers who can replace the index can forge its digest.
                index_path = bootstrap / "variant_index.json"
                index = json.loads(index_path.read_bytes())
                index["variants"][0]["batch_manifest_sha256"] = digest(raw)
                index_path.write_bytes(canonical_bytes(index))
                with self.assertRaises(ValueError):
                    audit(bootstrap, review)

    def test_forged_output_authority_flags_rejected_even_when_rehashed(self):
        # 06. Internal consistency alone cannot confer approval.
        for key, value in (
            ("workflow_registered", True),
            ("historical_composition_reused_as_guidance_only", False),
            ("distinct_shot_compositions_observed", True),
            ("source_render_intents_converted", True),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                manifest_path = bootstrap / "v0000" / "batch_manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                manifest[key] = value
                raw = canonical_bytes(manifest)
                manifest_path.write_bytes(raw)
                index_path = bootstrap / "variant_index.json"
                index = json.loads(index_path.read_bytes())
                index["variants"][0]["batch_manifest_sha256"] = digest(raw)
                index_path.write_bytes(canonical_bytes(index))
                with self.assertRaises(ValueError):
                    audit(bootstrap, review)

    def test_cross_variant_frozen_graph_and_prompt_hash_rejected(self):
        # 09. Rehashing a valid PNG must not hide changes to frozen Qwen nodes.
        for alteration in ("negative_prompt", "model_selector", "prompt_digest"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                folder = bootstrap / "v0001"
                graph_path = folder / "02-SHOT_002.json"
                manifest_path = folder / "batch_manifest.json"
                graph = json.loads(graph_path.read_bytes())
                manifest = json.loads(manifest_path.read_bytes())
                if alteration == "negative_prompt":
                    graph["9"]["inputs"]["prompt"] = "silent negative prompt tamper"
                elif alteration == "model_selector":
                    graph["10"]["inputs"]["model"] = ["other", 0]
                else:
                    graph["8"]["inputs"]["prompt"] = "different prompt"
                raw_graph = canonical_bytes(graph)
                graph_path.write_bytes(raw_graph)
                manifest["shots"][1]["graph_sha256"] = digest(raw_graph)
                if alteration == "prompt_digest":
                    manifest["shots"][1]["still_prompt_sha256"] = "f" * 64
                raw_manifest = canonical_bytes(manifest)
                manifest_path.write_bytes(raw_manifest)
                (review / "v0001_SHOT_002_shot2.png").write_bytes(png(graph))
                index_path = bootstrap / "variant_index.json"
                index = json.loads(index_path.read_bytes())
                index["variants"][1]["batch_manifest_sha256"] = digest(raw_manifest)
                index_path.write_bytes(canonical_bytes(index))
                with self.assertRaises(ValueError):
                    audit(bootstrap, review)

    def test_missing_or_malformed_review_index_rejected(self):
        # 07. The operator-created evidence index is mandatory but is not approval.
        for case in ("missing", "malformed", "duplicate"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                bootstrap, review, _ = fixture(Path(temp))
                index = review / "creative_review_index.json"
                if case == "missing":
                    index.unlink()
                elif case == "malformed":
                    index.write_bytes(b"not json")
                else:
                    index.write_bytes(b'{"a":1,"a":2}')
                with self.assertRaises((ValueError, FileNotFoundError)):
                    audit(bootstrap, review)

    def test_cli_does_not_follow_symlinked_evidence_directory(self):
        # 08. The CLI must reject a symlink even if resolve() finds a real tree.
        with tempfile.TemporaryDirectory() as temp:
            bootstrap, review, report = fixture(Path(temp))
            shortcut = Path(temp) / "review-shortcut"
            try:
                shortcut.symlink_to(review, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink unavailable on this host")
            self.assertEqual(main([
                "--bootstrap-dir", str(bootstrap),
                "--review-dir", str(shortcut),
                "--report-file", str(report),
            ]), 1)
            self.assertFalse(report.exists())

    def test_symlink_and_output_under_evidence_tree_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            bootstrap, review, _ = fixture(Path(temp))
            image = review / "v0000_SHOT_001_shot1.png"
            original = review / "original.png"
            image.rename(original)
            try:
                image.symlink_to(original)
            except OSError:
                self.skipTest("Symlink unavailable on this host")
            with self.assertRaises(ValueError):
                audit(bootstrap, review)
            image.unlink()
            original.rename(image)
            report = review / "audit.json"
            self.assertEqual(main([
                "--bootstrap-dir", str(bootstrap), "--review-dir", str(review),
                "--report-file", str(report),
            ]), 1)
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
