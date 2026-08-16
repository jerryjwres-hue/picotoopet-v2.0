from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK_ROUTES = ROOT / "src/picotoopet_core/api/routes/tasks.py"
TASK_MODELS = ROOT / "src/picotoopet_core/domain/models.py"
WINDOWS_TASKS = (
    ROOT
    / "windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Tasks.cs"
)


def test_task_record_exposes_reversible_visibility_flag() -> None:
    source = TASK_MODELS.read_text(encoding="utf-8")
    assert "is_hidden" in source
    assert "bool" in source


def test_core_exposes_fixed_hide_restore_and_batch_actions() -> None:
    source = TASK_ROUTES.read_text(encoding="utf-8")
    assert '"/tasks/{task_id}/hide"' in source
    assert '"/tasks/{task_id}/restore"' in source
    assert '"/tasks/batch-hide"' in source
    assert '"/tasks/batch-restore"' in source
    assert "physical" not in source.lower()


def test_windows_session_uses_core_visibility_actions() -> None:
    source = WINDOWS_TASKS.read_text(encoding="utf-8")
    assert "HideTasksAsync" in source
    assert "RestoreTasksAsync" in source
