from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEW_MODEL = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop"
    / "ViewModels"
    / "TaskCenterPageViewModel.cs"
)


def test_observation_finally_clears_task_before_notifying_button_state() -> None:
    source = VIEW_MODEL.read_text(encoding="utf-8-sig")
    method_start = source.index("private async Task ObserveCreatedTaskAsync")
    method_end = source.index("private void ApplySnapshot", method_start)
    method = source[method_start:method_end]
    finally_start = method.index("finally")
    finally_block = method[finally_start:]

    clear_index = finally_block.index("_observationTask = null;")
    notify_index = finally_block.index("RaiseActionProperties();")
    assert clear_index < notify_index


def test_retry_message_distinguishes_new_child_from_existing_active_task() -> None:
    source = VIEW_MODEL.read_text(encoding="utf-8-sig")
    method_start = source.index("public async Task RetrySelectedAsync")
    method_end = source.index("private async Task ObserveCreatedTaskAsync", method_start)
    method = source[method_start:method_end]

    assert "retried.ParentTaskId" in method
    assert "已有活动诊断任务" in method
    assert "已创建重试子任务" in method
