from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
DETAIL_XAML = DESKTOP / "Views" / "Pages" / "TaskDetailWindow.xaml"
DETAIL_VM = DESKTOP / "ViewModels" / "TaskDetailViewModel.cs"


def test_task_detail_shows_task_id_and_safe_failure_summary() -> None:
    xaml = DETAIL_XAML.read_text(encoding="utf-8-sig")
    view_model = DETAIL_VM.read_text(encoding="utf-8-sig")

    assert 'Text="任务 ID"' in xaml
    assert 'Text="{Binding TaskId}"' in xaml
    assert 'Text="状态说明"' in xaml
    assert 'Text="{Binding SafeStatusSummaryText}"' in xaml

    assert "public string SafeStatusSummaryText" in view_model
    assert "SafeStatusSummary(_task)" in view_model
    assert "public string ErrorText" not in view_model
    assert "_task.ErrorMessage" not in view_model


def test_safe_status_summary_uses_stable_status_and_error_code_only() -> None:
    view_model = DETAIL_VM.read_text(encoding="utf-8-sig")

    assert "private static string SafeStatusSummary(TaskRecord task)" in view_model
    assert "task.ErrorCode" in view_model
    assert '"Failed"' in view_model
    assert '"Cancelled"' in view_model
    assert "error_message" not in view_model.lower()
