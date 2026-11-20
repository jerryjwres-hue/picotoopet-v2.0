using System.Collections.ObjectModel;
using System.Text.Json;
using System.IO;
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
    private readonly WorkerProcessManager _workerManager;
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
    private string _mobilePairingText = "手机入口默认关闭，请先配置 HTTPS 并启用移动端。";
    private string _storyPackInput = "";
    private string _storyPackPreviewText = "粘贴完整的 StoryPack JSON 后点击验证；不会执行生成。";
    private string? _lastPreviewEpisodeId;
    private string? _lastStoryReviewSha;
    private Dictionary<string, string>? _lastShotInputSha;
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
        // 程序安装目录内的唯一 GPU Bridge；关闭 Studio 不杀掉在途旧 Journal。
        var appRoot = AppContext.BaseDirectory;
        var localRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PicotooPetV2", "Desktop");
        _workerManager = new WorkerProcessManager(
            Path.Combine(appRoot, "tools", "worker",
                "PicotooPet.Worker", "PicotooPet.Worker.exe"),
            Path.Combine(localRoot, "worker_launch.toml"));
        var workerKeyStore = new CredentialManagerTokenStore("PicotooPetV3/WorkerAttestationKey");
        Production = new ProductionViewModel(
            () => _client, () => CurrentConnectionToken, settingsStore,
            _workerManager, workerKeyStore, () => MacBaseUrl, () => _tokenStore.Read());
        _stateStore.SnapshotChanged += OnSnapshotChanged;
        SubmitTaskCommand = new AsyncRelayCommand(
            SubmitTaskAsync,
            HandleError,
            () => !IsBusy && _client is not null && !string.IsNullOrWhiteSpace(TaskType));
        RefreshCommand = new AsyncRelayCommand(
            RefreshAsync,
            HandleError,
            () => !IsBusy && _client is not null);
        PairMobileCommand = new AsyncRelayCommand(
            PairMobileAsync,
            HandleError,
            () => true);
        PreviewStoryPackCommand = new AsyncRelayCommand(
            PreviewStoryPackAsync,
            HandleError,
            () => !string.IsNullOrWhiteSpace(StoryPackInput));
    }

    public ObservableCollection<TaskRowViewModel> Tasks { get; } = new();
    public AsyncRelayCommand SubmitTaskCommand { get; }
    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand PreviewStoryPackCommand { get; }
    public AsyncRelayCommand PairMobileCommand { get; }
    public ProductionViewModel Production { get; }

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

    /// <summary>创作台中粘贴的 JSON；只有预览命令使用，不保存到本地设置。</summary>
    public string MobilePairingText
    {
        get => _mobilePairingText;
        private set => SetProperty(ref _mobilePairingText, value);
    }

    public string StoryPackInput
    {
        get => _storyPackInput;
        set
        {
            if (SetProperty(ref _storyPackInput, value))
            {
                PreviewStoryPackCommand.NotifyCanExecuteChanged();
            }
        }
    }

    public string StoryPackPreviewText
    {
        get => _storyPackPreviewText;
        private set => SetProperty(ref _storyPackPreviewText, value);
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
        Production.SetWorkerProjectRoot(settings.WindowsProjectRoot);
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            ConnectionText = "未配对";
            return;
        }
        try
        {
            await ConnectAsync(token, cancellationToken);
        }
        finally
        {
            // Mac 暂时离线也允许已配对 Worker 自己重试，不要求用户重启脚本。
            // 仍须用户此前显式选择自动启动，并有有效的 HTTPS 与独立密钥。
            await Production.TryAutoStartWorkerAsync(settings);
        }
    }

    /// <summary>验证地址与令牌后保存；Token 只进入 Credential Manager。</summary>
    public async Task SaveAndConnectAsync(string token, CancellationToken cancellationToken)
    {
        await ConnectAsync(token, cancellationToken);
        _tokenStore.Save(token);
        // 重新配对 Mac 时必须保留已有 Windows 视频项目目录，不要求重复选择。
        var existing = await _settingsStore.LoadAsync(cancellationToken);
        await _settingsStore.SaveAsync(
            existing with { MacBaseUrl = MacBaseUrl }, cancellationToken);
        if (existing.WorkerAutoStart)
            await Production.TryAutoStartWorkerAsync(existing);
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
                () =>
                {
                    StatusMessage = "双机控制链已连接。";
                    Production.ConnectionChanged();
                },
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

    /// <summary>只读预览故事包：设备没有得到任何 GPU/发布许可。</summary>
    /// <summary>只显示一次性手机配对码；不得写入日志或 Credential Manager。</summary>
    private async Task PairMobileAsync()
    {
        if (_client is null)
        {
            MobilePairingText = "请先连接 Mac Core。";
            return;
        }

        try
        {
            var response = await _client.IssueMobilePairingAsync(CurrentConnectionToken);
            if (!response.GetProperty("enabled").GetBoolean())
            {
                MobilePairingText = "Mac Core 尚未启用手机版；需先配置 HTTPS 入口。";
                return;
            }
            // 设备认证只发生在 Windows→Mac；浏览器配对后只能访问只读网页。
            var code = response.GetProperty("code").GetString();
            MobilePairingText = $"一次性配对码：{code}（5 分钟内有效，仅限手机只读）";
        }
        catch (Exception)
        {
            MobilePairingText = "配对码获取失败，请检查连接与 Mac Core 配置。";
        }
    }

    private async Task PreviewStoryPackAsync()
    {
        if (_client is null)
        {
            StoryPackPreviewText = "请先连接 Mac Core。";
            return;
        }

        try
        {
            // 同时支持纯 JSON 与云端 LLM 回复中的 markdown json 代码块。
            var source = StoryPackInput.Trim();
            var fence = source.IndexOf("```json", StringComparison.OrdinalIgnoreCase);
            if (fence >= 0)
            {
                var start = source.IndexOf('\n', fence);
                var end = start < 0 ? -1 : source.IndexOf("```", start + 1, StringComparison.Ordinal);
                if (start < 0 || end < 0)
                {
                    throw new FormatException("StoryPack JSON 代码块不完整。");
                }
                source = source.Substring(start + 1, end - start - 1).Trim();
            }
            using var document = JsonDocument.Parse(source);
            var preview = await _client.PreviewStoryPackAsync(
                document.RootElement, CurrentConnectionToken);
            var output = preview.GetProperty("output");
            var shots = preview.GetProperty("shot_count").GetInt32();
            var width = output.GetProperty("width").GetInt32();
            var height = output.GetProperty("height").GetInt32();
            var fps = output.GetProperty("fps").GetInt32();
            var duration = output.GetProperty("planned_duration_s").GetInt32();
            // 将计划按镜头展开，使审核者能直接检查角色和场景切换。
            var shotLines = preview.GetProperty("shots").EnumerateArray().Select(shot =>
            {
                var cast = string.Join(", ", shot.GetProperty("cast_refs").EnumerateArray()
                    .Select(item => item.GetString()));
                return $"{shot.GetProperty("id").GetString()}: {shot.GetProperty("action").GetString()}" +
                    $"  [场景 {shot.GetProperty("scene_ref").GetString()} | 角色 {cast}]";
            });
            // Core 只证明 SQLite 是否有记录；不在 UI 上暗示身份或使用权已批准。
            var assetStatus = preview.GetProperty("asset_record_checks").EnumerateArray()
                .Select(item => $"{item.GetProperty("ref").GetString()}: " +
                    $"{item.GetProperty("registry_record_status").GetString()}, " +
                    $"内容={item.GetProperty("managed_object_integrity").GetString()}");
            var missingLocks = preview.GetProperty("missing_design_locks").EnumerateArray()
                .Select(item => item.GetString());
            // 增量指纹用于缓存与变更追踪，不代表自动生成或 QC 许可。
            var fingerprintPlan = preview.GetProperty("fingerprint_plan");
            var currentShotKeys = fingerprintPlan.GetProperty("shots").EnumerateArray()
                .ToDictionary(
                    item => item.GetProperty("shot_id").GetString()!,
                    item => item.GetProperty("input_sha256").GetString()!,
                    StringComparer.OrdinalIgnoreCase);
            var currentStoryReviewSha = fingerprintPlan.GetProperty("story_review_sha256")
                .GetString()!;
            var currentEpisodeId = preview.GetProperty("episode_id").GetString()!;
            string changeSummary;
            if (_lastPreviewEpisodeId == currentEpisodeId && _lastShotInputSha is not null)
            {
                // 仅比较当前窗口中同一集的两次预览；不能用于证明 QC 或缓存合法性。
                var changed = currentShotKeys.Where(pair =>
                    !_lastShotInputSha.TryGetValue(pair.Key, out var old) || old != pair.Value)
                    .Select(pair => pair.Key).ToArray();
                var removed = _lastShotInputSha.Keys.Where(key =>
                    !currentShotKeys.ContainsKey(key)).ToArray();
                var storyChanged = _lastStoryReviewSha != currentStoryReviewSha;
                changeSummary = $"输入变化 {changed.Length} 镜" +
                    (changed.Length > 0 ? $"（{string.Join(", ", changed)}）" : "") +
                    (removed.Length > 0 ? $"；已删除 {string.Join(", ", removed)}" : "") +
                    (storyChanged ? "；需重新检查故事" : "；故事审阅摘要未变");
            }
            else
            {
                changeSummary = "首次预览本集，尚无本窗口内可比较版本";
            }
            _lastPreviewEpisodeId = currentEpisodeId;
            _lastStoryReviewSha = currentStoryReviewSha;
            _lastShotInputSha = currentShotKeys;
            var compilation = preview.GetProperty("production_compilation");
            var missing = compilation.GetProperty("missing_contract_fields").GetProperty("each_shot")
                .EnumerateArray().Select(item => item.GetString());
            var trust = compilation.GetProperty("missing_trust_gates")
                .EnumerateArray().Select(item => item.GetString());
            StoryPackPreviewText =
                $"预览通过：{shots} 镜 · {width}×{height} · {fps}fps · {duration}秒\\n" +
                string.Join("\\n", shotLines) + "\\n" +
                $"素材记录（不等于主人审批）：{string.Join("; ", assetStatus)}\\n" +
                $"未冻结设计项：{(missingLocks.Any() ? string.Join(", ", missingLocks) : "无")}\\n" +
                $"各镜仍需编制：{string.Join(", ", missing)}\\n" +
                $"审批缺口：{string.Join(", ", trust)}\\n" +
                $"变更追踪：{changeSummary}（只比较输入，不自动生成）\\n" +
                "编译结果仅为草稿，不具备执行和发布许可。";
        }
        catch (Exception exception)
        {
            // 不将未经验证的故事包保存到日志或自动发送到其它服务。
            StoryPackPreviewText = $"预览失败：{exception.Message}";
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
        if (_stateStore.Apply(envelope, IsVisibleTask) && envelope.IsProductionChange())
        {
            _ = _dispatcher.InvokeAsync(Production.QueueRefresh);
        }
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

    private void OnConnectionStateChanged(object? sender, ConnectionState state)
    {
        _stateStore.SetConnection(state);
        if (state == ConnectionState.Online)
        {
            _ = _dispatcher.InvokeAsync(Production.QueueRefresh);
        }
    }

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
        await _dispatcher.InvokeAsync(Production.ConnectionChanged).ConfigureAwait(false);
    }

    /// <summary>关闭应用时取消后台链路并释放连接池。</summary>
    public async ValueTask DisposeAsync()
    {
        _lifetime.Cancel();
        await CancelConnectionAsync().ConfigureAwait(false);
        _stateStore.SnapshotChanged -= OnSnapshotChanged;
        _lifetime.Dispose();
        _workerManager.Dispose();
        await _logger.DisposeAsync().ConfigureAwait(false);
    }
}
