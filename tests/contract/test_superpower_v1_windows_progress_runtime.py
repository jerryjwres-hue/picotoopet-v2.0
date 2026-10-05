"""Superpower v1.0 Windows 任务进度运行时合同。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows" / "desktop" / "src"


def read(relative: str) -> str:
    """读取 Windows Desktop UTF-8 源文件。"""

    return (DESKTOP / relative).read_text(encoding="utf-8-sig")


def test_progress_rest_channel_is_bounded_and_uses_current_pairing() -> None:
    """任务进度旁路必须有界，并继续使用当前 Core 地址与 Credential Manager 令牌。"""

    session = read("PicotooPet.Desktop/Services/ControlCenterSession.TaskProgress.cs")

    assert "MaxTaskProgressResponseBytes" in session
    assert "PooledConnectionLifetime" in session
    assert "ResponseHeadersRead" in session
    assert "_macBaseUrl" in session
    assert "_tokenStore.Read" in session
    assert 'api/v1/tasks/{Uri.EscapeDataString(taskId)}/progress' in session
    assert "MaxTaskProgressResponseBytes" in session


def test_open_task_detail_continuously_refreshes_durable_progress() -> None:
    """详情窗口打开期间必须持续读取 Core 进度，而不是只在 Loaded 时取一次。"""

    view_model = read("PicotooPet.Desktop/ViewModels/TaskDetailViewModel.cs")
    window = read("PicotooPet.Desktop/Views/Pages/TaskDetailWindow.xaml.cs")

    assert "RunProgressLoopAsync" in view_model
    assert "Task.Delay" in view_model
    assert "TimeSpan.FromSeconds(2)" in view_model
    assert "await LoadProgressAsync" in view_model
    assert "RunProgressLoopAsync" in window
    assert "CancellationTokenSource" in window
    assert "OnClosed" in window
    assert ".Cancel();" in window
    assert "Stopwatch" not in view_model
    assert "DateTimeOffset.UtcNow -" not in view_model
