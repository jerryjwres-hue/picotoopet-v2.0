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


def _rewrite_manifest(
    package: Path,
    required_values: dict[str, Any],
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
        encoded = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

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
                    data = (
                        encoded
                        if info.filename == manifest_name
                        else source.read(info.filename)
                    )
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

    package = _single_package(output)
    manifest = _rewrite_manifest(package, required)
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
