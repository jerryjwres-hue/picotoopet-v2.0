from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

GOAL_GATE_START = "# PICOTOO_GOAL_GATE_START"
GOAL_GATE_END = "# PICOTOO_GOAL_GATE_END"
FORMAL_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
    "Rollback-Phase2Prebuilt.ps1",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _single_root(expand_root: Path) -> Path:
    entries = list(expand_root.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise RuntimeError("Windows ZIP 必须只有一个顶层目录。")
    return entries[0]


def _copy_tree_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _manifest_entries(payload_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in payload_root.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(payload_root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return entries


def _ps_literal(value: str) -> str:
    return value.replace('"', '`"')


def _goal_gate_block(
    required_values: dict[str, Any],
    provenance: dict[str, str],
    workflow_path: str,
    product_version: str,
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
    boolean_names = (
        "source_build_on_user_pc",
        "browser_ui",
        "local_http_ui",
    )
    lines = [
        GOAL_GATE_START,
        "$goalGateExpected = [ordered]@{",
    ]
    for name in string_names:
        lines.append(f'    "{name}" = "{_ps_literal(str(required_values[name]))}"')
    for name in boolean_names:
        value = "$true" if bool(required_values[name]) else "$false"
        lines.append(f'    "{name}" = {value}')
    lines.append(f'    "product_version" = "{_ps_literal(product_version)}"')
    lines.extend(
        [
            '    "native_ci_verified" = $true',
            '    "user_install_allowed" = $true',
            f'    "github_run_id" = "{_ps_literal(provenance["github_run_id"])}"',
            f'    "github_run_attempt" = "{_ps_literal(provenance["github_run_attempt"])}"',
            f'    "github_workflow_ref" = "{_ps_literal(provenance["github_workflow_ref"])}"',
            f'    "github_workflow_path" = "{_ps_literal(workflow_path)}"',
            f'    "source_head" = "{_ps_literal(provenance["source_head"])}"',
            f'    "source_ref" = "{_ps_literal(provenance["source_ref"])}"',
            f'    "build_commit" = "{_ps_literal(provenance["build_commit"])}"',
            "}",
            "$goalGateManifestPath = Join-Path $PSScriptRoot \"release-manifest.json\"",
            "if (-not (Test-Path -LiteralPath $goalGateManifestPath -PathType Leaf)) {",
            '    throw "目标完整性门禁：release-manifest.json 缺失。"',
            "}",
            "$goalGateEncoding = [System.Text.UTF8Encoding]::new($false, $true)",
            "$goalGateManifest = ([System.IO.File]::ReadAllText(",
            "    $goalGateManifestPath,",
            "    $goalGateEncoding) | ConvertFrom-Json)",
            "foreach ($goalGateEntry in $goalGateExpected.GetEnumerator()) {",
            "    if (-not ($goalGateManifest.PSObject.Properties.Name -contains $goalGateEntry.Key)) {",
            '        throw "目标完整性门禁：Manifest 缺少字段 $($goalGateEntry.Key)。"',
            "    }",
            "    $goalGateActual = $goalGateManifest.($goalGateEntry.Key)",
            "    if ($goalGateEntry.Value -is [bool]) {",
            "        if ([bool]$goalGateActual -ne [bool]$goalGateEntry.Value) {",
            '            throw "目标完整性门禁失败：$($goalGateEntry.Key)。"',
            "        }",
            "    }",
            "    elseif ([string]$goalGateActual -ne [string]$goalGateEntry.Value) {",
            '        throw "目标完整性门禁失败：$($goalGateEntry.Key)。"',
            "    }",
            "}",
            GOAL_GATE_END,
        ]
    )
    return "\n".join(lines) + "\n"


def _inject_goal_gate(
    package_root: Path,
    required_values: dict[str, Any],
    provenance: dict[str, str],
    workflow_path: str,
    product_version: str,
) -> None:
    block = _goal_gate_block(
        required_values,
        provenance,
        workflow_path,
        product_version,
    )
    for relative in FORMAL_SCRIPTS:
        path = package_root / relative
        text = path.read_text(encoding="utf-8-sig")
        start = text.find(GOAL_GATE_START)
        end = text.find(GOAL_GATE_END)
        if (start >= 0 or end >= 0:
            if start < 0 or end < 0 or end < start:
                raise RuntimeError(f"目标完整性门禁标记损坏：{relative}")
            end += len(GOAL_GATE_END)
            while end < len(text) and text[end] in "\r\n":
                end += 1
            text = text[:start] + text[end:]
        if text.startswith("#!"):
            line_end = text.find("\n")
            if line_end >= 0:
                text = text[: line_end + 1] + block + text[line_end + 1 :]
            else:
                text = text + "\n" + block
        else:
            text = block + text
        path.write_text(text, encoding="utf-8")


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Windows ZIP 包含不安全路径：{name}")
            if "\\" in name or ":" in name:
                raise RuntimeError(f"Windows ZIP 包含非规范路径：{name}")
            normalized = posixpath.normpath(name)
            if normalized != name.rstrip("/"):
                raise RuntimeError(f"Windows ZIP 包含非规范路径：{name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError(f"Windows ZIP 禁止符号链接：{name}")
        bundle.extractall(destination)


def _build_zip(package_root: Path, archive_path: Path) -> None:
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        root_name = package_root.name
        for path in sorted(package_root.rglob("*")):
            relative = path.relative_to(package_root).as_posix()
            archive_name = f"{root_name}/{relative}"
            if path.is_dir():
                bundle.writestr(archive_name.rstrip("/") + "/", b"")
            else:
                bundle.write(path, archive_name)


def _validated_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"缺少原生 CI 溯源字段：{name}")
    return value.strip()


def _workflow_path_from_ref(repository: str, workflow_ref: str) -> str:
    prefix = f"{repository}/"
    if not workflow_ref.startswith(prefix) or "@" not in workflow_ref:
        raise RuntimeError("GITHUB_WORKFLOW_REF 与批准仓库不一致。")
    path, _, _ = workflow_ref[len(prefix) :].partition("@")
    if not path:
        raise RuntimeError("GITHUB_WORKFLOW_REF 缺少 workflow 路径。")
    return path


def _require_ci_provenance(
    required_values: dict[str, Any],
    windows_contract: dict[str, Any],
    manifest: dict[str, Any],
    build_report: dict[str, Any],
) -> tuple[dict[str, str], str]:
    if os.environ.get("CI", "").lower() != "true":
        raise RuntimeError("只允许在 CI=true 的原生 Windows 流程盖章。")
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        raise RuntimeError("只允许在 GITHUB_ACTIONS=true 的流程盖章。")
    if os.environ.get("RUNNER_OS", "").lower() != "windows":
        raise RuntimeError("只允许原生 Windows Runner 盖章。")

    repository = _validated_string(
        os.environ.get("GITHUB_REPOSITORY"),
        "GITHUB_REPOSITORY",
    )
    expected_repository = str(required_values["github_repository"])
    if repository.lower() != expected_repository.lower():
        raise RuntimeError(
            f"盖章仓库不一致：{repository!r} != {expected_repository!r}"
        )

    provenance = {
        "github_run_id": _validated_string(
            os.environ.get("GITHUB_RUN_ID"),
            "GITHUB_RUN_ID",
        ),
        "github_run_attempt": _validated_string(
            os.environ.get("GITHUB_RUN_ATTEMPT"),
            "GITHUB_RUN_ATTEMPT",
        ),
        "github_workflow_ref": _validated_string(
            os.environ.get("GITHUB_WORKFLOW_REF"),
            "GITHUB_WORKFLOW_REF",
        ),
        "source_head": _validated_string(
            os.environ.get("PICOTOO_SOURCE_HEAD_SHA"),
            "PICOTOO_SOURCE_HEAD_SHA",
        ),
        "source_ref": _validated_string(
            os.environ.get("PICOTOO_SOURCE_REF"),
            "PICOTOO_SOURCE_REF",
        ),
        "build_commit": _validated_string(
            os.environ.get("GITHUB_SHA"),
            "GITHUB_SHA",
        ),
    }
    workflow_path = _workflow_path_from_ref(
        repository,
        provenance["github_workflow_ref"],
    )
    allowed_workflows = windows_contract.get("allowed_native_ci_workflow_paths", [])
    if not isinstance(allowed_workflows, list) or not allowed_workflows:
        raise RuntimeError("目标合同缺少批准的 Windows 原生 workflow 白名单。")
    allowed = {str(item).lower() for item in allowed_workflows}
    if workflow_path.lower() not in allowed:
        raise RuntimeError(f"未批准的 Windows 原生 workflow：{workflow_path}")

    fields = windows_contract.get("required_native_ci_provenance_fields", [])
    if not isinstance(fields, list) or not fields:
        raise RuntimeError("目标合同缺少原生 CI 溯源字段定义。")
    for field in fields:
        if field not in provenance:
            raise RuntimeError(f"目标合同声明了未知溯源字段：{field}")
        expected = provenance[field]
        if str(manifest.get(field) or "") != expected:
            raise RuntimeError(
                f"Manifest 溯源字段不一致：{field} | "
                f"{manifest.get(field)!r} != {expected!r}"
            )
        if str(build_report.get(field) or "") != expected:
            raise RuntimeError(
                f"构建报告溯源字段不一致：{field} | "
                f"{build_report.get(field)!r} != {expected!r}"
            )

    return provenance, workflow_path


def _require_product_version(
    repo_root: Path,
    package_root: Path,
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    windows_contract = contract["windows"]
    product_version_contract = windows_contract["product_version"]
    expected = _validated_string(product_version_contract.get("value"), "product_version.value")
    source_path = repo_root / _validated_string(
        product_version_contract.get("source_path"),
        "product_version.source_path",
    )
    payload_path = package_root / "payload" / _validated_string(
        product_version_contract.get("payload_path"),
        "product_version.payload_path",
    )
    if source_path.read_text(encoding="utf-8").strip() != expected:
        raise RuntimeError("唯一产品版本源与目标合同不一致。")
    if payload_path.read_text(encoding="utf-8-sig").strip() != expected:
        raise RuntimeError("Windows payload 产品版本与目标合同不一致。")
    if manifest.get("product_version") != expected:
        raise RuntimeError("Windows Manifest 产品版本与目标合同不一致。")
    return expected


def _stamp(
    repo_root: Path,
    archive_path: Path,
    build_report_path: Path,
    contract_path: Path,
) -> tuple[str, Path, Path]:
    contract = _read_json(contract_path)
    windows_contract = contract["windows"]
    required_values = dict(windows_contract["required_manifest_values"])
    build_report = _read_json(build_report_path)

    with tempfile.TemporaryDirectory(prefix="picotoo-goal-stamp-") as temporary:
        expand_root = Path(temporary) / "expanded"
        expand_root.mkdir()
        _extract_zip(archive_path, expand_root)
        package_root = _single_root(expand_root)
        manifest_path = package_root / "release-manifest.json"
        manifest = _read_json(manifest_path)

        provenance, workflow_path = _require_ci_provenance(
            required_values,
            windows_contract,
            manifest,
            build_report,
        )
        product_version = _require_product_version(
            repo_root,
            package_root,
            manifest,
            contract,
        )

        source_build_on_user_pc = required_values.pop(
            "source_build_on_user_pc",
            None,
        )
        manifest.update(required_values)
        if source_build_on_user_pc is not None:
            manifest["source_build_on_user_pc"] = source_build_on_user_pc
        manifest["product_version"] = product_version
        manifest["native_ci_verified"] = True
        manifest["user_install_allowed"] = True
        manifest.update(provenance)
        _write_json(manifest_path, manifest)

        _inject_goal_gate(
            package_root,
            {
                **required_values,
                "source_build_on_user_pc": source_build_on_user_pc,
            },
            provenance,
            workflow_path,
            product_version,
        )

        manifest["files"] = _manifest_entries(package_root / "payload")
        _write_json(manifest_path, manifest)
        _build_zip(package_root, archive_path)

    digest = _sha256(archive_path)
    sidecar_path = archive_path.with_name(f"{archive_path.name}.sha256.txt")
    sidecar_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="utf-8",
    )

    build_report.update(required_values)
    if source_build_on_user_pc is not None:
        build_report["source_build_on_user_pc"] = source_build_on_user_pc
    build_report["product_version"] = product_version
    build_report["native_ci_verified"] = True
    build_report["user_install_allowed"] = True
    build_report.update(provenance)
    build_report["package"] = str(archive_path.resolve())
    build_report["package_sha256"] = digest
    _write_json(build_report_path, build_report)

    report = {
        "schema_version": "1.0",
        "policy_id": contract["policy_id"],
        "status": "pass",
        "product_version": product_version,
        "archive": str(archive_path.resolve()),
        "archive_sha256": digest,
        "build_report": str(build_report_path.resolve()),
        "contract": str(contract_path.resolve()),
        "workflow_path": workflow_path,
        "goal_values": {
            **required_values,
            "source_build_on_user_pc": source_build_on_user_pc,
            "product_version": product_version,
            "native_ci_verified": True,
            "user_install_allowed": True,
            **provenance,
        },
    }
    report_path = archive_path.parent / "project-goal-integrity-stamp.json"
    _write_json(report_path, report)
    return digest, sidecar_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在原生 Windows CI 验证并盖章项目目标完整性。"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()

    digest, sidecar, report = _stamp(
        args.repo_root.resolve(),
        args.archive.resolve(),
        args.build_report.resolve(),
        args.contract.resolve(),
    )
    print("PROJECT_GOAL_INTEGRITY_STAMP=PASS")
    print(f"SHA256={digest}")
    print(f"SIDECAR={sidecar}")
    print(f"REPORT={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
