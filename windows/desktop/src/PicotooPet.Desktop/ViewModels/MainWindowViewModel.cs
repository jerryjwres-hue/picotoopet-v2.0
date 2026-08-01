using System.Collections.ObjectModel;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 2 兼容展示适配器；网络和状态同步由 Core 协调器负责。</summary>
public sealed class MainWindowViewModel : ObservableObject, IAsyncDisposable
{
    private readonly ITokenStore _tokenStore;
    private readonly DesktopSettingsStore _settingsStore;
    private readonly IUiDispatcher _dispatcher;
    private readonly SafeFileLogger _logger;
    private readonly AppStateStore _stateStore = new();
    private readonly LatencyRecorder _restLatency = new();
    private readonly LatencyRecorder _socketLatency = new();
    private readonly Dictionary<string, TaskRowViewModel> _taskRowsById = new(StringComparer.Ordinal);
    private readonly CancellationTokenSource _lifetime = new();
    private CancellationTokenSource? _connectionLifetime;
    private StateSyncCoordinator? _syncCoordinator;
    private Task? _eventTask;
    private string _connectionText = "离线";
    private string _healthText = "尚未连接";
    private string _latencyText = "等待样本";
    private string _taskType = "analysis";
    private string _macBaseUrl = DesktopSettings.Default.MacBaseUrl;
    private string _statusMessage = "请先保存 Mac 地址和设备令牌。";
    private bool _isBusy;

    /// <summary>创建组合依赖并注册状态事件。</summary>
    public MainWindowViewModel(
        ITokenStore tokenStore,
        DesktopSettingsStore settingsStore,
        IUiDispatcher dispatcher,
        SafeFileLogger logger)
    {
        _tokenStore    = tokenStore;
        _settingsStore = settingsStore;
        _dispatcher    = dispatcher;
        _logger        = logger;
        _stateStore.SnapshotChanged += OnSnapshotChanged;
        SubmitTaskCommand = new AsyncRelayCommand(
            SubmitTaskAsync,
            HandleError,
            () => !IsBusy
                && _syncCoordinator is not null
                && !string.IsNullOrWhiteSpace(TaskType));
        RefreshCommand = new AsyncRelayCommand(
            RefreshAsync,
            HandleError,
            () => !IsBusy && _syncCoordinator is not null);
    }

    public ObservableCollection<TaskRowViewModel> Tasks { get; } = new();
    public AsyncRelayCommand SubmitTaskCommand { get; }
    public AsyncRelayCommand RefreshCommand { get; }

    public string ConnectionText
    {
        get => _connectionText;
        private set => SetProperty(ref _connectionText, value);
    }

    public string HealthText
    {
        get => _healthText;
        private set => SetProperty(ref _healthText, value);
    }

    public string LatencyText
    {
        get => _latencyText;
        private set => SetProperty(ref _latencyText, value);
    }

    public string TaskType
    {
        get => _taskType;
        set
        {
            if (SetProperty(ref _taskType, value))
            {
                SubmitTaskCommand.NotifyCanExecuteChanged();
            }
        }
    }

    public string MacBaseUrl
    {
        get => _macBaseUrl;
        set => SetProperty(ref _macBaseUrl, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                SubmitTaskCommand.NotifyCanExecuteChanged();
                RefreshCommand.NotifyCanExecuteChanged();
            }
        }
    }

    /// <summary>读取非敏感设置并在已有令牌时自动连接。</summary>
    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        var settings = await _settingsStore.LoadAsync(cancellationToken);
        MacBaseUrl = settings.MacBaseUrl;
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            ConnectionText = "未配对";
            return;
        }
        await ConnectAsync(token, cancellationToken);
    }

    /// <summary>验证地址与令牌后保存；Token 只进入 Credential Manager。</summary>
    public async Task SaveAndConnectAsync(string token, CancellationToken cancellationToken)
    {
        await ConnectAsync(token, cancellationToken);
        _tokenStore.Save(token);
        await _settingsStore.SaveAsync(new DesktopSettings(MacBaseUrl), cancellationToken);
    }

    private async Task ConnectAsync(string token, CancellationToken cancellationToken)
    {
        if (!Uri.TryCreate(MacBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("Mac 地址格式无效。");
        }
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }

        await CancelConnectionAsync().ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();

        var connectionLifetime = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
        var client = MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
        var coordinator = new StateSyncCoordinator(
            client,
            _stateStore.ConnectionStore,
            _stateStore.CapabilityStore,
            _stateStore.TaskStore,
            sequence => new EventStreamClient(baseUri, token, sequence));
        _connectionLifetime = connectionLifetime;
        _syncCoordinator    = coordinator;
        coordinator.RequestMeasured += OnRequestMeasured;
        coordinator.SocketMeasured  += OnSocketMeasured;
        coordinator.HealthChanged   += OnHealthChanged;
        coordinator.DiagnosticRaised += OnDiagnosticRaised;
        SubmitTaskCommand.NotifyCanExecuteChanged();
        RefreshCommand.NotifyCanExecuteChanged();

        try
        {
            await coordinator.InitializeSnapshotAsync(cancellationToken).ConfigureAwait(false);
            _eventTask = RunCoordinatorEventStreamAsync(
                coordinator,
                connectionLifetime.Token);
            await _dispatcher.InvokeAsync(
                () => StatusMessage = "双机控制链已连接。",
                cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            await CancelConnectionAsync().ConfigureAwait(false);
            throw;
        }
    }

    private Task RefreshAsync() => RefreshCoreAsync(CurrentConnectionToken);

    private async Task RefreshCoreAsync(CancellationToken cancellationToken)
    {
        var coordinator = _syncCoordinator;
        if (coordinator is null)
        {
            return;
        }
        IsBusy = true;
        try
        {
            var health = await coordinator.RefreshAsync(cancellationToken).ConfigureAwait(false);
            await UpdateHealthTextAsync(health, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            await _dispatcher.InvokeAsync(
                () => IsBusy = false,
                CancellationToken.None).ConfigureAwait(false);
        }
    }

    private async Task SubmitTaskAsync()
    {
        var coordinator = _syncCoordinator;
        if (coordinator is null)
        {
            return;
        }
        IsBusy = true;
        StatusMessage = "正在提交任务……";
        try
        {
            var request = new TaskCreateRequest(
                TaskType.Trim(),
                new Dictionary<string, object?>
                {
                    ["source"] = "windows-desktop-phase2",
                });
            var task = await coordinator.CreateTaskAsync(request, CurrentConnectionToken)
                .ConfigureAwait(false);
            await _dispatcher.InvokeAsync(
                () => StatusMessage = $"任务已入队：{task.TaskId}").ConfigureAwait(false);
        }
        finally
        {
            await _dispatcher.InvokeAsync(() => IsBusy = false).ConfigureAwait(false);
        }
    }

    private async Task RunCoordinatorEventStreamAsync(
        StateSyncCoordinator coordinator,
        CancellationToken cancellationToken)
    {
        try
        {
            await coordinator.RunEventStreamAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // 重新配对、退出程序或切换 Mac 地址时取消旧连接属于正常控制流。
        }
        catch (EventStreamAuthenticationException exception)
        {
            // 协调器已经提交 AuthenticationFailed；展示层只记录脱敏诊断。
            _logger.Error("WebSocket 设备认证失败", exception);
        }
        catch (Exception exception)
        {
            // 协调器已经提交 Faulted；展示层不重复修改网络状态。
            _logger.Error("WebSocket 事件链路异常", exception);
        }
    }

    private void OnRequestMeasured(object? sender, RequestMeasurement measurement)
    {
        _restLatency.Add(measurement.DurationMilliseconds);
        _ = UpdateLatencyTextAsync();
    }

    private void OnSocketMeasured(object? sender, SocketMeasurement measurement)
    {
        _socketLatency.Add(measurement.DurationMilliseconds);
        _ = UpdateLatencyTextAsync();
    }

    private Task UpdateLatencyTextAsync() => _dispatcher.InvokeAsync(() =>
    {
        var rest   = _restLatency.Snapshot();
        var socket = _socketLatency.Snapshot();
        LatencyText = $"REST p95 {rest.P95Milliseconds:F1} ms · WS p95 {socket.P95Milliseconds:F1} ms";
    });

    private void OnHealthChanged(object? sender, HealthResponse health) =>
        _ = UpdateHealthTextAsync(health, CancellationToken.None);

    private Task UpdateHealthTextAsync(
        HealthResponse health,
        CancellationToken cancellationToken) =>
        _dispatcher.InvokeAsync(
            () => HealthText = $"{health.Status} · {health.Version ?? "未知版本"}",
            cancellationToken);

    private void OnDiagnosticRaised(object? sender, string diagnostic) =>
        _logger.Info($"状态同步诊断：{diagnostic}");

    private void OnSnapshotChanged(object? sender, AppSnapshot snapshot)
    {
        _ = _dispatcher.InvokeAsync(() =>
        {
            ConnectionText = snapshot.ConnectionState switch
            {
                ConnectionState.Online               => "在线",
                ConnectionState.Connecting           => "连接中",
                ConnectionState.Reconnecting         => "正在重连",
                ConnectionState.AuthenticationFailed => "认证失败",
                ConnectionState.Faulted              => "连接故障",
                _                                    => "离线",
            };
            ApplyTaskDiff(snapshot);
        });
    }

    /// <summary>根据状态仓库的变化提示增量更新虚拟化列表。</summary>
    private void ApplyTaskDiff(AppSnapshot snapshot)
    {
        if (snapshot.ChangedTask is not null)
        {
            if (IsVisibleTask(snapshot.ChangedTask))
            {
                UpsertTaskRow(snapshot.ChangedTask);
            }
            return;
        }
        if (!snapshot.TaskReset)
        {
            return;
        }

        var visibleTasks = snapshot.Tasks.Where(IsVisibleTask).ToArray();
        var expectedIds = visibleTasks
            .Select(task => task.TaskId)
            .ToHashSet(StringComparer.Ordinal);
        for (var index = Tasks.Count - 1; index >= 0; index--)
        {
            var row = Tasks[index];
            if (expectedIds.Contains(row.TaskId))
            {
                continue;
            }
            Tasks.RemoveAt(index);
            _taskRowsById.Remove(row.TaskId);
        }

        for (var index = 0; index < visibleTasks.Length; index++)
        {
            var task = visibleTasks[index];
            if (!_taskRowsById.TryGetValue(task.TaskId, out var row))
            {
                row = TaskRowViewModel.FromRecord(task);
                _taskRowsById[task.TaskId] = row;
                Tasks.Insert(Math.Min(index, Tasks.Count), row);
                continue;
            }
            row.UpdateFrom(task);
            var currentIndex = Tasks.IndexOf(row);
            if (currentIndex >= 0 && currentIndex != index)
            {
                Tasks.Move(currentIndex, index);
            }
        }
    }

    private static bool IsVisibleTask(TaskRecord task) =>
        !string.Equals(
            task.ResourceTag,
            "phase2-diagnostic",
            StringComparison.Ordinal);

    private void UpsertTaskRow(TaskRecord task)
    {
        if (_taskRowsById.TryGetValue(task.TaskId, out var row))
        {
            row.UpdateFrom(task);
            return;
        }
        row = TaskRowViewModel.FromRecord(task);
        _taskRowsById[task.TaskId] = row;
        Tasks.Insert(0, row);
    }

    private void HandleError(Exception exception)
    {
        _logger.Error("桌面操作失败", exception);
        StatusMessage = exception is ApiException apiException
            ? $"{apiException.Code}：{apiException.Message}（Trace: {apiException.TraceId ?? "无"}）"
            : $"操作失败：{exception.Message}";
    }

    private CancellationToken CurrentConnectionToken =>
        _connectionLifetime?.Token ?? _lifetime.Token;

    /// <summary>取消并等待旧事件流，确保重连时不存在两个并发消费者。</summary>
    private async Task CancelConnectionAsync()
    {
        var connectionLifetime = _connectionLifetime;
        var eventTask           = _eventTask;
        var coordinator         = _syncCoordinator;

        _connectionLifetime = null;
        _eventTask           = null;
        _syncCoordinator     = null;
        connectionLifetime?.Cancel();
        SubmitTaskCommand.NotifyCanExecuteChanged();
        RefreshCommand.NotifyCanExecuteChanged();

        if (coordinator is not null)
        {
            try
            {
                await coordinator.StopAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                _logger.Error("停止旧状态同步链路失败", exception);
            }
        }
        if (eventTask is not null)
        {
            try
            {
                await eventTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // 旧连接已按设计取消。
            }
        }
        if (coordinator is not null)
        {
            coordinator.RequestMeasured -= OnRequestMeasured;
            coordinator.SocketMeasured  -= OnSocketMeasured;
            coordinator.HealthChanged   -= OnHealthChanged;
            coordinator.DiagnosticRaised -= OnDiagnosticRaised;
            await coordinator.DisposeAsync().ConfigureAwait(false);
        }
        connectionLifetime?.Dispose();
        _stateStore.SetConnection(ConnectionState.Offline);
    }

    /// <summary>关闭应用时取消后台链路并释放连接池。</summary>
    public async ValueTask DisposeAsync()
    {
        _lifetime.Cancel();
        await CancelConnectionAsync().ConfigureAwait(false);
        _stateStore.SnapshotChanged -= OnSnapshotChanged;
        _lifetime.Dispose();
        await _logger.DisposeAsync().ConfigureAwait(false);
    }
}
