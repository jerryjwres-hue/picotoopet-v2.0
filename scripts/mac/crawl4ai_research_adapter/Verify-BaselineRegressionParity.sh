#!/bin/bash
# 比较 feature 全量 pytest 与精确 Research baseline；只有 baseline 可真实重现的失败才允许继续。
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
baseline_sha="${BASELINE_SHA:-1c536fe4f13206a6a6ecd50728e27d8f2764112e}"
baseline_dir="${RUNNER_TEMP:-/tmp}/picotoopet-research-baseline-$baseline_sha"
evidence_dir="$repo_root/artifacts/crawl4ai-research-adapter"
baseline_xml="$evidence_dir/baseline-known-failures.xml"
feature_xml="$evidence_dir/feature-full-regression.xml"
candidate_json="$evidence_dir/baseline-reproduction-candidates.json"
reproduction_json="$evidence_dir/baseline-reproduced-flakes.json"
report_json="$evidence_dir/baseline-regression-parity.json"

mkdir -p "$evidence_dir"
rm -rf "$baseline_dir"
git worktree prune

git worktree add --detach "$baseline_dir" "$baseline_sha" >/dev/null
cleanup() {
  # 清理只发生在 CI 临时 worktree，不修改 baseline 或 feature 内容。
  git worktree remove --force "$baseline_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT

known_tests=(
  "tests/contract/test_comfyui_production_23201_contract.py::test_windows_business_page_hosts_production_without_new_shell_route"
  "tests/contract/test_controlled_promotion_23251_contract.py::test_real_wpf_smoke_is_registered_and_promotion_stays_in_advanced_business_automation"
  "tests/contract/test_paid_ai_quality_learning_23221_contract.py::test_api_and_windows_surface_are_bounded_without_provider_configuration_authority"
  "tests/contract/test_windows_product_version_surfaces.py::test_published_self_test_tracks_business_automation_navigation"
)

# 先在不可变 baseline 上重现四个确定的 Windows 导航旧契约失败。
set +e
(
  cd "$baseline_dir"
  PYTHONPATH=.:src python -m pytest -q "${known_tests[@]}" --junitxml="$baseline_xml"
)
baseline_rc=$?
set -e
if [[ "$baseline_rc" -eq 0 ]]; then
  echo "预期的 baseline 旧失败没有重现；拒绝自动豁免。" >&2
  exit 1
fi

# feature 仍执行完整 pytest。任何不属于确定旧失败的失败先视为新增回归候选。
set +e
PYTHONPATH=.:src python -m pytest -q --junitxml="$feature_xml"
feature_rc=$?
set -e

python - "$baseline_xml" "$feature_xml" "$candidate_json" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

expected_names = {
    "test_windows_business_page_hosts_production_without_new_shell_route",
    "test_real_wpf_smoke_is_registered_and_promotion_stays_in_advanced_business_automation",
    "test_api_and_windows_surface_are_bounded_without_provider_configuration_authority",
    "test_published_self_test_tracks_business_automation_navigation",
}


def failures(path: str) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    failed: list[dict[str, str]] = []
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        name = case.attrib.get("name", "")
        classname = case.attrib.get("classname", "")
        failed.append({"name": name, "classname": classname})
    return failed


baseline = failures(sys.argv[1])
baseline_names = {item["name"] for item in baseline}
if baseline_names != expected_names:
    raise SystemExit(
        "baseline known-failure set changed; refusing exemption: "
        + json.dumps(sorted(baseline_names), ensure_ascii=False)
    )

feature = failures(sys.argv[2])
candidates: list[dict[str, str]] = []
for item in feature:
    if item["name"] in expected_names:
        continue
    classname = item["classname"].strip()
    if not classname:
        raise SystemExit(f"cannot reproduce failure without classname: {item['name']}")
    # Pytest JUnit classname 使用 Python module 形式；转换回仓库 test nodeid。
    path = classname.replace(".", "/") + ".py"
    candidates.append(
        {
            "name": item["name"],
            "classname": classname,
            "nodeid": f"{path}::{item['name']}",
        }
    )

Path(sys.argv[3]).write_text(
    json.dumps(candidates, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(f"REGRESSION_REPRODUCTION_CANDIDATES={len(candidates)}")
PY

# 对每个新增候选在 immutable baseline 上独立重复最多 8 次。
# 只有 baseline 至少一次真实失败，才能证明它是既有 flaky/回归，而不是 Crawl4AI feature 新增失败。
python - "$candidate_json" "$baseline_dir" "$evidence_dir" "$reproduction_json" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

candidates = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
baseline_dir = Path(sys.argv[2])
evidence_dir = Path(sys.argv[3])
results: list[dict[str, object]] = []

environment = os.environ.copy()
environment["PYTHONPATH"] = ".:src"
for index, candidate in enumerate(candidates):
    reproduced = False
    attempts = 0
    failing_attempts = 0
    for attempt in range(1, 9):
        attempts = attempt
        junit = evidence_dir / f"baseline-repro-{index}-{attempt}.xml"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                candidate["nodeid"],
                f"--junitxml={junit}",
            ],
            cwd=baseline_dir,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            reproduced = True
            failing_attempts += 1
            break
    results.append(
        {
            **candidate,
            "attempts": attempts,
            "failing_attempts": failing_attempts,
            "reproduced_on_baseline": reproduced,
        }
    )

Path(sys.argv[4]).write_text(
    json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

python - \
  "$baseline_xml" \
  "$feature_xml" \
  "$reproduction_json" \
  "$report_json" \
  "$baseline_sha" \
  "$feature_rc" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def failed_names(path: str) -> set[str]:
    root = ET.parse(path).getroot()
    return {
        case.attrib.get("name", "")
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    }


known_baseline = failed_names(sys.argv[1])
feature_failures = failed_names(sys.argv[2])
reproductions = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
reproduced_names = {
    str(item["name"])
    for item in reproductions
    if item.get("reproduced_on_baseline") is True
}
unreproduced = {
    str(item["name"])
    for item in reproductions
    if item.get("reproduced_on_baseline") is not True
}
allowed = known_baseline | reproduced_names
new_failures = feature_failures - allowed
if unreproduced or new_failures:
    raise SystemExit(
        "feature introduced failures not reproducible on immutable baseline: "
        + json.dumps(sorted(unreproduced | new_failures), ensure_ascii=False)
    )

report = {
    "schema_version": "1.1",
    "baseline_sha": sys.argv[5],
    "baseline_known_failures": sorted(known_baseline),
    "baseline_reproduced_flaky_failures": sorted(reproduced_names),
    "feature_failures": sorted(feature_failures),
    "new_failures": sorted(new_failures),
    "feature_pytest_exit_code": int(sys.argv[6]),
    "status": "pass",
    "policy": (
        "feature failures are allowed only when the exact failure is reproduced "
        "on the immutable baseline; unexpected failures get up to 8 isolated baseline attempts"
    ),
}
Path(sys.argv[4]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print("BASELINE_REGRESSION_PARITY=PASS")
print(f"BASELINE_KNOWN_FAILURES={len(known_baseline)}")
print(f"BASELINE_REPRODUCED_FLAKES={len(reproduced_names)}")
print(f"FEATURE_FAILURES={len(feature_failures)}")
print("NEW_FAILURES=0")
PY
