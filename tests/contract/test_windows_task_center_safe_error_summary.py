import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
TASK_CENTER = DESKTOP / "Views" / "Pages" / "TaskCenterPage.xaml"
TASK_ROW = DESKTOP / "ViewModels" / "TaskRowViewModel.cs"


def test_task_center_never_binds_raw_core_error_message() -> None:
    xaml = TASK_CENTER.read_text(encoding="utf-8-sig")
    view_model = TASK_ROW.read_text(encoding="utf-8-sig")

    assert 'Text="{Binding SafeErrorSummary, Mode=OneWay}"' in xaml
    assert 'Text="{Binding Error, Mode=OneWay}"' not in xaml
    assert "public string SafeErrorSummary" in view_model
    assert "task.ErrorMessage" not in view_model
    assert re.search(r"public\s+string\?\s+Error\s*\{", view_model) is None


def test_task_center_safe_error_summary_uses_status_and_error_code() -> None:
    view_model = TASK_ROW.read_text(encoding="utf-8-sig")

    assert "FormatSafeErrorSummary(task.Status, task.ErrorCode)" in view_model
    assert "private static string FormatSafeErrorSummary(" in view_model
    assert '"Failed"' in view_model
    assert '"Cancelled"' in view_model
