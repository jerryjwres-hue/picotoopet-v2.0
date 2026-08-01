using System.Collections.ObjectModel;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>Phase 2 性能纵向切片主视图模型。</summary>
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
    private MacCoreClient? _client;
    private EventStreamClient? _eventStream;
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
            () => !IsBusy && _client is not null && !string.IsNullOrWhiteSpace(TaskType));
        RefreshCommand = new AsyncRelayCommand(
            RefreshAsync,
            HandleError,
            () => !IsBusy && _client is not null);
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
        _stateStore.SetConnection(ConnectionState.Connecting);
        var connectionLifetime = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
        var client = MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
        var stream = new EventStreamClient(baseUri, token, _stateStore.Snapshot.LastSequence);
        _connectionLifetime = connectionLifetime;
        _client             = client;
        _eventStream        = stream;
        client.RequestMeasured += OnRequestMeasured;
        stream.ConnectionStateChanged += OnConnectionStateChanged;
        stream.SocketMeasured += OnSocketMeasured;

        try
        {
            await RefreshCoreAsync(cancellationToken).ConfigureAwait(false);
            _eventTask = RunEventStreamAsync(stream, connectionLifetime.Token);
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
        var client = _client;
        if (client is null)
        {
            return;
        }
        IsBusy = true;
        try
        {
            var healthTask = client.GetHealthAsync(cancellationToken);
            var tasksTask  = client.GetTasksAsync(cancellationToken);
            await Task.WhenAll(healthTask, tasksTask).ConfigureAwait(false);
            _stateStore.ReplaceTasks(await tasksTask.ConfigureAwait(false));
            var health = await healthTask.ConfigureAwait(false);
            await _dispatcher.InvokeAsync(
                () => HealthText = $"{health.Status} · {health.Version ?? "未知版本"}",
                cancellationToken).ConfigureAwait(false);
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
        var client = _client;
        if (client is null)
        {
            return;
        }
        IsBusy = true;
        StatusMessage = "正在提交任务……";
        try
        {
            var coordinator = new TaskCoordinator(client, _stateStore);
            var request = new TaskCreateRequest(
                TaskType.Trim(),
                new Dictionary<string, object?>
                {
                    ["source"] = "windows-desktop-phase2",
                });
            var task = await coordinator.CreateAsync(request, CurrentConnectionToken)
                .ConfigureAwait(false);
            await _dispatcher.InvokeAsync(
                () => StatusMessage = $"任务已入队：{task.TaskId}").ConfigureAwait(false);
        }
        finally
        {
            await _dispatcher.InvokeAsync(() => IsBusy = false).ConfigureAwait(false);
        }
    }

    private async Task RunEventStreamAsync(
        EventStreamClient stream,
        CancellationToken cancellationToken)
    {
        try
        {
            await stream.RunAsync(
                (envelope, _) => new ValueTask(ApplyEventAsync(envelope)),
                cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // 重新配对、退出程序或切换 Mac 地址时取消旧连接属于正常控制流。
        }
        catch (EventStreamAuthenticationException exception)
        {
            _logger.Error("WebSocket 设备认证失败", exception);
            _stateStore.SetConnection(ConnectionState.AuthenticationFailed, exception.Message);
        }
        catch (Exception exception)
        {
            _logger.Error("WebSocket 事件链路异常", exception);
            _stateStore.SetConnection(ConnectionState.Faulted, exception.Message);
        }
    }

    private Task ApplyEventAsync(EventEnvelope envelope)
    {
        _stateStore.Apply(envelope, IsVisibleTask);
        return Task.CompletedTask;
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

    private void OnConnectionStateChanged(object? sender, ConnectionState state) =>
        _stateStore.SetConnection(state);

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
        var eventStream         = _eventStream;
        var client              = _client;

        _connectionLifetime = null;
        _eventTask           = null;
        _eventStream         = null;
        _client              = null;
        connectionLifetime?.Cancel();

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
        if (eventStream is not null)
        {
            eventStream.ConnectionStateChanged -= OnConnectionStateChanged;
            eventStream.SocketMeasured -= OnSocketMeasured;
            await eventStream.DisposeAsync().ConfigureAwait(false);
        }
        if (client is not null)
        {
            client.RequestMeasured -= OnRequestMeasured;
            await client.DisposeAsync().ConfigureAwait(false);
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
