"""Phase 2 Windows Desktop 源码结构与性能约束测试。"""

from __future__ import annotations

from pathlib import Path

ROOT    = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "windows/desktop"


def read(relative: str) -> str:
    """读取 Windows Desktop 源文件。"""

    return (DESKTOP / relative).read_text(encoding="utf-8")


def test_windows_core_targets_current_lts_without_third_party_packages() -> None:
    """核心客户端必须使用 .NET 10 LTS，并保持零第三方运行时依赖。"""

    project = read("src/PicotooPet.Desktop.Core/PicotooPet.Desktop.Core.csproj")
    global_json = read("global.json")

    assert "<TargetFramework>net10.0</TargetFramework>" in project
    assert "<PackageReference" not in project
    assert '"version": "10.0.302"' in global_json


def test_release_builder_resolves_pinned_sdk_from_desktop_root() -> None:
    """发布器无论从哪个目录启动，都必须在 global.json 所在目录解析固定 SDK。"""

    builder = read("scripts/Build-Phase2WindowsRelease.ps1")

    assert '[string]$WorkingDirectory = ""' in builder
    assert "$startInfo.WorkingDirectory = $WorkingDirectory" in builder
    assert (
        'Invoke-NativeCommand -FilePath $dotnet -Arguments @("--version") '
        '-WorkingDirectory $desktopRoot'
    ) in builder
    # SDK 检测、restore/build/run/publish 都必须继承同一 desktopRoot，禁止调用方 CWD 漂移。
    assert builder.count("-WorkingDirectory $desktopRoot") >= 8


def test_network_clients_use_pooling_bounded_channel_and_resume_sequence() -> None:
    """REST 与 WebSocket 客户端必须复用连接、背压并支持断线续传。"""

    rest   = read("src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs")
    stream = read("src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs")

    assert "PooledConnectionLifetime" in rest
    assert "Idempotency-Key" in rest
    assert "X-Picotoo-Trace-Id" in rest
    assert "Channel.CreateBounded" in stream
    assert "BoundedChannelFullMode.Wait" in stream
    assert "after_sequence" in stream
    assert "Task.Delay" in stream
    assert "Thread.Sleep" not in rest + stream
    assert ".Result" not in rest + stream
    assert ".Wait()" not in rest + stream


def test_credential_manager_storage_does_not_persist_plain_token() -> None:
    """设备令牌必须进入 Windows Credential Manager。"""

    token_store = read(
        "src/PicotooPet.Desktop.Core/Security/CredentialManagerTokenStore.cs"
    )

    assert "CredWriteW" in token_store
    assert "CredReadW" in token_store
    assert "CredFree" in token_store
    assert "File.WriteAllText" not in token_store


def test_wpf_task_list_enables_virtualization_and_recycling() -> None:
    """任务列表必须启用 WPF 虚拟化与容器复用。"""

    xaml = read("src/PicotooPet.Desktop/MainWindow.xaml")

    assert 'VirtualizingPanel.IsVirtualizing="True"' in xaml
    assert 'VirtualizingPanel.VirtualizationMode="Recycling"' in xaml
    assert 'ScrollViewer.CanContentScroll="True"' in xaml


def test_csharp_sources_have_chinese_comments_and_no_obvious_sync_over_async() -> None:
    """C# 文件必须包含中文说明，并禁止明显同步阻塞异步调用。"""

    import re

    sources = list((DESKTOP / "src").rglob("*.cs"))
    assert len(sources) >= 12
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "///" in text or "//" in text, source
        assert re.search(r"\.Result\b", text) is None, source
        assert ".Wait()" not in text, source
        assert "Thread.Sleep" not in text, source


def test_diagnostic_tasks_do_not_clutter_the_user_task_list() -> None:
    """高样本性能验收任务应保留耐久记录，但默认不占满用户界面。"""

    diagnostics = read("tools/PicotooPet.Desktop.Diagnostics/Program.cs")
    view_model  = read("src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs")

    assert 'ResourceTag: "phase2-diagnostic"' in diagnostics
    assert "IsVisibleTask" in view_model
    assert "task.ResourceTag" in view_model
    assert '"phase2-diagnostic"' in view_model


def test_windows_source_guards_connection_lifecycle_and_ui_incremental_updates() -> None:
    """重连必须取消旧事件流，任务事件必须增量更新而不是重建整张列表。"""

    view_model = read("src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs")
    row_model  = read("src/PicotooPet.Desktop/ViewModels/TaskRowViewModel.cs")

    assert "_connectionLifetime" in view_model
    assert "CancelConnectionAsync" in view_model
    assert "await eventTask.ConfigureAwait(false)" in view_model
    assert "Tasks.Clear()" not in view_model
    assert "ApplyTaskDiff" in view_model
    assert "UpdateFrom" in row_model


def test_state_events_are_published_outside_the_state_lock() -> None:
    """状态订阅器不得在仓库锁内执行，避免重入和 UI 调度拖慢写入。"""

    state_store = read("src/PicotooPet.Desktop.Core/State/AppStateStore.cs")

    assert "PublishSnapshotLocked" not in state_store
    assert "SnapshotChanged?.Invoke(this, snapshot);" in state_store
    assert "PublishSnapshot(snapshot);" in state_store


def test_native_interop_and_websocket_cleanup_are_compile_safe() -> None:
    """Credential Manager 清零与 WebSocket 收发应使用明确命名空间和安全清理结构。"""

    token_store = read(
        "src/PicotooPet.Desktop.Core/Security/CredentialManagerTokenStore.cs"
    )
    stream = read("src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs")

    assert "using System.Security.Cryptography;" in token_store
    assert "new ArraySegment<byte>(payload)" in stream
    assert "finally\n        {\n            linked.Cancel();" in stream
    assert "_pendingPings.Clear();" in stream


def test_websocket_detects_half_open_connections_without_false_disconnects() -> None:
    """业务入站必须视作存活；只有持续无入站才允许 Pong 超时触发重连。"""

    stream = read("src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs")

    assert "_pongTimeout" in stream
    assert "_pingInterval" in stream
    assert "ThrowIfPongExpired" in stream
    assert "RecordInboundActivity" in stream
    assert "Stopwatch.GetElapsedTime" in stream
    assert "TimeSpan.FromSeconds(30)" in stream
    assert "TimeSpan.FromSeconds(10)" in stream
    assert "KeepAliveInterval = TimeSpan.FromSeconds(30)" in stream


def test_network_failures_remain_traceable_and_auth_state_is_not_overwritten() -> None:
    """网络失败也必须产生 Trace 延迟样本，WebSocket 认证失败不得被覆盖成普通故障。"""

    rest       = read("src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs")
    stream     = read("src/PicotooPet.Desktop.Core/Networking/EventStreamClient.cs")
    view_model = read("src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs")

    assert "NETWORK_ERROR" in rest
    assert "ReadErrorAsync" in rest
    assert "RecordMeasurement" in rest
    assert "EventStreamAuthenticationException" in stream
    assert "catch (EventStreamAuthenticationException" in view_model


def test_ui_path_has_no_synchronous_log_file_writes_or_unobserved_initialization() -> None:
    """日志写盘不得阻塞 UI，启动初始化任务必须自行捕获异常。"""

    logger = read("src/PicotooPet.Desktop.Core/Logging/SafeFileLogger.cs")
    app    = read("src/PicotooPet.Desktop/App.xaml.cs")

    assert "File.AppendAllText" not in logger
    assert "WriteLineAsync" in logger
    assert "IAsyncDisposable" in logger
    assert "InitializeViewModelAsync" in app
    assert "catch (Exception exception)" in app


def test_windows_project_xml_and_source_delimiters_are_well_formed() -> None:
    """在无 .NET SDK 的构建环境中先执行确定性的 XML 与分隔符静态校验。"""

    import re
    import xml.etree.ElementTree as ET

    for relative in [
        "Directory.Build.props",
        "src/PicotooPet.Desktop.Core/PicotooPet.Desktop.Core.csproj",
        "src/PicotooPet.Desktop/PicotooPet.Desktop.csproj",
        "src/PicotooPet.Desktop/App.xaml",
        "src/PicotooPet.Desktop/MainWindow.xaml",
    ]:
        ET.fromstring(read(relative))

    string_or_comment = re.compile(
        r'@"(?:[^"]|"")*"|"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
        re.DOTALL,
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    for source in (DESKTOP / "src").rglob("*.cs"):
        cleaned = string_or_comment.sub("", source.read_text(encoding="utf-8"))
        stack: list[str] = []
        for character in cleaned:
            if character in pairs:
                stack.append(character)
            elif character in pairs.values():
                assert stack, f"{source}: 多余的 {character}"
                opening = stack.pop()
                assert pairs[opening] == character, source
        assert not stack, f"{source}: 未闭合 {stack}"


def test_phase2_windows_source_contains_no_placeholders() -> None:
    """交付源码不得保留会掩盖未实现功能的占位标记。"""

    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (DESKTOP / "src").rglob("*")
        if path.is_file() and path.suffix in {".cs", ".xaml", ".csproj"}
    )
    for marker in ("TODO", "TBD", "NotImplementedException"):
        assert marker not in combined


def test_desktop_enforces_single_instance_to_avoid_duplicate_event_consumers() -> None:
    """重复启动不得产生两个 WebSocket 消费者和两个状态写入者。"""

    app = read("src/PicotooPet.Desktop/App.xaml.cs")
    assert "Local\\PicotooPetV2.Desktop.SingleInstance" in app
    assert "new Mutex" in app
    assert "createdNew" in app
    assert "ReleaseMutex" in app


def test_desktop_filters_diagnostic_tasks_before_state_storage_and_rest_transfer() -> None:
    """诊断任务必须在 REST 与 Core 事件归并两处过滤，WPF 不再消费原始事件。"""

    view_model = read("src/PicotooPet.Desktop/ViewModels/MainWindowViewModel.cs")
    client = read("src/PicotooPet.Desktop.Core/Networking/MacCoreClient.cs")
    coordinator = read("src/PicotooPet.Desktop.Core/State/StateSyncCoordinator.cs")
    task_state = read("src/PicotooPet.Desktop.Core/State/TaskStateStore.cs")

    assert "exclude_resource_tag=phase2-diagnostic" in client
    assert "_taskStore.Apply(envelope, IsVisibleTask)" in coordinator
    assert "task.ResourceTag" in coordinator
    assert '"phase2-diagnostic"' in coordinator
    assert "Predicate<TaskRecord>? includeTask" in task_state
    assert "_stateStore.Apply(envelope" not in view_model


def test_task_detail_projects_durable_core_progress_without_fake_percent() -> None:
    """任务详情必须读取 Core 的耐久进度，不得用本地耗时猜测百分比。"""

    contracts = read("src/PicotooPet.Desktop.Core/Contracts/TaskProgressContracts.cs")
    session = read("src/PicotooPet.Desktop/Services/ControlCenterSession.TaskProgress.cs")
    view_model = read("src/PicotooPet.Desktop/ViewModels/TaskDetailViewModel.cs")
    xaml = read("src/PicotooPet.Desktop/Views/Pages/TaskDetailWindow.xaml")

    assert "TaskProgressSnapshot" in contracts
    assert "TaskProgressEvent" in contracts
    assert "GetTaskProgressAsync" in session
    assert "api/v1/tasks/{Uri.EscapeDataString(taskId)}/progress" in session
    assert "ProgressStageText" in view_model
    assert "ProgressValueText" in view_model
    assert "RecentActivityText" in view_model
    assert "Stopwatch" not in view_model
    assert "DateTimeOffset.UtcNow -" not in view_model
    assert 'Text="{Binding ProgressStageText}"' in xaml
    assert 'Text="{Binding ProgressValueText}"' in xaml
    assert 'Text="{Binding RecentActivityText}"' in xaml
