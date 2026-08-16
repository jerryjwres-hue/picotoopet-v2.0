#!/bin/bash
# 比较 feature 全量 pytest 与精确 Research baseline 的已知失败集；任何新增失败仍然阻断 CI。
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
baseline_sha="${BASELINE_SHA:-1c536fe4f13206a6a6ecd50728e27d8f2764112e}"
baseline_dir="${RUNNER_TEMP:-/tmp}/picotoopet-research-baseline-$baseline_sha"
evidence_dir="$repo_root/artifacts/crawl4ai-research-adapter"
baseline_xml="$evidence_dir/baseline-known-failures.xml"
feature_xml="$evidence_dir/feature-full-regression.xml"
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

# 先在不可变 baseline 上重现四个 Windows 导航旧契约失败；不能凭 feature 的失败结果自行放宽门禁。
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

# feature 仍执行完整 pytest。pytest 非零不会被忽略；随后只允许 baseline 已真实重现的同四项失败。
set +e
PYTHONPATH=.:src python -m pytest -q --junitxml="$feature_xml"
feature_rc=$?
set -e

python - "$baseline_xml" "$feature_xml" "$report_json" "$baseline_sha" "$feature_rc" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

expected = {
    "test_windows_business_page_hosts_production_without_new_shell_route",
    "test_real_wpf_smoke_is_registered_and_promotion_stays_in_advanced_business_automation",
    "test_api_and_windows_surface_are_bounded_without_provider_configuration_authority",
    "test_published_self_test_tracks_business_automation_navigation",
}


def failed_names(path: str) -> set[str]:
    root = ET.parse(path).getroot()
    return {
        case.attrib.get("name", "")
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    }


baseline_failures = failed_names(sys.argv[1])
feature_failures = failed_names(sys.argv[2])
if baseline_failures != expected:
    raise SystemExit(
        "baseline failure set changed; refusing exemption: "
        + json.dumps(sorted(baseline_failures), ensure_ascii=False)
    )
new_failures = feature_failures - baseline_failures
if new_failures:
    raise SystemExit(
        "feature introduced new full-regression failures: "
        + json.dumps(sorted(new_failures), ensure_ascii=False)
    )

report = {
    "schema_version": "1.0",
    "baseline_sha": sys.argv[4],
    "baseline_failures": sorted(baseline_failures),
    "feature_failures": sorted(feature_failures),
    "new_failures": sorted(new_failures),
    "feature_pytest_exit_code": int(sys.argv[5]),
    "status": "pass",
    "policy": "feature failures must be a subset of failures reproduced at immutable baseline",
}
Path(sys.argv[3]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print("BASELINE_REGRESSION_PARITY=PASS")
print(f"BASELINE_FAILURES={len(baseline_failures)}")
print(f"FEATURE_FAILURES={len(feature_failures)}")
print("NEW_FAILURES=0")
PY
