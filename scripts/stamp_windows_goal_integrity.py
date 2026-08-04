from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class GoalStampError(ValueError):
    """The native package cannot be safely promoted to user-installable status."""


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACT = _REPO_ROOT / "contracts" / "release" / "project-goal-invariants.json"
_GOAL_GATE_MARKER = "# PICOTOO_GOAL_INTEGRITY_GATE_V1"
_FORMAL_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
    "Rollback-Phase2Prebuilt.ps1",
)
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")


def _fail(message: str) -> GoalStampError:
    return GoalStampError(f"GOAL_STAMP_REJECTED: {message}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _fail(f"无法读取 JSON：{path}") from error
    if not isinstance(payload, dict):
        raise _fail(f"JSON 顶层必须是对象：{path}")
    return payload


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _validated_nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"缺少 {field}。")
    return value.strip()


def _workflow_path(repository: str, workflow_ref: str) -> str:
    prefix = f"{repository}/"
    if not workflow_ref.lower().startswith(prefix.lower()) or "@" not in workflow_ref:
        raise _fail("GITHUB_WORKFLOW_REF 与批准仓库不一致。")
    path, _, _ = workflow_ref[len(prefix) :].partition("@")
    if not path:
        raise _fail("GITHUB_WORKFLOW_REF 缺少 workflow 路径。")
    return path


def _provenance(
    *,
    source_head: str,
    source_ref: str,
    repository: str,
    allowed_workflow_paths: list[str],
) -> dict[str, str]:
    if os.environ.get("CI", "").lower() != "true":
        raise _fail("只允许在 CI=true 的原生 Windows 流程盖章。")
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        raise _fail("只允许在 GITHUB_ACTIONS=true 的流程盖章。")
    if os.environ.get("RUNNER_OS", "").lower() != "windows":
        raise _fail("只允许原生 Windows Runner 盖章。")
    actual_repository = _validated_nonempty(
        os.environ.get("GITHUB_REPOSITORY"), "GITHUB_REPOSITORY"
    )
    if actual_repository.lower() != repository.lower():
        raise _fail("GITHUB_REPOSITORY 与目标合同不一致。")

    run_id = _validated_nonempty(os.environ.get("GITHUB_RUN_ID"), "GITHUB_RUN_ID")
    run_attempt = _validated_nonempty(
        os.environ.get("GITHUB_RUN_ATTEMPT"), "GITHUB_RUN_ATTEMPT"
    )
    workflow_ref = _validated_nonempty(
        os.environ.get("GITHUB_WORKFLOW_REF"), "GITHUB_WORKFLOW_REF"
    )
    build_commit = _validated_nonempty(os.environ.get("GITHUB_SHA"), "GITHUB_SHA")
    if not _POSITIVE_INTEGER_PATTERN.fullmatch(run_id):
        raise _fail("GITHUB_RUN_ID 必须为正整数。")
    if not _POSITIVE_INTEGER_PATTERN.fullmatch(run_attempt):
        raise _fail("GITHUB_RUN_ATTEMPT 必须为正整数。")
    if not _GIT_SHA_PATTERN.fullmatch(source_head):
        raise _fail("source_head 必须为 40 位 Git SHA。")
    if not _GIT_SHA_PATTERN.fullmatch(build_commit):
        raise _fail("build_commit 必须为 40 位 Git SHA。")
    if not source_ref.strip():
        raise _fail("source_ref 不能为空。")

    workflow_path = _workflow_path(repository, workflow_ref)
    allowed = {value.casefold() for value in allowed_workflow_paths}
    if workflow_path.casefold() not in allowed:
        raise _fail(f"未批准的 Windows 原生 workflow：{workflow_path}")

    return {
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        "github_workflow_ref": workflow_ref,
        "source_head": source_head,
        "source_ref": source_ref,
        "build_commit": build_commit,
    }


def _validate_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise _fail("输入发布 ZIP 为空。")
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise _fail(f"输入 ZIP 包含不安全路径：{name!r}")
        if "\\" in name or ":" in name:
            raise _fail(f"输入 ZIP 包含非规范路径：{name!r}")
        if posixpath.normpath(name) != name.rstrip("/"):
            raise _fail(f"输入 ZIP 包含非规范路径：{name!r}")
        key = name.rstrip("/").casefold()
        if key in seen:
            raise _fail(f"输入 ZIP 包含重复路径：{name!r}")
        seen.add(key)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise _fail(f"输入 ZIP 禁止符号链接：{name!r}")
        if info.flag_bits & 0x1:
            raise _fail(f"输入 ZIP 禁止加密成员：{name!r}")
    return infos


def _extract_archive(package: Path, destination: Path) -> Path:
    try:
        with zipfile.ZipFile(package) as archive:
            infos = _validate_members(archive)
            roots = {
                PurePosixPath(info.filename).parts[0]
                for info in infos
                if PurePosixPath(info.filename).parts
            }
            if len(roots) != 1:
                raise _fail("输入发布 ZIP 必须只有一个顶层目录。")
            archive.extractall(destination)
    except zipfile.BadZipFile as error:
        raise _fail("输入发布文件不是有效 ZIP。") from error
    root = destination / next(iter(roots))
    if not root.is_dir():
        raise _fail("输入发布 ZIP 顶层目录无效。")
    return root


def _manifest_file_entries(payload_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in payload_root.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(payload_root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if not entries:
        raise _fail("Windows payload 为空。")
    return entries


def _ps_literal(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f'    "{key}" = ${str(value).lower()}'
    if isinstance(value, str):
        escaped = value.replace('"', '`"')
        return f'    "{key}" = "{escaped}"'
    raise _fail(f"运行时目标门不支持字段 {key}={value!r}。")


def _runtime_gate(
    required_values: dict[str, Any],
    provenance_fields: list[str],
    allowed_workflow_paths: list[str],
    *,
    allowed_executable_paths: list[str] | None = None,
    product_version: str | None = None,
) -> str:
    expected_lines = [
        _ps_literal(key, value) for key, value in required_values.items()
    ]
    expected_lines.extend(
        (
            _ps_literal("native_ci_verified", True),
            _ps_literal("user_install_allowed", True),
        )
    )
    if product_version is not None:
        expected_lines.append(_ps_literal("product_version", product_version))
    expected_block = "\n".join(expected_lines)
    provenance_names = ", ".join(f'"{value}"' for value in provenance_fields)
    workflow_names = ", ".join(f'"{value}"' for value in allowed_workflow_paths)
    executable_names = ", ".join(
        f'"{value.lower()}"' for value in (allowed_executable_paths or [])
    )
    return f'''{_GOAL_GATE_MARKER}
$goalGateExpected = [ordered]@{{
{expected_block}
}}
$goalGateRequiredProvenance = @({provenance_names})
$goalGateAllowedWorkflowPaths = @({workflow_names})
$goalGateAllowedExecutables = @({executable_names})
$goalGateManifestPath = Join-Path $PSScriptRoot "release-manifest.json"
if (-not (Test-Path -LiteralPath $goalGateManifestPath -PathType Leaf)) {{
    throw "GOAL_INTEGRITY_VIOLATION: release-manifest.json missing"
}}
$goalGateManifest = Get-Content -LiteralPath $goalGateManifestPath -Raw | ConvertFrom-Json
foreach ($goalGateEntry in $goalGateExpected.GetEnumerator()) {{
    $goalGateProperty = $goalGateManifest.PSObject.Properties[$goalGateEntry.Key]
    if ($null -eq $goalGateProperty -or $goalGateProperty.Value -ne $goalGateEntry.Value) {{
        throw "GOAL_INTEGRITY_VIOLATION: manifest goal mismatch: $($goalGateEntry.Key)"
    }}
}}
foreach ($goalGateField in $goalGateRequiredProvenance) {{
    $goalGateValue = [string]$goalGateManifest.$goalGateField
    if ([string]::IsNullOrWhiteSpace($goalGateValue)) {{
        throw "GOAL_INTEGRITY_VIOLATION: native provenance missing: $goalGateField"
    }}
}}
$goalGateRepository = [string]$goalGateManifest.github_repository
$goalGateWorkflowRef = [string]$goalGateManifest.github_workflow_ref
$goalGateWorkflowAllowed = $false
foreach ($goalGateWorkflowPath in $goalGateAllowedWorkflowPaths) {{
    if ($goalGateWorkflowRef.StartsWith(
            "$goalGateRepository/$goalGateWorkflowPath@",
            [System.StringComparison]::OrdinalIgnoreCase)) {{
        $goalGateWorkflowAllowed = $true
        break
    }}
}}
if (-not $goalGateWorkflowAllowed) {{
    throw "GOAL_INTEGRITY_VIOLATION: unapproved native workflow"
}}
$goalGateForbiddenSuffixes = @(".html", ".htm", ".js", ".css")
$goalGateForbiddenFragments = @("slicedhelper", "windows-helper", "picotoopet slice d.exe")
$goalGateExecutableRoot = Join-Path $PSScriptRoot "payload"
foreach ($goalGateFile in Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File) {{
    $goalGateName = $goalGateFile.Name.ToLowerInvariant()
    foreach ($goalGateFragment in $goalGateForbiddenFragments) {{
        if ($goalGateName.Contains($goalGateFragment)) {{
            throw "GOAL_INTEGRITY_VIOLATION: forbidden helper payload"
        }}
    }}
    foreach ($goalGateSuffix in $goalGateForbiddenSuffixes) {{
        if ($goalGateName.EndsWith($goalGateSuffix)) {{
            throw "GOAL_INTEGRITY_VIOLATION: forbidden web UI payload"
        }}
    }}
    if ($goalGateName.EndsWith(".exe")) {{
        $goalGateRelative = $goalGateFile.FullName.Substring(
            $goalGateExecutableRoot.Length).TrimStart("\\").Replace("\\", "/").ToLowerInvariant()
        if ($goalGateAllowedExecutables -notcontains $goalGateRelative) {{
            throw "GOAL_INTEGRITY_VIOLATION: unapproved executable payload"
        }}
    }}
}}
'''


def _inject_runtime_gate(path: Path, gate: str) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise _fail(f"无法读取正式脚本：{path.name}") from error
    if _GOAL_GATE_MARKER in text:
        text = text.split(_GOAL_GATE_MARKER, 1)[0].rstrip() + "\n"
    path.write_text(gate + "\n" + text, encoding="utf-8")


def _product_version(
    *,
    package_root: Path,
    manifest: dict[str, Any],
    build_report: dict[str, Any],
    product_contract: object,
) -> str | None:
    if product_contract is None:
        return None
    if not isinstance(product_contract, dict):
        raise _fail("product_version 合同无效。")
    expected = product_contract.get("value")
    source_relative = product_contract.get("source_path")
    payload_relative = product_contract.get("payload_path")
    if not all(isinstance(value, str) and value for value in (
        expected,
        source_relative,
        payload_relative,
    )):
        raise _fail("product_version 合同字段无效。")
    source_path = _REPO_ROOT / str(source_relative)
    payload_path = package_root / "payload" / str(payload_relative)
    try:
        source_value = source_path.read_text(encoding="utf-8").strip()
        payload_value = payload_path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise _fail("无法读取产品版本源或 payload 版本文件。") from error
    if source_value != expected:
        raise _fail("唯一产品版本源与目标合同不一致。")
    if payload_value != expected:
        raise _fail("Windows payload 产品版本与目标合同不一致。")
    if manifest.get("product_version") != expected:
        raise _fail("Windows Manifest 产品版本与目标合同不一致。")
    if build_report.get("product_version") != expected:
        raise _fail("Windows 构建报告产品版本与目标合同不一致。")
    return str(expected)


def _write_zip(source_root: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(
        target,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source_root.rglob("*")):
            relative = path.relative_to(source_root.parent).as_posix()
            if path.is_dir():
                archive.writestr(relative.rstrip("/") + "/", b"")
            else:
                archive.write(path, relative)


def stamp_windows_release(
    package: Path | str,
    *,
    output_root: Path | str,
    source_head: str,
    source_ref: str,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    source_package = Path(package)
    output = Path(output_root)
    contract_file = Path(contract_path)
    if not source_package.is_file() or source_package.stat().st_size <= 0:
        raise _fail("输入 Windows ZIP 不存在或为空。")

    source_report_path = source_package.parent / "windows-build-report.json"
    source_report = _read_json(source_report_path)
    if source_report.get("status") != "pass":
        raise _fail("输入 Windows 构建报告不是 pass。")
    if source_report.get("native_ci_verified") is not True:
        raise _fail("输入 Windows 构建报告没有原生 CI 证明。")
    if source_report.get("user_install_allowed") is not True:
        raise _fail("输入 Windows 构建报告未允许用户安装。")
    actual_input_sha = _sha256(source_package)
    if source_report.get("package_sha256") != actual_input_sha:
        raise _fail("输入 Windows ZIP 与构建报告 SHA-256 不一致。")

    contract = _read_json(contract_file)
    windows = contract.get("windows")
    if not isinstance(windows, dict):
        raise _fail("目标合同缺少 windows 对象。")
    required_values = windows.get("required_manifest_values")
    provenance_fields = windows.get("required_native_ci_provenance_fields")
    allowed_workflows = windows.get("allowed_native_ci_workflow_paths")
    allowed_executables = windows.get("allowed_payload_executable_paths")
    if not isinstance(required_values, dict):
        raise _fail("required_manifest_values 无效。")
    for value, name in (
        (provenance_fields, "required_native_ci_provenance_fields"),
        (allowed_workflows, "allowed_native_ci_workflow_paths"),
        (allowed_executables, "allowed_payload_executable_paths"),
    ):
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise _fail(f"{name} 无效。")
    repository = _validated_nonempty(
        required_values.get("github_repository"), "github_repository"
    )
    provenance = _provenance(
        source_head=source_head,
        source_ref=source_ref,
        repository=repository,
        allowed_workflow_paths=allowed_workflows,
    )

    output.mkdir(parents=True, exist_ok=True)
    output_package = output / source_package.name
    output_report = output / "windows-build-report.json"
    with tempfile.TemporaryDirectory(prefix="picotoo-goal-stamp-") as temporary:
        package_root = _extract_archive(source_package, Path(temporary))
        manifest_path = package_root / "release-manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("native_ci_verified") is not True:
            raise _fail("输入 Manifest 没有原生 CI 证明。")
        if manifest.get("user_install_allowed") is not True:
            raise _fail("输入 Manifest 未允许用户安装。")
        for field in provenance_fields:
            if manifest.get(field) != provenance[field]:
                raise _fail(f"输入 Manifest 溯源字段不一致：{field}")
            if source_report.get(field) != provenance[field]:
                raise _fail(f"输入构建报告溯源字段不一致：{field}")
        if manifest.get("github_repository") != repository:
            raise _fail("输入 Manifest github_repository 不一致。")
        if source_report.get("github_repository") != repository:
            raise _fail("输入构建报告 github_repository 不一致。")

        product_version = _product_version(
            package_root=package_root,
            manifest=manifest,
            build_report=source_report,
            product_contract=windows.get("product_version"),
        )
        manifest.update(required_values)
        manifest["native_ci_verified"] = True
        manifest["user_install_allowed"] = True
        manifest.update(provenance)
        if product_version is not None:
            manifest["product_version"] = product_version

        gate = _runtime_gate(
            required_values,
            provenance_fields,
            allowed_workflows,
            allowed_executable_paths=allowed_executables,
            product_version=product_version,
        )
        for script_name in _FORMAL_SCRIPTS:
            script_path = package_root / script_name
            if not script_path.is_file():
                raise _fail(f"输入正式包缺少 {script_name}。")
            _inject_runtime_gate(script_path, gate)

        manifest["files"] = _manifest_file_entries(package_root / "payload")
        _write_json(manifest_path, manifest)
        _write_zip(package_root, output_package)

    output_sha = _sha256(output_package)
    sha_file = output / f"{output_package.name}.sha256.txt"
    sha_file.write_text(
        f"{output_sha}  {output_package.name}\n",
        encoding="utf-8",
    )

    source_report.update(required_values)
    source_report["native_ci_verified"] = True
    source_report["user_install_allowed"] = True
    source_report.update(provenance)
    if product_version is not None:
        source_report["product_version"] = product_version
    source_report["package"] = str(output_package.resolve())
    source_report["package_sha256"] = output_sha
    _write_json(output_report, source_report)

    goal_report = output / "project-goal-integrity-report.json"
    goal_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "policy_id": contract.get("policy_id"),
        "status": "pass",
        "package": str(output_package.resolve()),
        "package_sha256": output_sha,
        "product_version": product_version,
        "delivery_surface": required_values.get("delivery_surface"),
        "ui_framework": required_values.get("ui_framework"),
        "integration_target": required_values.get("integration_target"),
        "native_ci_verified": True,
        "user_install_allowed": True,
        "github_repository": repository,
        **provenance,
        "installer_goal_gate": "pass",
    }
    _write_json(goal_report, goal_payload)
    return {
        "package": output_package,
        "build_report": output_report,
        "sha256_file": sha_file,
        "goal_integrity_report": goal_report,
        "package_sha256": output_sha,
        "product_version": product_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--contract", type=Path, default=_DEFAULT_CONTRACT)
    args = parser.parse_args()

    try:
        result = stamp_windows_release(
            args.package,
            output_root=args.output_root,
            source_head=args.source_head,
            source_ref=args.source_ref,
            contract_path=args.contract,
        )
    except GoalStampError as error:
        print(str(error))
        return 1

    print("PROJECT_GOAL_INTEGRITY_STAMP=PASS")
    print(f"PACKAGE={result['package']}")
    print(f"SHA256={result['package_sha256']}")
    print(f"REPORT={result['goal_integrity_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
