#!/usr/bin/env python3
"""Synchronize non-workflow cloud-contract milestone files, then delete this script."""

from pathlib import Path

OLD_VERSION = "2.3.8.1"
NEW_VERSION = "2.3.9.1"

VERSION_PATHS = (
    "contracts/release/project-goal-invariants.json",
    "tests/contract/test_phase23_mac_delta_source.py",
    "tests/contract/test_product_version_goal_integrity.py",
    "tests/contract/test_project_goal_integrity.py",
    "tests/contract/test_results_center_2371_contract.py",
    "tests/contract/test_windows_executable_allowlist.py",
    "tests/contract/test_windows_goal_integrity_stamper.py",
    "tests/contract/test_windows_product_version_surfaces.py",
    "tests/integration/api/test_product_version_api.py",
    "tests/release/test_windows_goal_integrity_release_contract.py",
    "tests/test_package_baseline.py",
    "tests/unit/test_product_version.py",
    "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs",
    "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ResultsCenterSmokeTests.cs",
    "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ResultsPageWpfLayoutSmokeTests.cs",
)

for name in VERSION_PATHS:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    if OLD_VERSION not in text:
        raise SystemExit(f"missing expected {OLD_VERSION} reference in {name}")
    path.write_text(text.replace(OLD_VERSION, NEW_VERSION), encoding="utf-8")

parser_test = Path("tests/unit/test_product_version.py")
text = parser_test.read_text(encoding="utf-8")
if '"2.3.8"' not in text:
    raise SystemExit("missing invalid three-part version fixture")
parser_test.write_text(text.replace('"2.3.8"', '"2.3.9"'), encoding="utf-8")

release_replacements = {
    "tests/contract/test_phase23_windows_source.py": (
        (
            "PicotooPet-Phase23-Approval-Windows-Prebuilt",
            "PicotooPet-Phase23-CloudContract-Windows-Prebuilt",
        ),
    ),
    "tests/release/test_windows_prebuilt_delivery.py": (
        ("2.3.0-slice-d-approval", "2.3.0-slice-d-cloud-contract"),
        (
            "PicotooPet-Phase23-Approval-Windows-Prebuilt",
            "PicotooPet-Phase23-CloudContract-Windows-Prebuilt",
        ),
    ),
}
for name, replacements in release_replacements.items():
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"missing release label {old!r} in {name}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")

navigation = Path(
    "windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/NavigationSmokeTests.cs"
)
text = navigation.read_text(encoding="utf-8")
for old, new in (
    (
        "            !shell.NavigationItems\n",
        "            shell.NavigationItems\n",
    ),
    (
        '            "未实现云端开发不得可操作");',
        '            "冻结合同状态页必须可打开");',
    ),
):
    if text.count(old) != 1:
        raise SystemExit(f"CloudDevelopment navigation replacement count mismatch: {old!r}")
    text = text.replace(old, new, 1)

start_marker = "        shell.Navigate(NavigationRoute.CloudDevelopment);\n"
end_marker = "\n        shell.ShowNavigationFailure(NavigationRoute.TaskCenter);"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("CloudDevelopment page assertion block markers not found")
new_block = '''        shell.Navigate(NavigationRoute.CloudDevelopment);
        var page = shell.CurrentPage as CloudDevelopmentPageViewModel;
        SmokeAssert.True(page is not null, "云端开发必须显示冻结合同状态页");
        SmokeAssert.True(page!.Title == "云端开发", "云端开发标题被改写");
        SmokeAssert.True(page.ContractVersion == "1.0.0", "云端开发合同版本错误");
        SmokeAssert.True(!page.ProviderConfigured, "云端开发不得伪造 Provider 已配置");
'''
navigation.write_text(text[:start] + new_block + text[end:], encoding="utf-8")

suppressions = Path("windows/desktop/src/PicotooPet.Desktop/GlobalSuppressions.cs")
text = suppressions.read_text(encoding="utf-8")
for property_name in (
    "ContractVersion",
    "ContractStatus",
    "ProviderConfigured",
    "ProviderStatus",
    "CurrentDelivery",
    "TrustChain",
    "SecurityBoundaries",
    "PhaseMilestones",
):
    target = (
        "~P:PicotooPet.Desktop.ViewModels."
        f"CloudDevelopmentPageViewModel.{property_name}"
    )
    if target in text:
        continue
    text += (
        "\n[assembly: SuppressMessage(\n"
        "    \"Performance\",\n"
        "    \"CA1822:Mark members as static\",\n"
        "    Justification = \"WPF binds this read-only contract property through the page DataContext instance.\",\n"
        "    Scope = \"member\",\n"
        f"    Target = \"{target}\")]\n"
    )
suppressions.write_text(text, encoding="utf-8")

allowed_old_version = {
    "src/picotoopet_core/product-version.txt",
    "docs/superpowers/plans/2026-08-05-cloud-development-contract-status-page.md",
    ".github/workflows/one-shot-version-2391-cloud-contract.yml",
    ".github/workflows/one-shot-audit-version-2381.yml",
    "scripts/one_shot_migrate_2391_cloud_contract.py",
    ".github/workflows/one-shot-version-2391-cloud-contract-v2.yml",
}
allowed_old_label = {
    ".github/workflows/windows-phase2-release.yml",
    ".github/workflows/one-shot-version-2391-cloud-contract.yml",
    ".github/workflows/one-shot-audit-version-2381.yml",
    "scripts/one_shot_migrate_2391_cloud_contract.py",
}
for path in Path(".").rglob("*"):
    if not path.is_file() or ".git" in path.parts:
        continue
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    relative = path.as_posix()
    if OLD_VERSION in content and relative not in allowed_old_version:
        raise SystemExit(f"unexpected remaining {OLD_VERSION} in {relative}")
    if (
        "slice-d-approval" in content or "Phase23-Approval" in content
    ) and relative not in allowed_old_label:
        raise SystemExit(f"unexpected old release label in {relative}")
