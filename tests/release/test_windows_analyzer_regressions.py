from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop.Core"
    / "Contracts"
    / "ApiContracts.cs"
)


def test_default_diagnostic_sections_use_one_static_readonly_instance() -> None:
    source = CONTRACTS.read_text(encoding="utf-8-sig")

    assert (
        "private static readonly IReadOnlyList<string> DefaultSections" in source
    )
    assert 'Array.AsReadOnly(["core", "worker", "queue"])' in source

    create_default = source.split(
        "public static DiagnosticSnapshotRequest CreateDefault()",
        1,
    )[1].split("}", 1)[0]
    assert "new[]" not in create_default
    assert "DefaultSections" in create_default
