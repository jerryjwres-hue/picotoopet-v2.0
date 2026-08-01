"""不依赖外部服务的发布结构、秘密和清单验证。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
    "artifacts",
    "bin",
    "obj",
}
SECRET_PATTERNS = {
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
GENERATED_REPORTS = {
    "docs/phase2/RELEASE_VERIFICATION_REPORT.json",
    "docs/phase2/RELEASE_VERIFICATION_REPORT.md",
    "docs/phase2/PHASE2_LOCAL_VERIFICATION_REPORT.json",
    "docs/phase2/PHASE2_LOCAL_VERIFICATION_REPORT.md",
}


def _files() -> list[Path]:
    """列出需要扫描的文本和契约文件。"""

    allowed = {
        ".cmd",
        ".command",
        ".cs",
        ".csproj",
        ".json",
        ".md",
        ".plist",
        ".ps1",
        ".py",
        ".sln",
        ".toml",
        ".txt",
        ".vbs",
        ".xaml",
    }
    return sorted(
        (
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.suffix.lower() in allowed
            and path.relative_to(ROOT).as_posix() not in GENERATED_REPORTS
            and not any(
                part in EXCLUDED_PARTS
                for part in path.relative_to(ROOT).parts
            )
        ),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def verify() -> dict[str, object]:
    """执行模型哈希格式、契约存在和秘密扫描。"""

    model_manifest = json.loads(
        (ROOT / "windows" / "bootstrap" / "model_manifest.json").read_text(encoding="utf-8")
    )
    malformed_hashes = [
        model["filename"]
        for model in model_manifest["models"]
        if not re.fullmatch(r"[0-9a-f]{64}", model["sha256"])
    ]
    findings: list[dict[str, str]] = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"type": name, "file": path.relative_to(ROOT).as_posix()})

    required = [
        ROOT / "contracts" / "openapi" / "mac_core_v1.openapi.json",
        ROOT / "contracts" / "mcp" / "tools_v1.json",
        ROOT / "contracts" / "schemas" / "event_envelope_v2.schema.json",
        ROOT / "contracts" / "schemas" / "performance_report_v2.schema.json",
        ROOT / "inventory" / "source_manifest.json",
        ROOT / "docs" / "phase0" / "PHASE_0_VERIFICATION_REPORT.md",
        ROOT / "docs" / "phase1" / "IMPLEMENTATION_STATUS.md",
        ROOT / "docs" / "phase2" / "INSTALLATION_GUIDE_CN.md",
        ROOT / "docs" / "phase2" / "PERFORMANCE_SLO_CN.md",
        ROOT / "docs" / "phase2" / "REAL_MACHINE_ACCEPTANCE_CN.md",
        ROOT / "docs" / "phase2" / "PHASE2_VERTICAL_SLICE_STATUS.md",
        ROOT / "windows" / "desktop" / "scripts" / "INSTALL_PHASE2_WINDOWS.vbs",
        ROOT / "windows" / "desktop" / "scripts" / "VERIFY_PHASE2_WINDOWS.vbs",
        ROOT / "windows" / "desktop" / "scripts" / "ROLLBACK_PHASE2_WINDOWS.vbs",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    scanned_files = _files()
    digest = hashlib.sha256()
    for path in scanned_files:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative + b"\0" + hashlib.sha256(path.read_bytes()).digest())

    powershell_bom_failures = [
        path.relative_to(ROOT).as_posix()
        for path in scanned_files
        if path.suffix.lower() == ".ps1" and not path.read_bytes().startswith(b"\xef\xbb\xbf")
    ]
    status = (
        "pass"
        if not malformed_hashes
        and not findings
        and not missing
        and not powershell_bom_failures
        else "fail"
    )
    return {
        "schema_version": "2.2.0",
        "release_phase": "phase2-slice1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "scanned_files": len(scanned_files),
        "source_tree_sha256": digest.hexdigest(),
        "model_count": len(model_manifest["models"]),
        "malformed_model_hashes": malformed_hashes,
        "powershell_bom_failures": powershell_bom_failures,
        "secret_findings": findings,
        "missing_required_files": missing,
    }



def _stable_generated_at(output: Path, source_hash: str) -> str:
    """同一源码摘要复用原报告时间，保证重复验证不会制造无意义差异。"""

    if output.is_file():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
            if (
                existing.get("source_tree_sha256") == source_hash
                and isinstance(existing.get("generated_at"), str)
            ):
                return existing["generated_at"]
        except (OSError, json.JSONDecodeError):
            # 损坏报告直接重建；源码和清单仍由本次扫描决定。
            pass
    return datetime.now(UTC).isoformat()

def main() -> int:
    """写入 JSON/Markdown 验证报告并返回退出码。"""

    report = verify()
    output = ROOT / "docs" / "phase2" / "RELEASE_VERIFICATION_REPORT.json"
    report["generated_at"] = _stable_generated_at(
        output,
        str(report["source_tree_sha256"]),
    )
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    markdown = ROOT / "docs" / "phase2" / "RELEASE_VERIFICATION_REPORT.md"
    markdown.write_text(
        "# 发布验证报告\n\n"
        f"- 状态：`{report['status']}`\n"
        f"- 扫描文件：{report['scanned_files']}\n"
        f"- 发布阶段：`{report['release_phase']}`\n"
        f"- 固定模型：{report['model_count']}\n"
        f"- 源码树 SHA-256：`{report['source_tree_sha256']}`\n"
        f"- PowerShell BOM 失败：{len(report['powershell_bom_failures'])}\n"
        f"- 秘密发现：{len(report['secret_findings'])}\n"
        f"- 缺失文件：{len(report['missing_required_files'])}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
