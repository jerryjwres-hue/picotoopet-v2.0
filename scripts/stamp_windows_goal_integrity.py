from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACT = (
    _REPO_ROOT / "contracts" / "release" / "project-goal-invariants.json"
)
_GOAL_GATE_MARKER = "# PICOTOO_GOAL_INTEGRITY_GATE_V1"
_FORMAL_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
)
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")


class GoalStampError(RuntimeError):
    """The formal native release could not be stamped safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoalStampError(f"无法读取 JSON：{path}") from error
    if not isinstance(value, dict):
        raise GoalStampError(f"JSON 顶层必须是对象：{path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _single_package(output_root: Path) -> Path:
    packages = sorted(
        output_root.glob("PicotooPet-Phase2-Windows-Prebuilt-*.zip")
    )
    if len(packages) != 1:
        raise GoalStampError(
            f"必须恰好存在一个原生 WPF ZIP，实际为 {len(packages)}。"
        )
    return packages[0]


def _single_root(names: list[str]) -> str:
    roots = {name.split("/", 1)[0] for name in names if name}
    if len(roots) != 1:
        raise GoalStampError("发布 ZIP 必须只有一个顶层目录。")
    return next(iter(roots))


def _ps_string(value: str) -> str:
    return '"' + value.replace("`", "``").replace('"', '`"') + '"'


def _required_provenance_fields(windows_contract: dict[str, Any]) -> list[str]:
    fields = windows_contract.get("required_native_ci_provenance_fields")
    if not isinstance(fields, list) or not all(
        isinstance(value, str) and value for value in fields
    ):
        raise GoalStampError(
            "目标合同缺少 required_native_ci_provenance_fields。"
        )
    return fields


def _allowed_workflow_paths(windows_contract: dict[str, Any]) -> list[str]:
    paths = windows_contract.get("allowed_native_ci_workflow_paths")
    if not isinstance(paths, list) or not all(
        isinstance(value, str) and value.startswith(".github/workflows/")
        for value in paths
    ):
        raise GoalStampError(
            "目标合同缺少 allowed_native_ci_workflow_paths。"
        )
    return paths


def _validate_manifest_provenance(
    manifest: dict[str, Any],
    provenance_fields: list[str],
    *,
    repository: str,
    allowed_workflow_paths: list[str],
) -> None:
    values: dict[str, str] = {}
    for field in provenance_fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GoalStampError(f"可安装包缺少原生 CI 溯源字段：{field}")
        values[field] = value.strip()

    for field in ("github_run_id", "github_run_attempt"):
        if not _POSITIVE_INTEGER_PATTERN.fullmatch(values.get(field, "")):
            raise GoalStampError(f"原生 CI 溯源字段必须为正整数：{field}")

    workflow_ref = values.get("github_workflow_ref", "")
    allowed_prefixes = tuple(
        f"{repository}/{workflow_path}@".lower()
        for workflow_path in allowed_workflow_paths
    )
    if not workflow_ref.lower().startswith(allowed_prefixes):
        raise GoalStampError(
            "github_workflow_ref 不属于批准的 Windows 原生 CI 工作流。"
        )

    for field in ("source_head", "build_commit"):
        if not _GIT_SHA_PATTERN.fullmatch(values.get(field, "")):
            raise GoalStampError(f"原生 CI 溯源字段必须为 40 位 Git SHA：{field}")


def _goal_gate_block(
    required_values: dict[str, Any],
    windows_contract: dict[str, Any],
    *,
    newline: str,
) -> str:
    string_names = (
        "release_type",
        "target",
        "delivery_surface",
        "ui_framework",
        "entry_executable",
        "integration_target",
        "github_repository",
    )
    boolean_values: dict[str, bool] = {
        "source_build_on_user_pc": False,
        "browser_ui": False,
        "local_http_ui": False,
        "native_ci_verified": True,
        "user_install_allowed": True,
    }

    string_lines: list[str] = []
    for name in string_names:
        value = required_values.get(name)
        if not isinstance(value, str) or not value:
            raise GoalStampError(f"目标合同缺少字符串字段：{name}")
        string_lines.append(f"        {_ps_string(name)} = {_ps_string(value)}")

    repository = required_values.get("github_repository")
    if not isinstance(repository, str) or not repository:
        raise GoalStampError("目标合同缺少 github_repository。")

    for name in ("source_build_on_user_pc", "browser_ui", "local_http_ui"):
        value = required_values.get(name)
        if not isinstance(value, bool):
            raise GoalStampError(f"目标合同缺少布尔字段：{name}")
        boolean_values[name] = value

    boolean_lines = [
        f"        {_ps_string(name)} = ${str(value).lower()}"
        for name, value in boolean_values.items()
    ]
    provenance_fields = _required_provenance_fields(windows_contract)
    provenance_lines = ", ".join(
        _ps_string(field) for field in provenance_fields
    )
    allowed_workflows = _allowed_workflow_paths(windows_contract)
    allowed_workflow_prefixes = ", ".join(
        _ps_string(f"{repository}/{workflow_path}@")
        for workflow_path in allowed_workflows
    )

    required_paths = windows_contract.get("required_archive_paths")
    if not isinstance(required_paths, list) or not required_paths:
        raise GoalStampError("目标合同缺少 required_archive_paths。")
    payload_paths = [
        path.removeprefix("payload/")
        for path in required_paths
        if isinstance(path, str) and path.startswith("payload/")
    ]
    for required in (
        "Picotoo Pet AI.exe",
        "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe",
    ):
        if required not in payload_paths:
            payload_paths.append(required)

    forbidden_suffixes = windows_contract.get("forbidden_suffixes")
    if not isinstance(forbidden_suffixes, list):
        raise GoalStampError("目标合同缺少 forbidden_suffixes。")
    forbidden_fragments = windows_contract.get("forbidden_name_fragments")
    if not isinstance(forbidden_fragments, list):
        raise GoalStampError("目标合同缺少 forbidden_name_fragments。")

    required_path_lines = ", ".join(
        _ps_string(path.lower()) for path in payload_paths
    )
    suffix_lines = ", ".join(
        _ps_string(str(value).lower()) for value in forbidden_suffixes
    )
    fragment_lines = ", ".join(
        _ps_string(str(value).lower()) for value in forbidden_fragments
    )

    lines = [
        f"    {_GOAL_GATE_MARKER}",
        "    $goalRequiredStrings = [ordered]@{",
        *string_lines,
        "    }",
        "    foreach ($goalName in $goalRequiredStrings.Keys) {",
        "        $goalProperty = $manifest.PSObject.Properties[$goalName]",
        "        if ($null -eq $goalProperty -or",
        "            [string]$goalProperty.Value -ne [string]$goalRequiredStrings[$goalName]) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: manifest field $goalName does not match the approved native WPF goal.\"",
        "        }",
        "    }",
        "    $goalRequiredBooleans = [ordered]@{",
        *boolean_lines,
        "    }",
        "    foreach ($goalName in $goalRequiredBooleans.Keys) {",
        "        $goalProperty = $manifest.PSObject.Properties[$goalName]",
        "        if ($null -eq $goalProperty -or",
        "            [bool]$goalProperty.Value -ne [bool]$goalRequiredBooleans[$goalName]) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: manifest boolean $goalName does not match the approved native WPF goal.\"",
        "        }",
        "    }",
        f"    $goalRequiredProvenance = @({provenance_lines})",
        "    foreach ($goalName in $goalRequiredProvenance) {",
        "        $goalProperty = $manifest.PSObject.Properties[$goalName]",
        "        if ($null -eq $goalProperty -or",
        "            [string]::IsNullOrWhiteSpace([string]$goalProperty.Value)) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: native CI provenance is missing: $goalName\"",
        "        }",
        "    }",
        "    if ([string]$manifest.github_run_id -notmatch '^[1-9][0-9]*$' -or",
        "        [string]$manifest.github_run_attempt -notmatch '^[1-9][0-9]*$') {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: native CI run provenance is invalid.\"",
        "    }",
        "    if ([string]$manifest.github_workflow_ref -notmatch '\\.github/workflows/.+@.+$') {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: github_workflow_ref is invalid.\"",
        "    }",
        f"    $goalAllowedWorkflowPrefixes = @({allowed_workflow_prefixes})",
        "    $goalWorkflowAllowed = $false",
        "    foreach ($goalWorkflowPrefix in $goalAllowedWorkflowPrefixes) {",
        "        if ([string]$manifest.github_workflow_ref -and",
        "            ([string]$manifest.github_workflow_ref).StartsWith(",
        "                $goalWorkflowPrefix,",
        "                [System.StringComparison]::OrdinalIgnoreCase)) {",
        "            $goalWorkflowAllowed = $true",
        "            break",
        "        }",
        "    }",
        "    if (-not $goalWorkflowAllowed) {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: github_workflow_ref is not an approved Windows native workflow.\"",
        "    }",
        "    if ([string]$manifest.source_head -notmatch '^[0-9a-fA-F]{40}$' -or",
        "        [string]$manifest.build_commit -notmatch '^[0-9a-fA-F]{40}$') {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: source commit provenance is invalid.\"",
        "    }",
        "    if (-not ($manifest.PSObject.Properties.Name -contains \"files\") -or",
        "        $null -eq $manifest.files) {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: manifest files are missing.\"",
        "    }",
        "    $goalPayloadPaths = @($manifest.files | ForEach-Object {",
        "        ([string]$_.path).Replace([System.IO.Path]::DirectorySeparatorChar, [char]'/').Replace([System.IO.Path]::AltDirectorySeparatorChar, [char]'/').ToLowerInvariant()",
        "    })",
        f"    foreach ($goalRequiredPath in @({required_path_lines})) {{",
        "        if (-not ($goalPayloadPaths -contains $goalRequiredPath)) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: required native WPF payload is missing: $goalRequiredPath\"",
        "        }",
        "    }",
        f"    $goalForbiddenSuffixes = @({suffix_lines})",
        f"    $goalForbiddenFragments = @({fragment_lines})",
        "    foreach ($goalPath in $goalPayloadPaths) {",
        "        foreach ($goalSuffix in $goalForbiddenSuffixes) {",
        "            if ($goalPath.EndsWith($goalSuffix, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "                throw \"GOAL_INTEGRITY_VIOLATION: forbidden web UI payload: $goalPath\"",
        "            }",
        "        }",
        "        foreach ($goalFragment in $goalForbiddenFragments) {",
        "            if ($goalPath.Contains($goalFragment)) {",
        "                throw \"GOAL_INTEGRITY_VIOLATION: forbidden substitute payload: $goalPath\"",
        "            }",
        "        }",
        "    }",
    ]
    return newline.join(lines)


def _inject_goal_gate(
    script_data: bytes,
    *,
    required_values: dict[str, Any],
    windows_contract: dict[str, Any],
    script_name: str,
) -> bytes:
    try:
        script = script_data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise GoalStampError(f"正式脚本不是有效 UTF-8：{script_name}") from error
    if _GOAL_GATE_MARKER in script:
        return script_data

    anchor = "    $manifest = Read-JsonUtf8 -Path $manifestPath"
    if script.count(anchor) != 1:
        raise GoalStampError(
            f"无法在 {script_name} 中唯一定位 manifest 读取边界。"
        )
    newline = "\r\n" if "\r\n" in script else "\n"
    gate = _goal_gate_block(
        required_values,
        windows_contract,
        newline=newline,
    )
    patched = script.replace(anchor, anchor + newline + gate, 1)
    return patched.encode("utf-8-sig")


def _rewrite_manifest(
    package: Path,
    required_values: dict[str, Any],
    windows_contract: dict[str, Any],
) -> dict[str, Any]:
    with zipfile.ZipFile(package, "r") as source:
        infos = source.infolist()
        root = _single_root([info.filename for info in infos])
        manifest_name = f"{root}/release-manifest.json"
        try:
            manifest = json.loads(source.read(manifest_name).decode("utf-8-sig"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoalStampError(
                "发布 ZIP 缺少有效 release-manifest.json。"
            ) from error
        if not isinstance(manifest, dict):
            raise GoalStampError("release-manifest.json 顶层必须是对象。")
        if manifest.get("release_type") != "prebuilt":
            raise GoalStampError("只允许给现有原生 prebuilt WPF 包加盖目标合同。")
        if manifest.get("target") != "win-x64":
            raise GoalStampError("只允许给 win-x64 原生包加盖目标合同。")

        manifest.update(required_values)
        native_verified = manifest.get("native_ci_verified") is True
        manifest["user_install_allowed"] = native_verified
        provenance_fields = _required_provenance_fields(windows_contract)
        allowed_workflows = _allowed_workflow_paths(windows_contract)
        repository = required_values.get("github_repository")
        if not isinstance(repository, str) or not repository:
            raise GoalStampError("目标合同缺少 github_repository。")
        if native_verified:
            _validate_manifest_provenance(
                manifest,
                provenance_fields,
                repository=repository,
                allowed_workflow_paths=allowed_workflows,
            )
        manifest_data = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

        replacements: dict[str, bytes] = {manifest_name: manifest_data}
        archive_names = {info.filename for info in infos}
        for script_name in _FORMAL_SCRIPTS:
            archive_name = f"{root}/{script_name}"
            if archive_name not in archive_names:
                raise GoalStampError(
                    f"发布 ZIP 缺少正式脚本：{script_name}"
                )
            replacements[archive_name] = _inject_goal_gate(
                source.read(archive_name),
                required_values=required_values,
                windows_contract=windows_contract,
                script_name=script_name,
            )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{package.name}.",
            suffix=".tmp",
            dir=package.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w") as destination:
                for info in infos:
                    data = replacements.get(info.filename)
                    if data is None:
                        data = source.read(info.filename)
                    destination.writestr(info, data)
            os.replace(temporary, package)
        finally:
            temporary.unlink(missing_ok=True)
    return manifest


def stamp_windows_release(
    output_root: Path | str,
    *,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    output = Path(output_root).resolve()
    if not output.is_dir():
        raise GoalStampError(f"发布输出目录不存在：{output}")

    contract = _load_json(Path(contract_path))
    windows = contract.get("windows")
    if not isinstance(windows, dict):
        raise GoalStampError("目标合同缺少 windows 对象。")
    required = windows.get("required_manifest_values")
    if not isinstance(required, dict):
        raise GoalStampError("目标合同缺少 required_manifest_values。")
    provenance_fields = _required_provenance_fields(windows)
    _allowed_workflow_paths(windows)

    package = _single_package(output)
    manifest = _rewrite_manifest(package, required, windows)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    checksum = package.with_name(package.name + ".sha256.txt")
    checksum.write_text(f"{digest}  {package.name}\n", encoding="utf-8")

    build_report_path = output / "windows-build-report.json"
    build_report = _load_json(build_report_path)
    build_report.update(required)
    build_report["native_ci_verified"] = (
        manifest.get("native_ci_verified") is True
    )
    build_report["user_install_allowed"] = (
        manifest.get("user_install_allowed") is True
    )
    for field in provenance_fields:
        build_report[field] = manifest.get(field)
    build_report["installer_goal_gate"] = "pass"
    build_report["package"] = str(package)
    build_report["package_sha256"] = digest
    _write_json(build_report_path, build_report)

    report: dict[str, object] = {
        "schema_version": "1.0",
        "policy_id": contract.get("policy_id"),
        "status": "pass",
        "package": str(package),
        "package_sha256": digest,
        "delivery_surface": manifest["delivery_surface"],
        "ui_framework": manifest["ui_framework"],
        "entry_executable": manifest["entry_executable"],
        "integration_target": manifest["integration_target"],
        "native_ci_verified": manifest.get("native_ci_verified"),
        "user_install_allowed": manifest.get("user_install_allowed"),
        "github_repository": manifest.get("github_repository"),
        "github_run_id": manifest.get("github_run_id"),
        "github_run_attempt": manifest.get("github_run_attempt"),
        "github_workflow_ref": manifest.get("github_workflow_ref"),
        "source_head": manifest.get("source_head"),
        "build_commit": manifest.get("build_commit"),
        "installer_goal_gate": "pass",
    }
    _write_json(output / "goal-integrity-stamp-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=_DEFAULT_CONTRACT)
    args = parser.parse_args()
    try:
        report = stamp_windows_release(
            args.output_root,
            contract_path=args.contract,
        )
    except GoalStampError as error:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "error_code": "GOAL_INTEGRITY_VIOLATION",
                    "error": str(error),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
