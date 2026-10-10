"""Portable tests of the C010B PREPARATION registry and mutation tooling only.

These portable tests verify the matrix/staging tools only. The separate Windows C010B IntegrationTests project now calls the real C010A API.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PreparationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((HERE / "coverage_scenarios.json").read_text(encoding="utf-8"))
        cls.cases = cls.spec["scenarios"]

    def test_matrix_identifiers_are_unique(self):
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 60)

    def test_all_blocked_cases_name_dependency(self):
        allowed = {"FIXTURE_ORACLE_READY", "COVERED_BY_PASS_NATIVE_WINDOWS_SUITE",
                   "STAGING_READY_REAL_MASTER_BLOCKED", "BLOCKED_GOAL_CENTER_OPEN_API",
                   "BLOCKED_C010B_ALL_PROFILES_REAL_WINDOWS"}
        for case in self.cases:
            self.assertIn(case["status"], allowed)
            if "BLOCKED" in case["status"]:
                self.assertTrue(case["dependency"], case["id"])

    def test_media_fixture_index_matches_generator_contract(self):
        media = [case for case in self.cases if case["status"] == "FIXTURE_ORACLE_READY"]
        self.assertEqual(len(media), 20)
        self.assertEqual(sum(case["expected_outcome"] == "PASS" for case in media), 6)
        self.assertEqual(len({case["id"] for case in media}), 20)

    def test_master_stager_uses_actual_digest_name_and_does_not_edit_original(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            digest = "a" * 64
            original = home / "upstream" / "job-1234abcd" / digest
            original.mkdir(parents=True)
            (original / "master.mp4").write_bytes(b"mock-bytes-not-real-C009A-output")
            known = {"schema_version": "1.0", "master_input_digest": digest,
                     "production_job_id": "pjob", "production_package_digest": "a" * 64,
                     "production_plan_digest": "a" * 64, "creative_package_digest": "a" * 64,
                     "c004_source_sha256": "a" * 64, "caption_overlay_plan_digest": "a" * 64,
                     "narration_plan_digest": "a" * 64, "selected_visual_sha256": "a" * 64,
                     "output_sha256": "a" * 64, "output_bytes": 30,
                     "has_audio": True, "narration_manifest_sha256": "a" * 64,
                     "c008b_manifest_sha256": "a" * 64}
            manifest = original / "master-manifest.json"
            manifest.write_text(json.dumps(known), encoding="utf-8")
            original_text = manifest.read_text(encoding="utf-8")
            stage = home / "staged"
            command = [sys.executable, str(HERE / "stage_master_manifest_mutations.py"),
                       "--artifact-dir", str(original), "--output", str(stage)]
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(original_text, manifest.read_text(encoding="utf-8"))
            mutated = json.loads((stage / "production-plan-mismatch" / "job-1234abcd" / digest /
                                  "master-manifest.json").read_text(encoding="utf-8"))
            self.assertNotEqual(mutated["production_plan_digest"], known["production_plan_digest"])
            self.assertEqual(json.loads((stage / "mutation-index.json").read_text(encoding="utf-8"))["schema"],
                             "c009a-negative-staging.v1")
            rejected = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(rejected.returncode, 0)

    def test_no_pretend_product_qa_success(self):
        self.assertIn("Fixture oracle PASS != product C010A PASS", self.spec["important"])
        e2e = [case for case in self.cases if case["area"] in {"receipt-restart", "candidate-selection"}]
        self.assertTrue(e2e)
        self.assertEqual(len(e2e), 23)
        self.assertEqual(sum(case["status"] == "COVERED_BY_PASS_NATIVE_WINDOWS_SUITE" for case in e2e), 22)
        self.assertEqual(sum(case["status"] == "BLOCKED_GOAL_CENTER_OPEN_API" for case in e2e), 1)
        self.assertEqual(self.spec["integration"]["workflow_run"], 38021044347)
        self.assertEqual(self.spec["integration"]["workflow_conclusion"], "success")


if __name__ == "__main__":
    unittest.main()
