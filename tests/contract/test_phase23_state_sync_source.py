"""Phase 2.3 Desktop 状态同步职责边界测试。"""

from pathlib import Path

ROOT       = Path(__file__).resolve().parents[2]
DESKTOP    = ROOT / "windows" / "desktop" / "src" / "PicotooPet.Desktop"
CORE_STATE = (
    ROOT
    / "windows"
    / "desktop"
    / "src"
    / "PicotooPet.Desktop.Core"
    / "State"
)


def test_main_view_model_is_only_a_state_sync_presentation_adapter() -> None:
    """主 ViewModel 不得继续直接拥有 REST、WebSocket 或旧任务协调器。"""

    view_model = (DESKTOP / "ViewModels" / "MainWindowViewModel.cs").read_text(
        encoding="utf-8"
    )

    assert "StateSyncCoordinator" in view_model
    assert "_syncCoordinator" in view_model
    assert "InitializeSnapshotAsync" in view_model
    assert "RunEventStreamAsync" in view_model
    assert "RefreshAsync" in view_model
    assert "CreateTaskAsync" in view_model
    assert "private MacCoreClient? _client" not in view_model
    assert "private EventStreamClient? _eventStream" not in view_model
    assert "private TaskCoordinator? _taskCoordinator" not in view_model
    assert "_stateStore.Apply(envelope" not in view_model


def test_core_coordinator_owns_auth_filtering_and_gap_recovery() -> None:
    """网络语义必须留在 Core，不得由 WPF 展示层重复实现。"""

    coordinator = (CORE_STATE / "StateSyncCoordinator.cs").read_text(encoding="utf-8")

    assert "catch (EventStreamAuthenticationException" in coordinator
    assert "IsVisibleTask" in coordinator
    assert '"phase2-diagnostic"' in coordinator
    assert "SequenceApplyResult.GapDetected" in coordinator
    assert "ReloadTasksAtSequence" in coordinator
    assert "event_sequence_gap:" in coordinator
