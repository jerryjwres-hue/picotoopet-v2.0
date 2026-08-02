using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Services;

/// <summary>集中管理真实 Mac Core 连接、状态快照、凭据和非敏感设置。</summary>
public sealed partial class ControlCenterSession : IAsyncDisposable
{
    private readonly object _snapshotGate = new();
    private readonly SemaphoreSlim _connectionGate = new(1, 1);
    private readonly CredentialManagerTokenStore _tokenStore;
    private readonly DesktopSettingsStore _settingsStore;
    private readonly SafeFileLogger _logger;
    private readonly AppStateStore _stateStore;
    private readonly LatencyRecorder _restLatency = new();
    private readonly LatencyRecorder _socketLatency = new();
    private readonly CancellationTokenSource _lifetime = new();
    private CancellationTokenSource? _connectionLifetime;
    private StateSyncCoordinator? _coordinator;
    private Task? _eventTask;
    private HealthResponse? _health;
    private string _macBaseUrl = DesktopSettings.Default.MacBaseUrl;
    private string _statusMessage = "请先保存 Mac 地址和设备令牌。";
    private bool _disposed;

    /// <summary>使用组合根提供的安全存储、状态仓库和日志器创建会话。</summary>
    public ControlCenterSession(
        CredentialManagerTokenStore tokenStore,
        DesktopSettingsStore settingsStore,
        SafeFileLogger logger,
        ConnectionStateStore connectionStore,
        CapabilityStateStore capabilityStore,
        TaskStateStore taskStore)
    {
        _tokenStore    = tokenStore ?? throw new ArgumentNullException(nameof(tokenStore));
        _settingsStore = settingsStore ?? throw new ArgumentNullException(nameof(settingsStore));
        _logger        = logger ?? throw new ArgumentNullException(nameof(logger));
        _stateStore    = new AppStateStore(
            connectionStore ?? throw new ArgumentNullException(nameof(connectionStore)),
            capabilityStore ?? throw new ArgumentNullException(nameof(capabilityStore)),
            taskStore ?? throw new ArgumentNullException(nameof(taskStore)));

        _stateStore.ConnectionStore.SnapshotChanged += OnConnectionChanged;
        _stateStore.CapabilityStore.SnapshotChanged += OnCapabilitiesChanged;
        _stateStore.WorkerStore.SnapshotChanged     += OnWorkerChanged;
        _stateStore.TaskStore.SnapshotChanged       += OnTasksChanged;
    }

    /// <summary>会话或服务端状态提交后发布完整只读快照。</summary>
    public event EventHandler<ControlCenterSessionSnapshot>? SnapshotChanged;

    /// <summary>当前可供 Shell 展示的完整快照。</summary>
    public ControlCenterSessionSnapshot Snapshot => CreateSnapshot();

    /// <summary>读取设置，并在 Credential Manager 已有令牌时自动连接。</summary>
    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var settings = await _settingsStore.LoadAsync(cancellationToken).ConfigureAwait(false);
        lock (_snapshotGate)
        {
            _macBaseUrl = settings.MacBaseUrl;
        }

        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            _stateStore.SetConnection(ConnectionState.Offline);
            SetStatus("尚未配对；设备令牌只会保存到 Windows Credential Manager。");
            return;
        }

        await ConnectAsync(settings.MacBaseUrl, token, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>验证新地址和令牌，连接成功后再持久化配对信息。</summary>
    public async Task SaveAndConnectAsync(
        string macBaseUrl,
        string token,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ValidateConnectionInput(macBaseUrl, token, out _);
        await ConnectAsync(macBaseUrl, token, cancellationToken).ConfigureAwait(false);
        _tokenStore.Save(token);
        await _settingsStore.SaveAsync(
            new DesktopSettings(macBaseUrl),
            cancellationToken).ConfigureAwait(false);
        lock (_snapshotGate)
        {
            _macBaseUrl = macBaseUrl;
        }
        SetStatus("双机控制链已连接，配对信息已安全保存。");
    }

    /// <summary>从 Mac Core 重新加载 health、capabilities、Worker 和任务快照。</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        var health = await coordinator.RefreshAsync(cancellationToken).ConfigureAwait(false);
        lock (_snapshotGate)
        {
            _health = health;
        }
        PublishSnapshot();
    }

    /// <summary>通过当前协调器创建任务并立即归并返回快照。</summary>
    public Task<TaskRecord> CreateTaskAsync(
        TaskCreateRequest request,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        return coordinator.CreateTaskAsync(request, cancellationToken);
    }

    private async Task ConnectAsync(
        string macBaseUrl,
        string token,
        CancellationToken cancellationToken)
    {
        ValidateConnectionInput(macBaseUrl, token, out var baseUri);
        await _connectionGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await StopConnectionCoreAsync().ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();

            lock (_snapshotGate)
            {
                _macBaseUrl    = macBaseUrl;
                _health        = null;
                _statusMessage = "正在连接 Mac Core……";
            }
            PublishSnapshot();

            var connectionLifetime = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);
            var client = MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
            var coordinator = new StateSyncCoordinator(
                client,
                _stateStore.ConnectionStore,
                _stateStore.CapabilityStore,
                _stateStore.WorkerStore,
                _stateStore.TaskStore,
                sequence => new EventStreamClient(baseUri, token, sequence));
            Subscribe(coordinator);
            _connectionLifetime = connectionLifetime;
            _coordinator        = coordinator;

            try
            {
                var health = await coordinator.InitializeSnapshotAsync(cancellationToken)
                    .ConfigureAwait(false);
                lock (_snapshotGate)
                {
                    _health        = health;
                    _statusMessage = "双机控制链已连接。";
                }
                _eventTask = RunEventStreamAsync(coordinator, connectionLifetime.Token);
                PublishSnapshot();
            }
            catch
            {
                await StopConnectionCoreAsync().ConfigureAwait(false);
                throw;
            }
        }
        finally
        {
            _connectionGate.Release();
        }
    }

    private async Task RunEventStreamAsync(
        StateSyncCoordinator coordinator,
        CancellationToken cancellationToken)
    {
        try
        {
            await coordinator.RunEventStreamAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // 重新配对、显式退出或会话释放时取消旧事件流属于正常控制路径。
        }
        catch (EventStreamAuthenticationException exception)
        {
            _logger.Error("WebSocket 设备认证失败", exception);
            SetStatus("设备认证失败，请在设置中重新配对。");
        }
        catch (Exception exception)
        {
            _logger.Error("WebSocket 状态同步失败", exception);
            SetStatus("事件链路发生故障；详细信息已写入脱敏日志。");
        }
    }

    private void Subscribe(StateSyncCoordinator coordinator)
    {
        coordinator.RequestMeasured += OnRequestMeasured;
        coordinator.SocketMeasured  += OnSocketMeasured;
        coordinator.HealthChanged   += OnHealthChanged;
        coordinator.DiagnosticRaised += OnDiagnosticRaised;
    }

    private void Unsubscribe(StateSyncCoordinator coordinator)
    {
        coordinator.RequestMeasured -= OnRequestMeasured;
        coordinator.SocketMeasured  -= OnSocketMeasured;
        coordinator.HealthChanged   -= OnHealthChanged;
        coordinator.DiagnosticRaised -= OnDiagnosticRaised;
    }

    private void OnRequestMeasured(object? sender, RequestMeasurement measurement)
    {
        _restLatency.Add(measurement.DurationMilliseconds);
        PublishSnapshot();
    }

    private void OnSocketMeasured(object? sender, SocketMeasurement measurement)
    {
        _socketLatency.Add(measurement.DurationMilliseconds);
        PublishSnapshot();
    }

    private void OnHealthChanged(object? sender, HealthResponse health)
    {
        lock (_snapshotGate)
        {
            _health = health;
        }
        PublishSnapshot();
    }

    private void OnDiagnosticRaised(object? sender, string diagnostic) =>
        _logger.Info($"状态同步诊断：{diagnostic}");

    private void OnConnectionChanged(object? sender, ConnectionSnapshot snapshot) =>
        PublishSnapshot();

    private void OnCapabilitiesChanged(object? sender, CapabilitySnapshot snapshot) =>
        PublishSnapshot();

    private void OnWorkerChanged(object? sender, WorkerSnapshot snapshot) =>
        PublishSnapshot();

    private void OnTasksChanged(object? sender, TaskStateSnapshot snapshot) =>
        PublishSnapshot();

    private ControlCenterSessionSnapshot CreateSnapshot()
    {
        lock (_snapshotGate)
        {
            var healthText = _health is null
                ? "尚未连接"
                : $"{_health.Status} · {_health.Version ?? "未知版本"}";
            var rest   = _restLatency.Snapshot();
            var socket = _socketLatency.Snapshot();
            var latencyText = rest.Count == 0 && socket.Count == 0
                ? "等待样本"
                : $"REST p95 {rest.P95Milliseconds:F1} ms · WS p95 {socket.P95Milliseconds:F1} ms";
            return new ControlCenterSessionSnapshot(
                _macBaseUrl,
                _stateStore.ControlCenterSnapshot,
                healthText,
                latencyText,
                _statusMessage);
        }
    }

    private void SetStatus(string message)
    {
        lock (_snapshotGate)
        {
            _statusMessage = message;
        }
        PublishSnapshot();
    }

    private void PublishSnapshot()
    {
        var snapshot = CreateSnapshot();
        SnapshotChanged?.Invoke(this, snapshot);
    }

    private static void ValidateConnectionInput(
        string macBaseUrl,
        string token,
        out Uri baseUri)
    {
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out baseUri!))
        {
            throw new InvalidOperationException("Mac 地址格式无效。");
        }
        if (baseUri.Scheme is not ("http" or "https"))
        {
            throw new InvalidOperationException("Mac 地址只允许 HTTP 或 HTTPS。");
        }
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new ArgumentException("设备令牌不能为空。", nameof(token));
        }
    }

    private async Task StopConnectionCoreAsync()
    {
        var connectionLifetime = _connectionLifetime;
        var eventTask           = _eventTask;
        var coordinator         = _coordinator;
        _connectionLifetime = null;
        _eventTask           = null;
        _coordinator         = null;
        connectionLifetime?.Cancel();

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
                // 旧事件消费者已按设计停止。
            }
        }
        if (coordinator is not null)
        {
            Unsubscribe(coordinator);
            await coordinator.DisposeAsync().ConfigureAwait(false);
        }
        connectionLifetime?.Dispose();
    }

    private void ThrowIfDisposed() =>
        ObjectDisposedException.ThrowIf(_disposed, this);

    /// <summary>停止事件链路、取消状态订阅并刷新关闭脱敏日志。</summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _lifetime.Cancel();
        await _connectionGate.WaitAsync().ConfigureAwait(false);
        try
        {
            await StopConnectionCoreAsync().ConfigureAwait(false);
        }
        finally
        {
            _connectionGate.Release();
        }

        _stateStore.ConnectionStore.SnapshotChanged -= OnConnectionChanged;
        _stateStore.CapabilityStore.SnapshotChanged -= OnCapabilitiesChanged;
        _stateStore.WorkerStore.SnapshotChanged     -= OnWorkerChanged;
        _stateStore.TaskStore.SnapshotChanged       -= OnTasksChanged;
        _connectionGate.Dispose();
        _lifetime.Dispose();
        await _logger.DisposeAsync().ConfigureAwait(false);
    }
}

/// <summary>Shell 一次性消费的真实会话状态。</summary>
public sealed record ControlCenterSessionSnapshot(
    string MacBaseUrl,
    ControlCenterSnapshot State,
    string HealthText,
    string LatencyText,
    string StatusMessage);
