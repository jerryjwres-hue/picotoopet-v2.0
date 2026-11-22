"""Generate an exact Python-to-Windows-WPF Qwen readiness contract fixture.

This is synthetic CPU-only CI data, not actual user image evidence, rights,
owner approval, an executable Comfy graph or GPU authorization.
"""
from __future__ import annotations

import argparse
import copy
import tempfile
from pathlib import Path

from test_qwen_reference_readiness import observed_fixture
from qwen_reference_readiness import inspect_readiness
from recover_comfy_keyframe_workflow import canonical_bytes

PACKAGE_SHA256 = "c" * 64


def export(output_dir: Path) -> None:
    # 01. Only a fresh, caller-owned CI directory can receive these two JSONs.
    #     Synthetic source images live in an automatically removed temp folder.
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise ValueError("QWEN_WPF_FIXTURE_OUTPUT_NOT_FRESH")
    with tempfile.TemporaryDirectory(prefix="picotoo-qwen-wpf-cpu-") as folder:
        root = Path(folder)
        graph, recovery, package = observed_fixture(root)
        report = inspect_readiness(
            graph, recovery, package, PACKAGE_SHA256, root,
            composition_node="1", fixed_nodes=("2", "3"),
        )
        if (report["status"] != "BLOCKED_MISSING_REFERENCES"
            or [item["composition_status"]
                for item in report["composition_work_order"]["items"]]
            != ["OBSERVED_UNAPPROVED", "NEEDS_DISTINCT_COMPOSITION",
                "NEEDS_DISTINCT_COMPOSITION"]
            or report["production_authorized"] is not False
            or report["gpu_post"] != 0
            or report["source_rights_confirmed"] is not False):
            raise ValueError("QWEN_WPF_FIXTURE_CONTRACT_UNEXPECTED")

        # 02. Adapt only the synthetic Core transport envelope required by
        #     the existing native WPF candidate constructor. Preserve the
        #     actual frozen kit, exact prompts, digest, shot IDs and report.
        manifest = copy.deepcopy(package)
        manifest["creative_job_id"] = "job-1"
        manifest["source_set_digest"] = "d" * 64
        manifest["stage_results"]["script.v1"] = {}
        if (manifest["stage_results"]["keyframe_kit.v1"]["kit_digest"]
            != report["creative_kit_digest"]):
            raise ValueError("QWEN_WPF_FIXTURE_KIT_IDENTITY_CHANGED")

        output_dir.mkdir()
        with (output_dir / "python_qwen_readiness.json").open("xb") as out:
            out.write(canonical_bytes(report))
        with (output_dir / "python_creative_manifest.json").open("xb") as out:
            out.write(canonical_bytes(manifest))
    print("QWEN_WPF_EXACT_PYTHON_FIXTURE=PASS; SHOTS=3; GPU_POST=0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    export(args.output_dir)


if __name__ == "__main__":
    main()
