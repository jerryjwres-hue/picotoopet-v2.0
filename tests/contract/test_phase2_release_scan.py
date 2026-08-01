"""Phase 2 发布扫描必须覆盖 Python、C#、WPF 和双击安装入口。"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_release

ROOT = Path(__file__).resolve().parents[2]


def test_release_scanner_covers_phase2_source_types_and_required_files() -> None:
    """发布扫描不得遗漏 Windows 源码或 Phase 2 的关键交付文件。"""

    suffixes = {path.suffix.lower() for path in verify_release._files()}
    assert {".cs", ".xaml", ".csproj", ".sln", ".cmd"} <= suffixes

    report = verify_release.verify()
    assert report["status"] == "pass"
    assert report["release_phase"] == "phase2-slice1"
    assert report["missing_required_files"] == []


def test_release_report_targets_phase2_directory() -> None:
    """当前版本的发布证据必须写入 Phase 2，而不是覆盖历史 Phase 1 报告。"""

    source = (ROOT / "scripts/verify_release.py").read_text(encoding="utf-8")
    assert 'ROOT / "docs" / "phase2" / "RELEASE_VERIFICATION_REPORT.json"' in source
    assert 'ROOT / "docs" / "phase2" / "RELEASE_VERIFICATION_REPORT.md"' in source


def test_release_hash_excludes_its_own_generated_reports() -> None:
    """源码树摘要不得包含发布报告本身，否则每次运行都会改变摘要。"""

    generated = {
        "docs/phase2/RELEASE_VERIFICATION_REPORT.json",
        "docs/phase2/RELEASE_VERIFICATION_REPORT.md",
        "docs/phase2/PHASE2_LOCAL_VERIFICATION_REPORT.json",
        "docs/phase2/PHASE2_LOCAL_VERIFICATION_REPORT.md",
    }
    scanned = {path.relative_to(ROOT).as_posix() for path in verify_release._files()}
    assert generated.isdisjoint(scanned)


def test_release_report_reuses_timestamp_when_source_hash_is_unchanged(tmp_path: Path) -> None:
    """重复验证同一源码树不得仅因当前时间变化而污染 Git 工作区。"""

    output = tmp_path / "report.json"
    output.write_text(
        '{"generated_at":"2026-07-31T00:00:00+00:00","source_tree_sha256":"same"}',
        encoding="utf-8",
    )

    value = verify_release._stable_generated_at(output, "same")

    assert value == "2026-07-31T00:00:00+00:00"
