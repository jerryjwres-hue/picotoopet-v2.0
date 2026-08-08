"""Windows safe diagnostic workflow must match the strict Mac Worker wire contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEW_MODEL = (
    ROOT
    / "windows/desktop/src/PicotooPet.Desktop/ViewModels/AutomationPageViewModel.cs"
)


def test_windows_platform_diagnostic_uses_worker_schema_version_1_0() -> None:
    source = VIEW_MODEL.read_text(encoding="utf-8")
    assert 'Payload: new { schema_version = "1.0" }' in source
    assert 'Payload: new { schema_version = "1.0.0" }' not in source
