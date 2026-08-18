from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
PROJECTION = DESKTOP / "ViewModels" / "OperatorProjection.cs"


def test_simple_mode_task_cards_never_copy_raw_core_error_message() -> None:
    source = PROJECTION.read_text(encoding="utf-8-sig")

    assert "task.ErrorMessage" not in source
    assert "FormatSafeErrorSummary(task.Status, task.ErrorCode)" in source
    assert "private static string? FormatSafeErrorSummary(" in source


def test_simple_mode_safe_error_summary_uses_stable_status_and_error_code() -> None:
    source = PROJECTION.read_text(encoding="utf-8-sig")

    assert 'status == "Failed"' in source
    assert 'status == "Cancelled"' in source
    assert "errorCode" in source
