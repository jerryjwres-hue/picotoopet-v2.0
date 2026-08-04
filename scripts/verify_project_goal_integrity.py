from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class GoalIntegrityError(ValueError):
    """The candidate changes the approved product goal or delivery surface."""


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACT = _REPO_ROOT / "contracts" / "release" / "project-goal-invariants.json"
_GOAL_GATE_MARKER = "# PICOTOO_GOAL_INTEGRITY_GATE_V1"
_FORMAL_RUNTIME_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
    "Rollback-Phase2Prebuilt.ps1",
)
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")


def _violation(message: str) -> GoalIntegrityError:
    return GoalIntegrityError(f"GOAL_INTEGRITY_VIOLATION: {message}")


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _violation(f"无法读取目标合同：{path}") from error
    if not isinstance(payload, dict):
        raise _violation("目标合同顶层必须是 JSON 对象。")
    return payload


def _validate_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise _violation("发布 ZIP 为空。")
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise _violation(f"发布 ZIP 包含不安全路径：{name!r}")
        if "\\" in name or ":" in name:
            raise _violation(f"发布 ZIP 包含非规范路径：{name!r}")
        if posixpath.normpath(name) != name.rstrip("/"):
            raise _violation(f"发布 ZIP 包含非规范路径：{name!r}")
        key = name.rstrip("/").casefold()
        if key in seen:
            raise _violation(f"发布 ZIP 包含重复路径：{name!r}")
        seen.add(key)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise _violation(f"发布 ZIP 禁止符号链接：{name!r}")
        if info.flag_bits & 0x1:
            raise _violation(f"发布 ZIP 禁止加密成员：{name!r}")
    return infos


def _single_root(names: list[str]) -> str:
    roots = {
        PurePosixPath(name).parts[0]
        for name in names
        if name and PurePosixPath(name).parts
    }
    if len(roots) != 1:
        raise _violation("发布 ZIP 必须只有一个顶层目录。")
    return next(iter(roots))


def _read_manifest(archive: zipfile.ZipFile, root: str) -> dict[str, Any]:
    name = f"{root}/release-manifest.json"
    try:
        document = json.loads(archive.read(name).decode("utf-8-sig"))
    except KeyError as error:
        raise _violation("缺少 release-manifest.json。") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _violation("release-manifest.json 不是有效 UTF-8 JSON。") from error
    if not isinstance(document, dict):
        raise _violation("release-manifest.json 顶层必须是对象。")
    return document


def _require_manifest_values(
    manifest: dict[str, Any], required: dict[str, Any]
) -> None:
    for key, expected in required.items():
        actual = manifest.get(key)
        if actual != expected:
            raise _violation(
                "不得降级或曲解项目目标；"
                f"{key} 必须为 {expected!r}，实际为 {actual!r}。"
            )


def _require_native_ci_provenance(
    manifest: dict[str, Any],
    required_fields: list[str],
    *,
    repository: str,
    allowed_workflow_paths: list[str],
) -> None:
    if not (
        manifest.get("native_ci_verified") is True
        or manifest.get("user_install_allowed") is True
    ):
        return

    values: dict[str, str] = {}
    for field in required_fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise _violation(f"可安装包缺少原生 CI 溯源字段 {field}。")
        values[field] = value.strip()

    for field in ("github_run_id", "github_run_attempt"):
        if not _POSITIVE_INTEGER_PATTERN.fullmatch(values.get(field, "")):
            raise _violation(f"原生 CI 溯源字段 {field} 必须为正整数。")

    workflow_ref = values.get("github_workflow_ref", "")
    allowed_prefixes = tuple(
        f"{repository}/{workflow_path}@".lower()
        for workflow_path in allowed_workflow_paths
    )
    if not workflow_ref.lower().startswith(allowed_prefixes):
        raise _violation(
            "github_workflow_ref 不属于批准的 Windows 原生 CI 工作流。"
        )

    for field in ("source_head", "build_commit"):
        if not _GIT_SHA_PATTERN.fullmatch(values.get(field, "")):
            raise _violation(f"原生 CI 溯源字段 {field} 必须为 40 位 Git SHA。")


def _require_archive_paths(
    names: list[str], *, root: str, required: list[str]
) -> None:
    available = set(names)
    missing = sorted(
        relative for relative in required if f"{root}/{relative}" not in available
    )
    if missing:
        raise _violation(
            "正式 Windows 包必须复用现有 WPF 安装链，"
            f"缺少：{missing!r}"
        )


def _normalize_payload_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _violation("Manifest payload 路径不能为空。")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise _violation(f"Manifest payload 路径非法：{value!r}")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        normalized != value
        or normalized in {"", "."}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise _violation(f"Manifest payload 路径非法：{value!r}")
    return normalized


def _verify_manifest_payload(
    archive: zipfile.ZipFile,
    *,
    root: str,
    manifest: dict[str, Any],
    allowed_executable_paths: list[str],
) -> int:
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise _violation("Manifest files 必须是非空数组。")

    payload_prefix = f"{root}/payload/"
    payload_members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(payload_prefix):
            continue
        relative = _normalize_payload_path(info.filename[len(payload_prefix) :])
        key = relative.casefold()
        if key in payload_members:
            raise _violation(
                f"ZIP payload 包含大小写冲突或重复路径：{relative}"
            )
        payload_members[key] = info

    listed_paths: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise _violation("Manifest files 项必须是对象。")
        relative = _normalize_payload_path(entry.get("path"))
        key = relative.casefold()
        if key in listed_paths:
            raise _violation(f"Manifest files 包含重复路径：{relative}")
        listed_paths[key] = relative

        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_hash, str) or not _SHA256_PATTERN.fullmatch(
            expected_hash
        ):
            raise _violation(f"Manifest SHA-256 非法：{relative}")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise _violation(f"Manifest 文件大小非法：{relative}")

        member = payload_members.get(key)
        if member is None:
            raise _violation(f"Manifest 文件缺失：{relative}")
        digest = hashlib.sha256()
        actual_size = 0
        with archive.open(member) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                actual_size += len(chunk)
        if actual_size != expected_size or actual_size != member.file_size:
            raise _violation(f"payload 文件大小不一致：{relative}")
        if digest.hexdigest().lower() != expected_hash.lower():
            raise _violation(f"payload 文件 SHA-256 不一致：{relative}")

    unmanifested = sorted(
        payload_members[key].filename[len(payload_prefix) :]
        for key in payload_members.keys() - listed_paths.keys()
    )
    if unmanifested:
        raise _violation(
            f"payload 包含未列入 Manifest 的文件：{unmanifested!r}"
        )
    missing = sorted(
        listed_paths[key]
        for key in listed_paths.keys() - payload_members.keys()
    )
    if missing:
        raise _violation(f"Manifest 列出不存在的 payload 文件：{missing!r}")

    allowed_executables = {
        _normalize_payload_path(path).casefold()
        for path in allowed_executable_paths
    }
    actual_executables = {key for key in payload_members if key.endswith(".exe")}
    unexpected = sorted(actual_executables - allowed_executables)
    if unexpected:
        raise _violation(f"payload 包含未批准的可执行文件：{unexpected!r}")
    return len(listed_paths)


def _reject_forbidden_paths(
    names: list[str], *, fragments: list[str], suffixes: list[str]
) -> None:
    lowered_fragments = tuple(value.lower() for value in fragments)
    lowered_suffixes = tuple(value.lower() for value in suffixes)
    forbidden = [
        name
        for name in names
        if any(fragment in name.lower() for fragment in lowered_fragments)
        or name.lower().endswith(lowered_suffixes)
    ]
    if forbidden:
        raise _violation(
            "浏览器、本地 HTTP 或独立 Helper 不是现有原生 WPF 交付，"
            f"禁止进入正式包：{sorted(forbidden)!r}"
        )


def _powershell_literal(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f'"{key}" = ${str(value).lower()}'
    if isinstance(value, str):
        return f'"{key}" = "{value}"'
    raise _violation(f"运行时目标门不支持字段 {key}={value!r}。")


def _product_version(
    archive: zipfile.ZipFile,
    *,
    package_path: Path,
    root: str,
    manifest: dict[str, Any],
    product_contract: object,
) -> str | None:
    if product_contract is None:
        return None
    if not isinstance(product_contract, dict):
        raise _violation("product_version 合同无效。")
    expected = product_contract.get("value")
    source_relative = product_contract.get("source_path")
    payload_relative = product_contract.get("payload_path")
    if not all(isinstance(value, str) and value for value in (
        expected,
        source_relative,
        payload_relative,
    )):
        raise _violation("product_version 合同字段无效。")
    source_path = _REPO_ROOT / str(source_relative)
    try:
        source_value = source_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise _violation("无法读取唯一产品版本源。") from error
    if source_value != expected:
        raise _violation("唯一产品版本源与目标合同不一致。")
    member = f"{root}/payload/{payload_relative}"
    try:
        payload_value = archive.read(member).decode("utf-8-sig").strip()
    except (KeyError, UnicodeDecodeError) as error:
        raise _violation("无法读取 Windows payload 产品版本。") from error
    if payload_value != expected:
        raise _violation("Windows payload 产品版本与目标合同不一致。")
    if manifest.get("product_version") != expected:
        raise _violation("Windows Manifest 产品版本与目标合同不一致。")
    if (
        package_path.name.startswith("PicotooPet-Phase2-Windows-Prebuilt-")
        and f"-{expected}-" not in package_path.name
    ):
        raise _violation("Windows 正式 ZIP 文件名未包含产品版本。")
    return str(expected)


def _require_runtime_goal_gates(
    archive: zipfile.ZipFile,
    *,
    root: str,
    required_values: dict[str, Any],
    provenance_fields: list[str],
    allowed_workflow_paths: list[str],
    allowed_executable_paths: list[str],
    product_version: str | None,
) -> None:
    expected = [
        _powershell_literal(key, value)
        for key, value in required_values.items()
    ]
    expected.extend(
        (
            '"native_ci_verified" = $true',
            '"user_install_allowed" = $true',
            "forbidden web UI payload",
        )
    )
    if product_version is not None:
        expected.append(_powershell_literal("product_version", product_version))
    expected.extend(f'"{field}"' for field in provenance_fields)
    expected.extend(allowed_workflow_paths)
    expected.extend(f'"{path.lower()}"' for path in allowed_executable_paths)

    for script_name in _FORMAL_RUNTIME_SCRIPTS:
        archive_name = f"{root}/{script_name}"
        try:
            script = archive.read(archive_name).decode("utf-8-sig")
        except KeyError as error:
            raise _violation(f"正式 Windows 包缺少 {script_name} runtime gate。") from error
        except UnicodeDecodeError as error:
            raise _violation(f"{script_name} 不是有效 UTF-8 PowerShell。") from error
        if script.count(_GOAL_GATE_MARKER) != 1:
            raise _violation(f"{script_name} runtime gate 缺失或重复。")
        missing = [fragment for fragment in expected if fragment not in script]
        if missing:
            raise _violation(
                f"{script_name} runtime gate 不完整，缺少：{missing!r}"
            )


def verify_windows_package(
    package: Path | str,
    *,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    path = Path(package)
    if not path.is_file() or path.stat().st_size <= 0:
        raise _violation("候选安装包不存在或为空。")

    contract = _load_contract(Path(contract_path))
    windows = contract.get("windows")
    if not isinstance(windows, dict):
        raise _violation("目标合同缺少 windows 对象。")

    required_values = windows.get("required_manifest_values")
    provenance_fields = windows.get("required_native_ci_provenance_fields")
    allowed_workflows = windows.get("allowed_native_ci_workflow_paths")
    required_paths = windows.get("required_archive_paths")
    allowed_executables = windows.get("allowed_payload_executable_paths")
    forbidden_fragments = windows.get("forbidden_name_fragments")
    forbidden_suffixes = windows.get("forbidden_suffixes")
    if not isinstance(required_values, dict):
        raise _violation("required_manifest_values 无效。")
    repository = required_values.get("github_repository")
    if not isinstance(repository, str) or not repository:
        raise _violation("github_repository 合同无效。")
    typed_lists = (
        (provenance_fields, "required_native_ci_provenance_fields"),
        (allowed_workflows, "allowed_native_ci_workflow_paths"),
        (required_paths, "required_archive_paths"),
        (allowed_executables, "allowed_payload_executable_paths"),
        (forbidden_fragments, "forbidden_name_fragments"),
        (forbidden_suffixes, "forbidden_suffixes"),
    )
    for value, name in typed_lists:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise _violation(f"{name} 无效。")

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise _violation("候选文件不是有效 ZIP。") from error

    with archive:
        infos = _validate_archive_members(archive)
        names = [info.filename for info in infos]
        root = _single_root(names)
        manifest = _read_manifest(archive, root)
        _require_manifest_values(manifest, required_values)
        _require_native_ci_provenance(
            manifest,
            provenance_fields,
            repository=repository,
            allowed_workflow_paths=allowed_workflows,
        )
        _require_archive_paths(names, root=root, required=required_paths)
        verified_payload_files = _verify_manifest_payload(
            archive,
            root=root,
            manifest=manifest,
            allowed_executable_paths=allowed_executables,
        )
        _reject_forbidden_paths(
            names,
            fragments=forbidden_fragments,
            suffixes=forbidden_suffixes,
        )
        product_version = _product_version(
            archive,
            package_path=path,
            root=root,
            manifest=manifest,
            product_contract=windows.get("product_version"),
        )
        _require_runtime_goal_gates(
            archive,
            root=root,
            required_values=required_values,
            provenance_fields=provenance_fields,
            allowed_workflow_paths=allowed_workflows,
            allowed_executable_paths=allowed_executables,
            product_version=product_version,
        )

        if (
            windows.get("user_install_requires_native_ci") is True
            and manifest.get("user_install_allowed") is True
            and manifest.get("native_ci_verified") is not True
        ):
            raise _violation(
                "user_install_allowed=true 时 native_ci_verified 必须为 true；"
                "平台受阻不能改成浏览器 Helper。"
            )

    return {
        "schema_version": "1.0",
        "policy_id": contract.get("policy_id"),
        "status": "pass",
        "package": path.name,
        "product_version": product_version,
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
        "verified_payload_files": verified_payload_files,
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
