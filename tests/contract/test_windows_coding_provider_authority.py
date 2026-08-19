from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HANDOFF_SESSION = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "Services"
    / "ControlCenterSession.Handoffs.cs"
)


def test_windows_filters_handoff_templates_to_manual_provider_only() -> None:
    source = HANDOFF_SESSION.read_text(encoding="utf-8-sig")
    compact = "".join(source.split())

    assert "GetHandoffTemplatesAsync" in source
    assert ".Where(" in source
    assert 'template.Provider,"manual",StringComparison.Ordinal' in compact
    assert ".ToArray();" in source
