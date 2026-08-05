from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONTRACT = (
    _REPO_ROOT / "contracts" / "release" / "project-goal-invariants.json"
)
_MARKER = "# PICOTOO_EXECUTABLE_ALLOWLIST_GATE_V1"
_FORMAL_SCRIPTS = (
    "Install-Phase2Prebuilt.ps1",
    "Verify-Phase2Prebuilt.ps1",
)


class ExecutableAllowlistError(RuntimeError):
    """Windows release contains an executable outside the approved surface."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutableAllowlistError(f"无法读取 JSON：{path}") from error
    if not isinstance(payload, dict):
        raise ExecutableAllowlistError(f"JSON 顶层必须是对象：{path}")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _single_root(names: list[str]) -> str:
    roots = {
        name.split("/", 1)[0]
        for name in names
        if name and not name.startswith("/")
    }
    if len(roots) != 1:
        raise ExecutableAllowlistError("Windows 发布 ZIP 必须只有一个顶层目录。")
    return next(iter(roots))


def _allowed_paths(contract_path: Path) -> tuple[str, ...]:
    contract = _load_json(contract_path)
    windows = contract.get("windows")
    if not isinstance(windows, dict):
        raise ExecutableAllowlistError("目标合同缺少 windows 对象。")
    values = windows.get("allowed_payload_executable_paths")
    if not isinstance(values, list) or not values:
        raise ExecutableAllowlistError(
            "目标合同缺少 allowed_payload_executable_paths。"
        )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ExecutableAllowlistError("可执行文件白名单包含非法路径。")
        path = value.replace("\\", "/").strip("/").lower()
        if path.startswith("../") or "/../" in path or not path.endswith(".exe"):
            raise ExecutableAllowlistError(f"可执行文件白名单路径非法：{value}")
        normalized.append(path)
    if len(set(normalized)) != len(normalized):
        raise ExecutableAllowlistError("可执行文件白名单不允许重复。")
    return tuple(sorted(normalized))


def _actual_executables(names: list[str], *, root: str) -> tuple[str, ...]:
    prefix = f"{root}/payload/"
    executables: set[str] = set()
    for name in names:
        if not name.startswith(prefix) or name.endswith("/"):
            continue
        relative = name[len(prefix) :].replace("\\", "/").lower()
        if relative.endswith(".exe"):
            executables.add(relative)
    return tuple(sorted(executables))


def _require_exact_set(
    actual: tuple[str, ...],
    allowed: tuple[str, ...],
) -> None:
    if actual == allowed:
        return
    unapproved = sorted(set(actual) - set(allowed))
    missing = sorted(set(allowed) - set(actual))
    raise ExecutableAllowlistError(
        "GOAL_INTEGRITY_VIOLATION: unapproved executable payload; "
        f"未批准={unapproved!r}, 缺失={missing!r}。"
    )


def _ps_string(value: str) -> str:
    return '"' + value.replace("`", "``").replace('"', '`"') + '"'


def _runtime_block(allowed: tuple[str, ...], *, newline: str) -> str:
    allowed_values = ", ".join(_ps_string(value) for value in allowed)
    lines = [
        f"    {_MARKER}",
        f"    $goalAllowedExecutables = @({allowed_values})",
        "    $goalTrimChars = [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)",
        "    $goalPayloadRootFull = [System.IO.Path]::GetFullPath($payloadRoot).TrimEnd($goalTrimChars)",
        "    $goalPayloadPrefix = $goalPayloadRootFull + [System.IO.Path]::DirectorySeparatorChar",
        "    $goalActualExecutables = @(Get-ChildItem -LiteralPath $payloadRoot -File -Recurse | Where-Object { $_.Extension -ieq '.exe' } | ForEach-Object {",
        "        $goalExecutableFull = [System.IO.Path]::GetFullPath($_.FullName)",
        "        if (-not $goalExecutableFull.StartsWith($goalPayloadPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: executable path escapes payload.\"",
        "        }",
        "        $goalExecutableFull.Substring($goalPayloadPrefix.Length).Replace([System.IO.Path]::DirectorySeparatorChar, [char]'/').Replace([System.IO.Path]::AltDirectorySeparatorChar, [char]'/').ToLowerInvariant()",
        "    } | Sort-Object -Unique)",
        "    if ($goalActualExecutables.Count -ne $goalAllowedExecutables.Count) {",
        "        throw \"GOAL_INTEGRITY_VIOLATION: unapproved executable payload.\"",
        "    }",
        "    foreach ($goalExecutable in $goalAllowedExecutables) {",
        "        if (-not ($goalActualExecutables -contains $goalExecutable)) {",
        "            throw \"GOAL_INTEGRITY_VIOLATION: approved executable is missing: $goalExecutable\"",
        "        }",
        "    }",
    ]
    return newline.join(lines)


def _inject_runtime_gate(
    script_data: bytes,
    *,
    allowed: tuple[str, ...],
    script_name: str,
) -> bytes:
    try:
        script = script_data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ExecutableAllowlistError(
            f"正式脚本不是有效 UTF-8：{script_name}"
        ) from error
    if _MARKER in script:
        return script_data
    anchor = "    $manifest = Read-JsonUtf8 -Path $manifestPath"
    if script.count(anchor) != 1:
        raise ExecutableAllowlistError(
            f"无法在 {script_name} 中唯一定位 manifest 读取边界。"
        )
    newline = "\r\n" if "\r\n" in script else "\n"
    block = _runtime_block(allowed, newline=newline)
    return script.replace(anchor, anchor + newline + block, 1).encode("utf-8-sig")


def _require_runtime_gate(
    archive: zipfile.ZipFile,
    *,
    root: str,
    allowed: tuple[str, ...],
) -> None:
    expected = [
        _MARKER,
        "Get-ChildItem -LiteralPath $payloadRoot -File -Recurse",
        "unapproved executable payload",
        *(_ps_string(value) for value in allowed),
    ]
    for script_name in _FORMAL_SCRIPTS:
        name = f"{root}/{script_name}"
        try:
            script = archive.read(name).decode("utf-8-sig")
        except KeyError as error:
            raise ExecutableAllowlistError(
                f"正式 Windows 包缺少 {script_name}。"
            ) from error
        except UnicodeDecodeError as error:
            raise ExecutableAllowlistError(
                f"{script_name} 不是有效 UTF-8 PowerShell。"
            ) from error
        if script.count(_MARKER) != 1:
            raise ExecutableAllowlistError(
                f"{script_name} executable runtime gate 缺失或重复。"
            )
        missing = [value for value in expected if value not in script]
        if missing:
            raise ExecutableAllowlistError(
                f"{script_name} executable runtime gate 不完整：{missing!r}"
            )


def verify_windows_executable_allowlist(
    package: Path | str,
    *,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    path = Path(package).resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ExecutableAllowlistError("Windows 候选 ZIP 不存在或为空。")
    allowed = _allowed_paths(Path(contract_path))
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise ExecutableAllowlistError("Windows 候选不是有效 ZIP。") from error
    with archive:
        names = archive.namelist()
        root = _single_root(names)
        actual = _actual_executables(names, root=root)
        _require_exact_set(actual, allowed)
        _require_runtime_gate(archive, root=root, allowed=allowed)
    return {
        "schema_version": "1.0",
        "status": "pass",
        "package": path.name,
        "actual_executables": list(actual),
        "allowed_executables": list(allowed),
        "runtime_gate": "pass",
    }


def stamp_windows_executable_allowlist(
    output_root: Path | str,
    *,
    contract_path: Path | str = _DEFAULT_CONTRACT,
) -> dict[str, object]:
    output = Path(output_root).resolve()
    packages = sorted(output.glob("PicotooPet-Phase2-Windows-Prebuilt-*.zip"))
    if len(packages) != 1:
        raise ExecutableAllowlistError(
            f"必须恰好存在一个正式 Windows ZIP，实际为 {len(packages)}。"
        )
    package = packages[0]
    allowed = _allowed_paths(Path(contract_path))

    with zipfile.ZipFile(package, "r") as source:
        infos = source.infolist()
        root = _single_root([info.filename for info in infos])
        actual = _actual_executables([info.filename for info in infos], root=root)
        _require_exact_set(actual, allowed)
        replacements: dict[str, bytes] = {}
        names = {info.filename for info in infos}
        for script_name in _FORMAL_SCRIPTS:
            archive_name = f"{root}/{script_name}"
            if archive_name not in names:
                raise ExecutableAllowlistError(
                    f"正式 Windows 包缺少 {script_name}。"
                )
            replacements[archive_name] = _inject_runtime_gate(
                source.read(archive_name),
                allowed=allowed,
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

    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_name(package.name + ".sha256.txt").write_text(
        f"{digest}  {package.name}\n",
        encoding="utf-8",
    )
    report = verify_windows_executable_allowlist(
        package,
        contract_path=contract_path,
    )
    report["package_sha256"] = digest
    _write_json(output / "windows-executable-allowlist-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("stamp", "verify"), required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--contract", type=Path, default=_DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "stamp":
            if args.output_root is None:
                parser.error("--output-root is required for stamp mode")
            report = stamp_windows_executable_allowlist(
                args.output_root,
                contract_path=args.contract,
            )
        else:
            if args.package is None:
                parser.error("--package is required for verify mode")
            report = verify_windows_executable_allowlist(
                args.package,
                contract_path=args.contract,
            )
            if args.report is not None:
                _write_json(args.report, report)
    except ExecutableAllowlistError as error:
        failure: dict[str, object] = {
            "schema_version": "1.0",
            "status": "fail",
            "error_code": "UNAPPROVED_EXECUTABLE_PAYLOAD",
            "error": str(error),
        }
        if args.report is not None:
            _write_json(args.report, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
