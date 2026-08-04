from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

GOAL_GATE_START = "# PICOTOO_GOAL_GATE_START"
GOAL_GATE_END = "# PICOTOO_GOAL_GATE_END"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_json_member(
    archive: zipfile.ZipFile,
    name: str,
) -> dict[str, Any]:
    with archive.open(name) as stream:
        return json.loads(stream.read().decode("utf-8-sig"))


def _validate_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise RuntimeError("Windows ZIP 为空。")
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Windows ZIP 包含不安全路径：{name}")
        if "\\" in name or ":" in name:
            raise RuntimeError(f"Windows ZIP 包含非规范路径：{name}")
        normalized = posixpath.normpath(name)
        if normalized != name.rstrip("/"):
            raise RuntimeError(f"Windows ZIP 包含非规范路径：{name}")
        key = name.rstrip("/").lower()
        if key in seen:
            raise RuntimeError(f"Windows ZIP 包含重复路径：{name}")
        seen.add(key)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise RuntimeError(f"Windows ZIP 禁止符号链接：{name}")
        if info.flag_bits & 0x1:
            raise RuntimeError(f"Windows ZIP 禁止加密成员：{name}")
    return infos


def _single_root(infos: list[zipfile.ZipInfo]) -> str:
    roots = {
        PurePosixPath(info.filename).parts[0]
        for info in infos
        if PurePosixPath(info.filename).parts
    }
    if len(roots) != 1:
        raise RuntimeError(f"Windows ZIP 必须只有一个顶层目录：{sorted(roots)!r}")
    return next(iter(roots))


def _workflow_path_from_ref(repository: str, workflow_ref: str) -> str:
    prefix = f"{repository}/"
    if not workflow_ref.startswith(prefix) or "@" not in workflow_ref:
        raise RuntimeError("GITHUB_WORKFLOW_REF 与批准仓库不一致。")
    path, _, _ = workflow_ref[len(prefix) :].partition("@")
    if not path:
        raise RuntimeError("GITHUB_WORKFLOW_REF 缺少 workflow 路径。")
    return path


def _require_archive_shape(
    archive: zipfile.ZipFile,
    root: str,
    contract: dict[str, Any],
) -> None:
    names = set(archive.namelist())
    windows_contract = contract["windows"]
    for relative in windows_contract["required_archive_paths"]:
        member = f"{root}/{relative}"
        if member not in names:
            raise RuntimeError(f"Windows ZIP 缺少冻结路径：{relative}")

    forbidden_fragments = tuple(
        fragment.lower()
        for fragment in windows_contract["forbidden_name_fragments"]
    )
    forbidden_suffixes = tuple(
        suffix.lower() for suffix in windows_contract["forbidden_suffixes"]
    )
    for name in names:
        lower = name.lower()
        if any(fragment in lower for fragment in forbidden_fragments):
            raise RuntimeError(f"Windows ZIP 包含禁止名称：{name}")
        if lower.endswith(forbidden_suffixes):
            raise RuntimeError(f"Windows ZIP 包含禁止前端资源：{name}")


def _normalize_payload_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("Manifest payload 路径为空。")
    if "\\" in value or ":" in value:
        raise RuntimeError(f"Manifest payload 路径不是 POSIX 相对路径：{value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise RuntimeError(f"Manifest payload 路径不安全：{value}")
    normalized = posixpath.normpath(value)
    if normalized != value:
        raise RuntimeError(f"Manifest payload 路径不是规范形式：{value}")
    return value


def _require_payload_manifest_integrity(
    archive: zipfile.ZipFile,
    root: str,
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> int:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Windows Manifest 缺少 payload 文件清单。")

    expected: dict[str, dict[str, Any]] = {}
    casefolded: set[str] = set()
    for raw_entry in files:
        if not isinstance(raw_entry, dict):
            raise RuntimeError("Windows Manifest 文件项不是对象。")
        relative = _normalize_payload_path(raw_entry.get("path"))
        folded = relative.casefold()
        if folded in casefolded:
            raise RuntimeError(f"Windows Manifest 包含重复 payload 路径：{relative}")
        casefolded.add(folded)
        digest = raw_entry.get("sha256")
        if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
            raise RuntimeError(f"Windows Manifest SHA-256 无效：{relative}")
        size = raw_entry.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RuntimeError(f"Windows Manifest 文件大小无效：{relative}")
        expected[relative] = raw_entry

    payload_prefix = f"{root}/payload/"
    actual_infos: dict[str, zipfile.ZipInfo] = {}
    actual_casefolded: set[str] = set()
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(payload_prefix):
            continue
        relative = info.filename[len(payload_prefix) :]
        normalized = _normalize_payload_path(relative)
        folded = normalized.casefold()
        if folded in actual_casefolded:
            raise RuntimeError(f"Windows ZIP 包含重复 payload 路径：{normalized}")
        actual_casefolded.add(folded)
        actual_infos[normalized] = info

    expected_paths = set(expected)
    actual_paths = set(actual_infos)
    missing = sorted(expected_paths - actual_paths)
    extras = sorted(actual_paths - expected_paths)
    if missing:
        raise RuntimeError(f"Windows ZIP 缺少 Manifest payload：{missing}")
    if extras:
        raise RuntimeError(f"Windows ZIP 包含未列入 Manifest 的 payload：{extras}")

    allowed_executables = {
        _normalize_payload_path(value).casefold()
        for value in contract["windows"]["allowed_payload_executable_paths"]
    }
    for relative, info in actual_infos.items():
        with archive.open(info) as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        entry = expected[relative]
        if digest.hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Windows payload SHA-256 不一致：{relative}")
        if size != entry["size_bytes"] or size != info.file_size:
            raise RuntimeError(f"Windows payload 文件大小不一致：{relative}")
        if relative.lower().endswith((".exe", ".com", ".scr")):
            if relative.casefold() not in allowed_executables:
                raise RuntimeError(f"Windows payload 包含未批准可执行文件：{relative}")

    return len(actual_infos)


def _require_manifest_values(
    manifest: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    required = contract["windows"]["required_manifest_values"]
    for name, expected in required.items():
        actual = manifest.get(name)
        if actual != expected:
            raise RuntimeError(
                f"Windows Manifest 目标字段不一致：{name} | "
                f"{actual!r} != {expected!r}"
            )
    if manifest.get("native_ci_verified") is not True:
        raise RuntimeError("Windows Manifest 未通过原生 CI 验证。")
    if manifest.get("user_install_allowed") is not True:
        raise RuntimeError("Windows Manifest 未允许用户安装。")


def _require_report_values(
    report: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    required = contract["windows"]["required_manifest_values"]
    for name, expected in required.items():
        if name == "source_build_on_user_pc":
            if report.get(name) != expected:
                raise RuntimeError(f"Windows 构建报告目标字段不一致：{name}")
            continue
        if name in report and report.get(name) != expected:
            raise RuntimeError(f"Windows 构建报告目标字段不一致：{name}")
    if report.get("native_ci_verified") is not True:
        raise RuntimeError("Windows 构建报告未标记原生 CI 通过。")
    if report.get("user_install_allowed") is not True:
        raise RuntimeError("Windows 构建报告未允许用户安装。")


def _require_product_version(
    archive_path: Path,
    archive: zipfile.ZipFile,
    root: str,
    manifest: dict[str, Any],
    report: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    product_version_contract = contract["windows"]["product_version"]
    product_version = product_version_contract["value"]
    if not isinstance(product_version, str) or not product_version:
        raise RuntimeError("目标合同 product_version.value 无效。")
    payload_relative = product_version_contract["payload_path"]
    if not isinstance(payload_relative, str) or not payload_relative:
        raise RuntimeError("目标合同 product_version.payload_path 无效。")
    member = f"{root}/payload/{payload_relative}"
    try:
        with archive.open(member) as stream:
            payload_value = stream.read().decode("utf-8-sig").strip()
    except KeyError as exc:
        raise RuntimeError("Windows ZIP 缺少产品版本载荷文件。") from exc
    if payload_value != product_version:
        raise RuntimeError("Windows payload 产品版本与目标合同不一致。")
    if manifest.get("product_version") != product_version:
        raise RuntimeError("Windows Manifest 产品版本与目标合同不一致。")
    if report.get("product_version") != product_version:
        raise RuntimeError("Windows 构建报告产品版本与目标合同不一致。")
    if f"-{product_version}-" not in archive_path.name:
        raise RuntimeError("Windows ZIP 文件名未包含产品版本。")
    return product_version


def _require_native_ci_provenance(
    manifest: dict[str, Any],
    report: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, str], str]:
    windows_contract = contract["windows"]
    fields = windows_contract.get("required_native_ci_provenance_fields", [])
    if not isinstance(fields, list) or not fields:
        raise RuntimeError("目标合同缺少 Windows 原生 CI 溯源字段。")

    provenance: dict[str, str] = {}
    for field in fields:
        manifest_value = manifest.get(field)
        report_value = report.get(field)
        if not isinstance(manifest_value, str) or not manifest_value.strip():
            raise RuntimeError(f"Windows Manifest 缺少原生 CI 溯源：{field}")
        if report_value != manifest_value:
            raise RuntimeError(f"Windows 报告与 Manifest 溯源不一致：{field}")
        provenance[field] = manifest_value

    expected_repository = str(
        windows_contract["required_manifest_values"]["github_repository"]
    )
    if manifest.get("github_repository") != expected_repository:
        raise RuntimeError("Windows Manifest 仓库来源不一致。")
    if report.get("github_repository") != expected_repository:
        raise RuntimeError("Windows 构建报告仓库来源不一致。")

    workflow_path = _workflow_path_from_ref(
        expected_repository,
        provenance["github_workflow_ref"],
    )
    allowed = {
        str(item).lower()
        for item in windows_contract["allowed_native_ci_workflow_paths"]
    }
    if workflow_path.lower() not in allowed:
        raise RuntimeError(f"Windows 包来自未批准 workflow：{workflow_path}")
    return provenance, workflow_path


def _ps_expected_fragment(name: str, value: Any) -> str:
    if isinstance(value, bool):
        rendered = "$true" if value else "$false"
        return f'    "{name}" = {rendered}'
    rendered = str(value).replace('"', '`"')
    return f'    "{name}" = "{rendered}"'


def _require_runtime_goal_gates(
    archive: zipfile.ZipFile,
    root: str,
    contract: dict[str, Any],
    provenance: dict[str, str],
    workflow_path: str,
    product_version: str,
) -> None:
    required = contract["windows"]["required_manifest_values"]
    expected_fragments = {
        _ps_expected_fragment(name, value)
        for name, value in required.items()
    }
    expected_fragments.update(
        {
            _ps_expected_fragment("product_version", product_version),
            _ps_expected_fragment("native_ci_verified", True),
            _ps_expected_fragment("user_install_allowed", True),
            _ps_expected_fragment("github_run_id", provenance["github_run_id"]),
            _ps_expected_fragment(
                "github_run_attempt", provenance["github_run_attempt"]
            ),
            _ps_expected_fragment(
                "github_workflow_ref", provenance["github_workflow_ref"]
            ),
            _ps_expected_fragment("github_workflow_path", workflow_path),
            _ps_expected_fragment("source_head", provenance["source_head"]),
            _ps_expected_fragment("source_ref", provenance["source_ref"]),
            _ps_expected_fragment("build_commit", provenance["build_commit"]),
        }
    )

    for relative in FORMAL_SCRIPTS:
        member = f"{root}/{relative}"
        with archive.open(member) as stream:
            script = stream.read().decode("utf-8-sig")
        if script.count(GOAL_GATE_START) != 1 or script.count(GOAL_GATE_END) != 1:
            raise RuntimeError(f"运行时目标门禁标记数量错误：{relative}")
        if script.find(GOAL_GATE_START) > script.find(GOAL_GATE_END):
            raise RuntimeError(f"运行时目标门禁标记顺序错误：{relative}")
        missing = sorted(fragment for fragment in expected_fragments if fragment not in script)
        if missing:
            raise RuntimeError(f"运行时目标门禁缺少冻结值：{relative} | {missing}")
        required_runtime_terms = (
            "$goalGateExpected",
            "$goalGateManifestPath",
            "ConvertFrom-Json",
            "GetEnumerator()",
            "throw",
        )
        if any(term not in script for term in required_runtime_terms):
            raise RuntimeError(f"运行时目标门禁不可执行或不完整：{relative}")
        if script.find(GOAL_GATE_START) > 512:
            raise RuntimeError(f"运行时目标门禁没有位于脚本入口前部：{relative}")


def _require_forbidden_terms_absent(
    archive: zipfile.ZipFile,
    root: str,
    contract: dict[str, Any],
) -> None:
    forbidden = tuple(
        value.lower()
        for value in contract["windows"]["forbidden_name_fragments"]
    )
    for relative in FORMAL_SCRIPTS:
        member = f"{root}/{relative}"
        with archive.open(member) as stream:
            text = stream.read().decode("utf-8-sig").lower()
        for fragment in forbidden:
            if fragment in text:
                raise RuntimeError(
                    f"正式 Windows 脚本包含禁止产品形态：{relative} | {fragment}"
                )


def verify(
    archive_path: Path,
    report_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    contract = _load_json_file(contract_path)
    report = _load_json_file(report_path)
    expected_archive_hash = report.get("package_sha256")
    actual_archive_hash = _sha256(archive_path)
    if expected_archive_hash != actual_archive_hash:
        raise RuntimeError("Windows 构建报告 SHA-256 与 ZIP 不一致。")

    with zipfile.ZipFile(archive_path) as archive:
        infos = _validate_archive_members(archive)
        root = _single_root(infos)
        _require_archive_shape(archive, root, contract)
        manifest = _load_json_member(
            archive,
            f"{root}/release-manifest.json",
        )
        _require_manifest_values(manifest, contract)
        _require_report_values(report, contract)
        product_version = _require_product_version(
            archive_path,
            archive,
            root,
            manifest,
            report,
            contract,
        )
        provenance, workflow_path = _require_native_ci_provenance(
            manifest,
            report,
            contract,
        )
        verified_payload_files = _require_payload_manifest_integrity(
            archive,
            root,
            manifest,
            contract,
        )
        _require_runtime_goal_gates(
            archive,
            root,
            contract,
            provenance,
            workflow_path,
            product_version,
        )
        _require_forbidden_terms_absent(archive, root, contract)

    return {
        "schema_version": "1.0",
        "policy_id": contract["policy_id"],
        "status": "pass",
        "product_version": product_version,
        "archive": str(archive_path.resolve()),
        "archive_sha256": actual_archive_hash,
        "report": str(report_path.resolve()),
        "contract": str(contract_path.resolve()),
        "workflow_path": workflow_path,
        "verified_payload_files": verified_payload_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="独立复验 Windows 正式包未改变 PicotooPet 项目目标。"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = verify(
        args.archive.resolve(),
        args.report.resolve(),
        args.contract.resolve(),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print("PROJECT_GOAL_INTEGRITY=PASS")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
