from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any


class GoalIntegrityError(ValueError):
    """The candidate changes the approved product goal or delivery surface."""


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACT = _REPO_ROOT / "contracts" / "release" / "project-goal-invariants.json"
_GOAL_GATE_MARKER = "# PICOTOO_GOAL_INTEGRITY_GATE_V1"
_FORMAL_RUNTIME_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoalIntegrityError(
            f"GOAL_INTEGRITY_VIOLATION: 无法读取目标合同：{path}"
        ) from error
    if not isinstance(payload, dict):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 目标合同顶层必须是 JSON 对象。"
        )
    return payload


def _single_root(names: list[str]) -> str:
    roots = {
        name.split("/", 1)[0]
        for name in names
        if name and not name.startswith("/")
    }
    if len(roots) != 1:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 发布 ZIP 必须只有一个顶层目录。"
        )
    return next(iter(roots))


def _read_manifest(
    archive: zipfile.ZipFile,
    root: str,
) -> dict[str, Any]:
    name = f"{root}/release-manifest.json"
    try:
        document = json.loads(archive.read(name).decode("utf-8-sig"))
    except KeyError as error:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 缺少 release-manifest.json。"
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: release-manifest.json 不是有效 UTF-8 JSON。"
        ) from error
    if not isinstance(document, dict):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: release-manifest.json 顶层必须是对象。"
        )
    return document


def _require_manifest_values(
    manifest: dict[str, Any],
    required: dict[str, Any],
) -> None:
    for key, expected in required.items():
        actual = manifest.get(key)
        if actual != expected:
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: 不得降级或曲解项目目标；"
                f"{key} 必须为 {expected!r}，实际为 {actual!r}。"
            )


def _require_native_ci_provenance(
    manifest: dict[str, Any],
    required_fields: list[str],
) -> None:
    """可安装原生包必须可追溯到具体 GitHub Actions Windows run。"""

    if not (
        manifest.get("native_ci_verified") is True
        or manifest.get("user_install_allowed") is True
    ):
        return

    values: dict[str, str] = {}
    for field in required_fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: 可安装包缺少原生 CI 溯源字段 "
                f"{field}。"
            )
        values[field] = value.strip()

    for field in ("github_run_id", "github_run_attempt"):
        value = values.get(field, "")
        if not _POSITIVE_INTEGER_PATTERN.fullmatch(value):
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: 原生 CI 溯源字段 "
                f"{field} 必须为正整数。"
            )

    workflow_ref = values.get("github_workflow_ref", "")
    if ".github/workflows/" not in workflow_ref or "@" not in workflow_ref:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: github_workflow_ref 不是有效工作流引用。"
        )

    for field in ("source_head", "build_commit"):
        value = values.get(field, "")
        if not _SHA256_PATTERN.fullmatch(value):
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: 原生 CI 溯源字段 "
                f"{field} 必须为 40 位 Git 提交 SHA。"
            )


def _require_archive_paths(
    names: list[str],
    *,
    root: str,
    required: list[str],
) -> None:
    available = set(names)
    missing = sorted(
        relative
        for relative in required
        if f"{root}/{relative}" not in available
    )
    if missing:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 正式 Windows 包必须复用现有 WPF "
            f"安装链，缺少：{missing!r}"
        )


def _reject_forbidden_paths(
    names: list[str],
    *,
    fragments: list[str],
    suffixes: list[str],
) -> None:
    lowered_fragments = tuple(value.lower() for value in fragments)
    lowered_suffixes = tuple(value.lower() for value in suffixes)
    forbidden: list[str] = []
    for name in names:
        lowered = name.lower()
        if any(fragment in lowered for fragment in lowered_fragments):
            forbidden.append(name)
            continue
        if lowered.endswith(lowered_suffixes):
            forbidden.append(name)
    if forbidden:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 浏览器、本地 HTTP 或独立 Helper "
            "不是现有原生 WPF 交付，禁止进入正式包："
            f"{sorted(forbidden)!r}"
        )


def _powershell_literal(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f'"{key}" = ${str(value).lower()}'
    if isinstance(value, str):
        return f'"{key}" = "{value}"'
    raise GoalIntegrityError(
        f"GOAL_INTEGRITY_VIOLATION: 运行时目标门不支持字段 {key}={value!r}。"
    )


def _require_runtime_goal_gates(
    archive: zipfile.ZipFile,
    *,
    root: str,
    required_values: dict[str, Any],
    provenance_fields: list[str],
) -> None:
    expected = [
        _powershell_literal(key, value)
        for key, value in required_values.items()
    ]
    expected.extend(
        (
            '"native_ci_verified" = $true',
            '"user_install_allowed" = $true',
            '"picotoo pet ai.exe"',
            '"tools/diagnostics/picotoopet.desktop.diagnostics.exe"',
            "forbidden web UI payload",
        )
    )
    expected.extend(f'"{field}"' for field in provenance_fields)

    for script_name in _FORMAL_RUNTIME_SCRIPTS:
        archive_name = f"{root}/{script_name}"
        try:
            script = archive.read(archive_name).decode("utf-8-sig")
        except KeyError as error:
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: 正式 Windows 包缺少 "
                f"{script_name} runtime gate。"
            ) from error
        except UnicodeDecodeError as error:
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: "
                f"{script_name} 不是有效 UTF-8 PowerShell。"
            ) from error

        if script.count(_GOAL_GATE_MARKER) != 1:
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: "
                f"{script_name} runtime gate 缺失或重复。"
            )
        missing = [fragment for fragment in expected if fragment not in script]
        if missing:
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: "
                f"{script_name} runtime gate 不完整，缺少：{missing!r}"
            )


def verify_windows_package(
    package: Path | str,
    *,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    path = Path(package)
    if not path.is_file() or path.stat().st_size <= 0:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 候选安装包不存在或为空。"
        )

    contract = _load_contract(Path(contract_path))
    windows = contract.get("windows")
    if not isinstance(windows, dict):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 目标合同缺少 windows 对象。"
        )
    required_values = windows.get("required_manifest_values")
    provenance_fields = windows.get("required_native_ci_provenance_fields")
    required_paths = windows.get("required_archive_paths")
    forbidden_fragments = windows.get("forbidden_name_fragments")
    forbidden_suffixes = windows.get("forbidden_suffixes")
    if not isinstance(required_values, dict):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: required_manifest_values 无效。"
        )
    if not isinstance(provenance_fields, list) or not all(
        isinstance(value, str) and value for value in provenance_fields
    ):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: required_native_ci_provenance_fields 无效。"
        )
    if not isinstance(required_paths, list) or not all(
        isinstance(value, str) for value in required_paths
    ):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: required_archive_paths 无效。"
        )
    if not isinstance(forbidden_fragments, list) or not all(
        isinstance(value, str) for value in forbidden_fragments
    ):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: forbidden_name_fragments 无效。"
        )
    if not isinstance(forbidden_suffixes, list) or not all(
        isinstance(value, str) for value in forbidden_suffixes
    ):
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: forbidden_suffixes 无效。"
        )

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise GoalIntegrityError(
            "GOAL_INTEGRITY_VIOLATION: 候选文件不是有效 ZIP。"
        ) from error

    with archive:
        names = archive.namelist()
        root = _single_root(names)
        manifest = _read_manifest(archive, root)
        _require_manifest_values(manifest, required_values)
        _require_native_ci_provenance(manifest, provenance_fields)
        _require_archive_paths(
            names,
            root=root,
            required=required_paths,
        )
        _reject_forbidden_paths(
            names,
            fragments=forbidden_fragments,
            suffixes=forbidden_suffixes,
        )
        _require_runtime_goal_gates(
            archive,
            root=root,
            required_values=required_values,
            provenance_fields=provenance_fields,
        )

        if (
            windows.get("user_install_requires_native_ci") is True
            and manifest.get("user_install_allowed") is True
            and manifest.get("native_ci_verified") is not True
        ):
            raise GoalIntegrityError(
                "GOAL_INTEGRITY_VIOLATION: user_install_allowed=true 时 "
                "native_ci_verified 必须为 true；平台受阻只能标记 "
                "BLOCKED、UNVERIFIED 或 DIAGNOSTIC，不能改成浏览器 Helper。"
            )

    return {
        "schema_version": "1.0",
        "policy_id": contract.get("policy_id"),
        "status": "pass",
        "package": path.name,
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


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--contract", type=Path, default=_DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    try:
        report = verify_windows_package(
            args.package,
            contract_path=args.contract,
        )
    except GoalIntegrityError as error:
        report = {
            "schema_version": "1.0",
            "policy_id": "GOV-GOAL-001",
            "status": "fail",
            "error_code": "GOAL_INTEGRITY_VIOLATION",
            "package": str(args.package),
            "error": str(error),
        }
        if args.report is not None:
            _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    if args.report is not None:
        _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
