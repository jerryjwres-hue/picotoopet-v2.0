"""CPU-only exact output evidence tests; synthetic images and Comfy histories."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from collect_local_keyframe_outputs import (  # noqa: E402
    collect, collect_variant_snapshot, discover_exact_prompt_ids, fetch_recent_history,
    file_sha, main, png_chunks_checked, safe_components,
)
from recover_comfy_keyframe_workflow import canonical_bytes  # noqa: E402


def png(width: int, height: int) -> bytes:
    def chunk(name: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + name + value + struct.pack(
            ">I", zlib.crc32(name + value) & 0xffffffff
        )
    pixels = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def fixture(root: Path):
    batch_dir = root / "batch"
    batch_dir.mkdir()
    output_root = root / "comfy-output"
    output_root.mkdir()
    history_dir = root / "history"
    history_dir.mkdir()
    records, ids, histories = [], [], {}
    for i in range(1, 4):
        shot = f"shot-{i}"
        prompt_id = f"00000000-0000-4000-8000-{i:012d}"
        graph = {
            "1": {"class_type": "SyntheticText", "inputs": {"text": shot}},
            "2": {"class_type": "SyntheticSave", "inputs": {"filename_prefix": shot}},
        }
        graph_bytes = canonical_bytes(graph)
        filename = f"{i:02d}-{shot}.json"
        (batch_dir / filename).write_bytes(graph_bytes)
        (output_root / f"{shot}.png").write_bytes(png(15 + i, 9))
        records.append({"shot_id": shot, "order": i, "graph_file": filename,
                        "graph_sha256": file_sha(graph_bytes)})
        ids.append({"shot_id": shot, "prompt_id": prompt_id})
        histories[prompt_id] = {
            prompt_id: {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "prompt": [i, prompt_id, graph, {}, ["2"]],
                "outputs": {"2": {"images": [
                    {"type": "output", "subfolder": "", "filename": f"{shot}.png"}
                ]}},
            }
        }
        (history_dir / f"{prompt_id}.json").write_bytes(canonical_bytes(histories[prompt_id]))
    batch = {
        "schema": "picotoo.local-keyframe-batch-dry-run.v1",
        "creative_package_id": "22222222-2222-4222-8222-222222222222",
        "creative_package_sha256": "a" * 64, "source_graph_sha256": "b" * 64,
        "keyframe_kit_digest": "c" * 64, "slot_map_sha256": "d" * 64,
        "shots": records, "production_authorized": False,
        "source_inputs_verified": False, "gpu_post": 0,
    }
    identities = {"schema": "picotoo.keyframe-prompt-identities.v1", "shots": ids}
    (batch_dir / "batch_manifest.json").write_bytes(canonical_bytes(batch))
    (root / "prompt_ids.json").write_bytes(canonical_bytes(identities))
    return batch, batch_dir, identities, histories, output_root, history_dir


def variant_fixture(root: Path):
    """Two synthetic frozen batches and six successful exact-graph histories."""
    # 01. The snapshot can contain many prompts, but every prepared graph
    #     must have exactly one distinct completed history entry.
    base, _, _, _, output, _ = fixture(root)
    variants_root = root / "prepared-variants"
    variants_root.mkdir()
    listing, rows = {}, []
    for version in (7, 8):
        folder = variants_root / f"v{version:04d}"
        folder.mkdir()
        batch = copy.deepcopy(base)
        batch["variant"] = version
        batch["shots"] = []
        for i in range(1, 4):
            shot_id = f"shot-{i}"
            graph = {
                "1": {"class_type": "SyntheticText",
                      "inputs": {"text": f"{shot_id}-seed-{version}"}},
                "2": {"class_type": "SyntheticSave",
                      "inputs": {"filename_prefix": f"v{version}-{shot_id}"}},
            }
            graph_bytes = canonical_bytes(graph)
            graph_name = f"{i:02d}-{shot_id}.json"
            (folder / graph_name).write_bytes(graph_bytes)
            batch["shots"].append({
                "shot_id": shot_id, "order": i, "graph_file": graph_name,
                "graph_sha256": file_sha(graph_bytes),
            })
            prompt_id = f"00000000-0000-4000-8000-{version * 100 + i:012d}"
            image_name = f"v{version}-{shot_id}.png"
            (output / image_name).write_bytes(png(14 + version * 4 + i, 9))
            listing[prompt_id] = {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "prompt": [i, prompt_id, graph, {}, ["2"]],
                "outputs": {"2": {"images": [{
                    "type": "output", "subfolder": "", "filename": image_name,
                }]}},
            }
        body = canonical_bytes(batch)
        (folder / "batch_manifest.json").write_bytes(body)
        rows.append({
            "variant": version, "relative_directory": folder.name,
            "batch_manifest_sha256": file_sha(body), "shot_count": 3,
        })
    index = {
        "schema": "picotoo.local-keyframe-variant-index.v1",
        "creative_package_sha256": base["creative_package_sha256"],
        "keyframe_kit_digest": base["keyframe_kit_digest"],
        "variant_count": 2,
        "variants": rows,
        "source_inputs_verified": False,
        "production_authorized": False,
        "gpu_post": 0,
    }
    (variants_root / "variant_index.json").write_bytes(canonical_bytes(index))
    snapshot = root / "offline-history.json"
    snapshot.write_bytes(canonical_bytes(listing))
    return variants_root, output, snapshot, index, listing


class CandidateTests(unittest.TestCase):
    def test_complete_images_match_exact_histories_without_any_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            result = collect(batch, folder, ids, histories, output)
            self.assertEqual(len(result["shots"]), 3)
            self.assertEqual(result["review_status"], "NEEDS_HUMAN_REVIEW")
            self.assertFalse(result["reference_approved"])
            self.assertFalse(result["candidate_files_staged"])
            self.assertFalse(result["source_rights_confirmed"])
            self.assertEqual(result["gpu_post"], 0)
            for item in result["shots"]:
                self.assertEqual(len(item["candidates"]), 1)
                candidate = item["candidates"][0]
                self.assertEqual((candidate["width"], candidate["height"]), (15 + item["order"], 9))
                self.assertEqual(candidate["visual_review"], "UNREVIEWED")
                self.assertFalse(candidate["pixels_decoded"])
                self.assertIsNone(item["selected_reference"])

    def test_negative_wrong_graph_status_and_shot_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = fixture(Path(tmp))
            batch, folder, ids, histories, output, _ = args
            for bad in ("graph", "status", "wrong_id", "short", "duplicate"):
                b, mapping, logs = copy.deepcopy(batch), copy.deepcopy(ids), copy.deepcopy(histories)
                target = mapping["shots"][1]["prompt_id"]
                if bad == "graph":
                    logs[target][target]["prompt"][2]["1"]["inputs"]["text"] = "modified"
                elif bad == "status":
                    logs[target][target]["status"]["completed"] = False
                elif bad == "wrong_id":
                    logs[target][target]["prompt"][1] = mapping["shots"][0]["prompt_id"]
                elif bad == "short":
                    b["shots"].pop()
                else:
                    mapping["shots"][1]["prompt_id"] = mapping["shots"][0]["prompt_id"]
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    collect(b, folder, mapping, logs, output)

    def test_image_bytes_missing_crc_and_cross_shot_reuse_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            second = output / "shot-2.png"
            original = second.read_bytes()
            for bad in ("missing", "corrupt", "reused"):
                if bad == "missing":
                    second.unlink()
                elif bad == "corrupt":
                    second.write_bytes(original[:-5] + b"broken")
                else:
                    second.write_bytes((output / "shot-1.png").read_bytes())
                with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                    collect(batch, folder, ids, histories, output)
                second.write_bytes(original)

    def test_path_escape_symlink_and_animated_png_reject(self):
        for value in ("../escape", "C:/Users/secret", "/root", "a\\b", "a//b", "a/./b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_components(value, filename=False)
        with tempfile.TemporaryDirectory() as tmp:
            batch, folder, ids, histories, output, _ = fixture(Path(tmp))
            first = ids["shots"][0]["prompt_id"]
            histories[first][first]["outputs"]["2"]["images"][0]["filename"] = "../bad.png"
            with self.assertRaises(ValueError):
                collect(batch, folder, ids, histories, output)
            histories[first][first]["outputs"]["2"]["images"][0]["filename"] = "shot-1.png"
            target = output / "shot-1.png"
            target.unlink()
            try:
                target.symlink_to(output / "shot-2.png")
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks not available on runner")
            with self.assertRaises(ValueError):
                collect(batch, folder, ids, histories, output)
        animated = png(1, 1)
        # Add APNG control chunk before IDAT with a valid CRC; still must reject.
        header = animated[:33]
        name, data = b"acTL", struct.pack(">II", 2, 0)
        chunk = struct.pack(">I", len(data)) + name + data + struct.pack(
            ">I", zlib.crc32(name + data) & 0xffffffff
        )
        with self.assertRaises(ValueError):
            png_chunks_checked(header + chunk + animated[33:])

    def test_discovery_uses_exact_graph_identity_without_manual_prompt_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch, folder, identities, histories, output, _ = fixture(root)
            listing = {key: value[key] for key, value in histories.items()}
            listing["unrelated-history"] = {"prompt": ["not-a-uuid", "untrusted", {}]}
            found, matched = discover_exact_prompt_ids(batch, folder, listing)
            self.assertEqual(found, identities)
            self.assertEqual(set(matched), set(histories))
            self.assertEqual(collect(batch, folder, found, matched, output)["gpu_post"], 0)

            # 01. Two completed prompts with an identical graph are ambiguous.
            duplicate_id = "00000000-0000-4000-8000-000000000009"
            first = identities["shots"][0]["prompt_id"]
            duplicate = copy.deepcopy(listing[first])
            duplicate["prompt"][1] = duplicate_id
            listing[duplicate_id] = duplicate
            with self.assertRaisesRegex(ValueError, "AMBIGUOUS"):
                discover_exact_prompt_ids(batch, folder, listing)
            del listing[duplicate_id]

            # 02. A failed task never substitutes for a missing completed task.
            listing[first]["status"]["status_str"] = "error"
            with self.assertRaisesRegex(ValueError, "AMBIGUOUS_OR_MISSING"):
                discover_exact_prompt_ids(batch, folder, listing)

            # 03. Modified frozen local graph disqualifies every matching history.
            listing[first]["status"]["status_str"] = "success"
            (folder / batch["shots"][0]["graph_file"]).write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "GRAPH_INVALID"):
                discover_exact_prompt_ids(batch, folder, listing)

    def test_offline_history_snapshot_discovers_and_collects_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, folder, _, histories, output, _ = fixture(root)
            listing = {key: value[key] for key, value in histories.items()}
            history_path = root / "complete-history.json"
            history_path.write_bytes(canonical_bytes(listing))
            args = ["--batch-dir", str(folder), "--history-snapshot", str(history_path),
                    "--comfy-output-root", str(output), "--output-dir", str(root / "discovered")]
            with patch("collect_local_keyframe_outputs.fetch_history") as single, patch(
                "collect_local_keyframe_outputs.fetch_recent_history"
            ) as listing_get:
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
                single.assert_not_called()
                listing_get.assert_not_called()
            report = json.loads((root / "discovered" / "candidate_manifest.json").read_bytes())
            self.assertEqual(len(report["shots"]), 3)
            self.assertFalse(report["source_rights_confirmed"])

    def test_one_offline_history_snapshot_collects_two_complete_seed_variants(self):
        # 02. One non-network command produces exactly the folder shape
        #     consumed by the existing Windows multi-seed thumbnail review.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared, comfy_output, snapshot, index, listing = variant_fixture(root)
            variants, report_index = collect_variant_snapshot(
                prepared, listing, comfy_output
            )
            self.assertEqual([folder for folder, _ in variants], ["v0007", "v0008"])
            self.assertEqual(report_index["variant_count"], 2)
            self.assertFalse(report_index["reference_approved"])
            self.assertFalse(report_index["source_rights_confirmed"])
            self.assertEqual(report_index["gpu_post"], 0)

            review_root = root / "review"
            args = [
                "--variants-root", str(prepared),
                "--history-snapshot", str(snapshot),
                "--comfy-output-root", str(comfy_output),
                "--output-dir", str(review_root),
            ]
            with patch("collect_local_keyframe_outputs.fetch_history") as single, patch(
                "collect_local_keyframe_outputs.fetch_recent_history"
            ) as scan:
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)   # Never overwrite any review file.
                single.assert_not_called()
                scan.assert_not_called()
            self.assertEqual(sorted(x.name for x in review_root.iterdir()),
                             ["observed_variant_index.json", "v0007", "v0008"])
            saved_index = json.loads(
                (review_root / "observed_variant_index.json").read_bytes()
            )
            self.assertEqual(saved_index, report_index)
            seen_images, seen_prompts = set(), set()
            for entry in saved_index["variants"]:
                path = review_root / entry["relative_directory"] / "candidate_manifest.json"
                raw = path.read_bytes()
                self.assertEqual(file_sha(raw), entry["candidate_manifest_sha256"])
                report = json.loads(raw)
                self.assertEqual(report["schema"], "picotoo.local-keyframe-output-candidates.v1")
                self.assertEqual(report["creative_package_sha256"],
                                 index["creative_package_sha256"])
                self.assertEqual([s["shot_id"] for s in report["shots"]],
                                 ["shot-1", "shot-2", "shot-3"])
                self.assertFalse(report["reference_approved"])
                self.assertFalse(report["candidate_files_staged"])
                self.assertFalse(report["source_rights_confirmed"])
                self.assertEqual(report["gpu_post"], 0)
                for shot in report["shots"]:
                    self.assertIsNone(shot["selected_reference"])
                    seen_prompts.add(shot["prompt_id"])
                    for candidate in shot["candidates"]:
                        self.assertEqual(candidate["visual_review"], "UNREVIEWED")
                        self.assertFalse(candidate["pixels_decoded"])
                        seen_images.add(candidate["sha256"])
            self.assertEqual(len(seen_prompts), 6)
            self.assertEqual(len(seen_images), 6)

    def test_offline_variant_collection_fails_closed_before_writing(self):
        # 03. Any single unsafe/missing identity blocks the whole export:
        #     no partially certified candidate review index or hidden POST.
        for bad in ("wrong_index", "noncanonical", "changed_graph",
                    "missing_history", "missing_image", "reused_image", "path_escape"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                prepared, output, snapshot, index, listing = variant_fixture(root)
                if bad == "wrong_index":
                    index["creative_package_sha256"] = "e" * 64
                    (prepared / "variant_index.json").write_bytes(canonical_bytes(index))
                elif bad == "noncanonical":
                    batch = prepared / "v0008" / "batch_manifest.json"
                    batch.write_bytes(batch.read_bytes() + b" ")
                    index["variants"][1]["batch_manifest_sha256"] = file_sha(batch.read_bytes())
                    (prepared / "variant_index.json").write_bytes(canonical_bytes(index))
                elif bad == "changed_graph":
                    (prepared / "v0008" / "03-shot-3.json").write_bytes(b"{}")
                elif bad == "missing_history":
                    listing.pop("00000000-0000-4000-8000-000000000803")
                    snapshot.write_bytes(canonical_bytes(listing))
                elif bad == "missing_image":
                    (output / "v8-shot-2.png").unlink()
                elif bad == "reused_image":
                    (output / "v8-shot-2.png").write_bytes(
                        (output / "v7-shot-1.png").read_bytes()
                    )
                else:
                    index["variants"][0]["relative_directory"] = "../v0007"
                    (prepared / "variant_index.json").write_bytes(canonical_bytes(index))
                target = root / "review"
                args = [
                    "--variants-root", str(prepared),
                    "--history-snapshot", str(snapshot),
                    "--comfy-output-root", str(output),
                    "--output-dir", str(target),
                ]
                with patch("collect_local_keyframe_outputs.fetch_history") as single, patch(
                    "collect_local_keyframe_outputs.fetch_recent_history"
                ) as scan:
                    self.assertEqual(main(args), 1)
                    single.assert_not_called()
                    scan.assert_not_called()
                self.assertFalse(target.exists())
        # 04. Multi-variant syntax never silently falls back to live Comfy.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared, output, _, _, _ = variant_fixture(root)
            with self.assertRaises(SystemExit):
                main(["--variants-root", str(prepared), "--live-history",
                      "--comfy-output-root", str(output),
                      "--output-dir", str(root / "invalid")])
            self.assertFalse((root / "invalid").exists())

    def test_live_multi_seed_scan_reuses_one_fixed_local_get_only(self):
        # 05. Both variants use exactly ONE GET through the existing
        #     loopback-only reader. No POST, history export or image staging.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            variants, output, snapshot, _, _ = variant_fixture(root)
            baseline_dir = root / "offline"
            live_dir = root / "live"
            source = [
                "--variants-root", str(variants),
                "--comfy-output-root", str(output),
            ]
            self.assertEqual(main(source + [
                "--history-snapshot", str(snapshot),
                "--output-dir", str(baseline_dir),
            ]), 0)
            with patch("collect_local_keyframe_outputs.fetch_recent_history",
                       return_value=snapshot.read_bytes()) as get, patch(
                "collect_local_keyframe_outputs.fetch_history"
            ) as by_id:
                self.assertEqual(main(source + [
                    "--live-history-scan",
                    "--output-dir", str(live_dir),
                ]), 0)
                get.assert_called_once_with()
                by_id.assert_not_called()

            # 06. A live GET is strictly an alternative evidence source;
            #     all output report bytes equal the offline snapshot mode.
            left = sorted(path.relative_to(baseline_dir)
                          for path in baseline_dir.rglob("*") if path.is_file())
            right = sorted(path.relative_to(live_dir)
                           for path in live_dir.rglob("*") if path.is_file())
            self.assertEqual(left, right)
            for relative in left:
                self.assertEqual(
                    (baseline_dir / relative).read_bytes(),
                    (live_dir / relative).read_bytes(),
                )
            self.assertEqual(len(left), 3)

    def test_live_multi_seed_scan_rejects_missing_and_invalid_records(self):
        # 07. Missing, truncated and ambiguous finished histories must not
        #     create a partial WPF review directory or use network fallback.
        for invalid in ("missing", "malformed", "ambiguous", "unreachable"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                variants, output, snapshot, _, listing = variant_fixture(root)
                if invalid == "missing":
                    listing.pop("00000000-0000-4000-8000-000000000803")
                    returned = canonical_bytes(listing)
                elif invalid == "malformed":
                    returned = b'{"incomplete":'
                elif invalid == "ambiguous":
                    original_id = "00000000-0000-4000-8000-000000000701"
                    new_id = "00000000-0000-4000-8000-000000009999"
                    record = copy.deepcopy(listing[original_id])
                    record["prompt"][1] = new_id
                    listing[new_id] = record
                    returned = canonical_bytes(listing)
                else:
                    returned = None
                target = root / "not_created"
                args = [
                    "--variants-root", str(variants),
                    "--live-history-scan",
                    "--comfy-output-root", str(output),
                    "--output-dir", str(target),
                ]
                with patch("collect_local_keyframe_outputs.fetch_history") as by_id:
                    if returned is None:
                        with patch(
                            "collect_local_keyframe_outputs.fetch_recent_history",
                            side_effect=OSError("loopback refused")
                        ) as get:
                            self.assertEqual(main(args), 1)
                    else:
                        with patch(
                            "collect_local_keyframe_outputs.fetch_recent_history",
                            return_value=returned,
                        ) as get:
                            self.assertEqual(main(args), 1)
                    get.assert_called_once_with()
                    by_id.assert_not_called()
                self.assertFalse(target.exists())

    def test_live_multi_seed_scan_requires_explicit_safe_source(self):
        # 08. Multi-seed collection must never infer a live API choice
        #     from a missing snapshot or accept per-ID/live-history modes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            variants, output, snapshot, _, _ = variant_fixture(root)
            common = [
                "--variants-root", str(variants),
                "--comfy-output-root", str(output),
                "--output-dir", str(root / "not_created"),
            ]
            for wrong in (
                [],
                ["--live-history"],
                ["--history-dir", str(root)],
                ["--embedded-png-map", str(snapshot)],
                ["--live-history-scan", "--prompt-ids", str(snapshot)],
                ["--history-snapshot", str(snapshot), "--prompt-ids", str(snapshot)],
            ):
                with self.subTest(args=wrong):
                    with patch("collect_local_keyframe_outputs.fetch_recent_history") as get:
                        with self.assertRaises(SystemExit):
                            main(common + wrong)
                        get.assert_not_called()
                    self.assertFalse((root / "not_created").exists())

    def test_live_history_scan_is_fixed_loopback_get(self):
        with patch("collect_local_keyframe_outputs.urllib.request.build_opener") as builder:
            opener = builder.return_value
            opener.open.return_value.__enter__.return_value.read.return_value = b"{}"
            self.assertEqual(fetch_recent_history(), b"{}")
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8188/history")
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(builder.call_args.args[0].proxies, {})

    def test_offline_cli_never_overwrites_or_accesses_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, batch_dir, _, _, output, history_dir = fixture(root)
            args = ["--batch-dir", str(batch_dir), "--prompt-ids", str(root / "prompt_ids.json"),
                    "--history-dir", str(history_dir), "--comfy-output-root", str(output),
                    "--output-dir", str(root / "evidence")]
            with patch("collect_local_keyframe_outputs.fetch_history") as network:
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
                network.assert_not_called()
            saved = json.loads((root / "evidence" / "candidate_manifest.json").read_bytes())
            self.assertFalse(saved["reference_approved"])


if __name__ == "__main__":
    unittest.main()
