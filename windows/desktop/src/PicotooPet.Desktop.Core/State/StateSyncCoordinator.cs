using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.State;

/// <summary>统一协调 REST 真相快照、WebSocket 实时增量和有界恢复。</summary>
public sealed class StateSyncCoordinator : IAsyncDisposable
{
    private static readonly HashSet<string> WorkerStates = new(StringComparer.Ordinal)
    {
        "not_deployed",
        "starting",
        "online",
        "degraded",
        "offline",
    };

    private static readonly TimeSpan HealthyRestPollInterval  = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan DegradedRestPollInterval = TimeSpan.FromSeconds(3);

    private readonly object _streamGate = new();
    private readonly MacCoreClient _client;
    private readonly ConnectionStateStore _connectionStore;
    private readonly CapabilityStateStore _capabilityStore;
    private readonly WorkerStateStore _workerStore;
    private readonly TaskStateStore _taskStore;
    private readonly Func<long, IEventStreamSession>? _eventStreamFactory;
    private CancellationTokenSource? _streamLifetime;
    private IEventStreamSession? _eventStream;
    private Task? _streamTask;
    private bool _disposed;

    /// <summary>保留 Slice A 构造器，并使用内部保守 Worker 状态仓库。</summary>
    public StateSyncCoordinator(
        MacCoreClient client,
        ConnectionStateStore connectionStore,
        CapabilityStateStore capabilityStore,
        TaskStateStore taskStore,
        Func<long, IEventStreamSession>? eventStreamFactory)
        : this(
            client,
            connectionStore,
            capabilityStore,
            new WorkerStateStore(),
            taskStore,
            eventStreamFactory)
    {
    }

    /// <summary>创建同步协调器；事件流工厂可为空以支持纯 REST 测试。</summary>
    public StateSyncCoordinator(
        MacCoreClient client,
        ConnectionStateStore connectionStore,
        CapabilityStateStore capabilityStore,
        WorkerStateStore workerStore,
        TaskStateStore taskStore,
        Func<long, IEventStreamSession>? eventStreamFactory)
    {
        _client             = client ?? throw new ArgumentNullException(nameof(client));
        _connectionStore    = connectionStore ?? throw new ArgumentNullException(nameof(connectionStore));
        _capabilityStore    = capabilityStore ?? throw new ArgumentNullException(nameof(capabilityStore));
        _workerStore        = workerStore ?? throw new ArgumentNullException(nameof(workerStore));
        _taskStore          = taskStore ?? throw new ArgumentNullException(nameof(taskStore));
        _eventStreamFactory = eventStreamFactory;
        _client.RequestMeasured += OnRequestMeasured;
    }

    /// <summary>REST 请求延迟样本。</summary>
    public event EventHandler<RequestMeasurement>? RequestMeasured;

    /// <summary>WebSocket Ping/Pong 延迟样本。</summary>
    public event EventHandler<SocketMeasurement>? SocketMeasured;

    /// <summary>轻量健康快照更新。</summary>
    public event EventHandler<HealthResponse>? HealthChanged;

    /// <summary>需要写入脱敏诊断日志的协调器事件。</summary>
    public event EventHandler<string>? DiagnosticRaised;

    /// <summary>并发读取 health、capabilities、Worker 和 tasks，再启动事件流之前提交快照。</summary>
    public Task<HealthResponse> InitializeSnapshotAsync(
        CancellationToken cancellationToken) =>
        RefreshAsync(cancellationToken);

    /// <summary>手动重新加载完整服务端快照；REST 成功是系统可用性的权威事实。</summary>
    public async Task<HealthResponse> RefreshAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();

        try
        {
            var healthTask     = _client.GetHealthAsync(cancellationToken);
            var capabilityTask = LoadCapabilitiesAsync(cancellationToken);
            var workerTask     = LoadWorkerStatusAsync(cancellationToken);
            var tasksTask      = _client.GetTasksAsync(cancellationToken);
            await Task.WhenAll(healthTask, capabilityTask, workerTask, tasksTask)
                .ConfigureAwait(false);

            var health       = await healthTask.ConfigureAwait(false);
            var capabilities = await capabilityTask.ConfigureAwait(false);
            var worker       = await workerTask.ConfigureAwait(false);
            var tasks        = await tasksTask.ConfigureAwait(false);
            _capabilityStore.Set(capabilities);
            _workerStore.Set(worker);
            _taskStore.ReplaceTasks(tasks);
            _connectionStore.SetCoreReachability(reachable: true);
            HealthChanged?.Invoke(this, health);
            return health;
        }
        catch (ApiException exception) when (exception.StatusCode is 401 or 403)
        {
            _connectionStore.SetCoreAuthenticationFailed(exception.Message);
            throw;
        }
        catch (Exception exception)
        {
            _connectionStore.SetCoreReachability(reachable: false, exception.Message);
            throw;
        }
    }

    /// <summary>启动 WebSocket 实时通道，并同时保持低频 REST 真相对账。</summary>
    public Task RunEventStreamAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var factory = _eventStreamFactory
            ?? throw new InvalidOperationException("当前协调器未配置事件流工厂。");

        lock (_streamGate)
        {
            if (_streamTask is not null)
            {
                return _streamTask;
            }

            var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            var stream   = factory(_taskStore.Snapshot.LastSequence);
            stream.ConnectionStateChanged += OnConnectionStateChanged;
            stream.SocketMeasured         += OnSocketMeasured;
            _streamLifetime = lifetime;
            _eventStream    = stream;
            _connectionStore.SetEventStreamState(ConnectionState.Connecting);
            _streamTask = RunDualChannelCoreAsync(stream, lifetime);
            return _streamTask;
        }
    }

    /// <summary>创建任务并立即归并 REST 返回快照。</summary>
    public async Task<TaskRecord> CreateTaskAsync(
        TaskCreateRequest request,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(request);
        var task = await _client.CreateTaskAsync(
            request,
            Guid.NewGuid().ToString("N"),
            cancellationToken).ConfigureAwait(false);
        _taskStore.UpsertTask(task);
        return task;
    }

    /// <summary>读取审批中心安全快照；审批不进入任务事件 reducer。</summary>
    public Task<ApprovalRecord[]> GetApprovalsAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        return _client.GetApprovalsAsync(cancellationToken);
    }

    /// <summary>执行摘要绑定审批决策，并由调用方刷新审批与任务快照。</summary>
    public Task<ApprovalRecord> DecideApprovalAsync(
        string approvalId,
        ApprovalDecisionRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(approvalId);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        return _client.DecideApprovalAsync(
            approvalId,
            request,
            idempotencyKey,
            cancellationToken);
    }

    /// <summary>请求 Mac Core 取消任务，并归并服务端裁决后的状态。</summary>
    public async Task<TaskRecord> CancelTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);
        var task = await _client.CancelTaskAsync(taskId, cancellationToken)
            .ConfigureAwait(false);
        _taskStore.UpsertTask(task);
        return task;
    }

    /// <summary>请求 Mac Core 为失败或取消任务创建新的重试子任务。</summary>
    public async Task<TaskRecord> RetryTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);
        var task = await _client.RetryTaskAsync(taskId, cancellationToken)
            .ConfigureAwait(false);
        _taskStore.UpsertTask(task);
        return task;
    }

    /// <summary>取消并等待旧双通道同步循环，确保重连时只有一个消费者。</summary>
    public async Task StopAsync()
    {
        Task? streamTask;
        CancellationTokenSource? lifetime;
        lock (_streamGate)
        {
            streamTask = _streamTask;
            lifetime   = _streamLifetime;
        }

        lifetime?.Cancel();
        if (streamTask is not null)
        {
            try
            {
                await streamTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // 主动停止双通道同步属于正常控制路径。
            }
        }
    }

    private async Task<CapabilitiesResponse> LoadCapabilitiesAsync(
        CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetCapabilitiesAsync(cancellationToken)
                .ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(response.SchemaVersion)
                || response.Features is null
                || response.ContractVersions is null)
            {
                throw new InvalidDataException("能力响应缺少必需字段。");
            }
            return response;
        }
        catch (ApiException exception) when (exception.StatusCode == 404)
        {
            DiagnosticRaised?.Invoke(this, "capabilities_legacy22_fallback");
            return Legacy22Response();
        }
        catch (ApiException exception) when (exception.Code == "INVALID_RESPONSE")
        {
            DiagnosticRaised?.Invoke(this, "capabilities_invalid_legacy22_fallback");
            return Legacy22Response();
        }
        catch (InvalidDataException)
        {
            DiagnosticRaised?.Invoke(this, "capabilities_incomplete_legacy22_fallback");
            return Legacy22Response();
        }
    }

    private async Task<WorkerStatusResponse> LoadWorkerStatusAsync(
        CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetWorkerStatusAsync(cancellationToken)
                .ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(response.SchemaVersion)
                || !WorkerStates.Contains(response.State)
                || string.IsNullOrWhiteSpace(response.Reason)
                || response.SupportedTaskTypes is null
                || response.ObservedAt == default
                || (response.Available && string.IsNullOrWhiteSpace(response.WorkerId)))
            {
                throw new InvalidDataException("Worker 状态响应缺少必需字段。");
            }
            return response;
        }
        catch (ApiException exception) when (exception.StatusCode == 404)
        {
            DiagnosticRaised?.Invoke(this, "worker_status_not_deployed_fallback");
            return NotDeployedWorkerResponse();
        }
        catch (ApiException exception) when (exception.Code == "INVALID_RESPONSE")
        {
            DiagnosticRaised?.Invoke(this, "worker_status_invalid_fallback");
            return NotDeployedWorkerResponse();
        }
        catch (InvalidDataException)
        {
            DiagnosticRaised?.Invoke(this, "worker_status_incomplete_fallback");
            return NotDeployedWorkerResponse();
        }
    }

    private async Task RunDualChannelCoreAsync(
        IEventStreamSession stream,
        CancellationTokenSource lifetime)
    {
        var eventTask = RunEventStreamSessionAsync(stream, lifetime.Token);
        var pollTask  = RunSnapshotPollingAsync(lifetime.Token);
        try
        {
            var completed = await Task.WhenAny(eventTask, pollTask).ConfigureAwait(false);
            await completed.ConfigureAwait(false);
        }
        finally
        {
            lifetime.Cancel();
            await ObserveCancellationAsync(eventTask).ConfigureAwait(false);
            await ObserveCancellationAsync(pollTask).ConfigureAwait(false);
            if (_connectionStore.Snapshot.EventStreamState != ConnectionState.AuthenticationFailed)
            {
                _connectionStore.SetEventStreamState(ConnectionState.Offline);
            }
            stream.ConnectionStateChanged -= OnConnectionStateChanged;
            stream.SocketMeasured         -= OnSocketMeasured;
            await stream.DisposeAsync().ConfigureAwait(false);
            lifetime.Dispose();
            lock (_streamGate)
            {
                if (ReferenceEquals(_eventStream, stream))
                {
                    _streamLifetime = null;
                    _eventStream    = null;
                    _streamTask     = null;
                }
            }
        }
    }

    private async Task RunEventStreamSessionAsync(
        IEventStreamSession stream,
        CancellationToken cancellationToken)
    {
        try
        {
            await stream.RunAsync(ApplyEventAsync, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (EventStreamAuthenticationException exception)
        {
            _connectionStore.SetEventStreamState(
                ConnectionState.AuthenticationFailed,
                exception.Message);
            throw;
        }
        catch (Exception exception)
        {
            _connectionStore.SetEventStreamState(ConnectionState.Faulted, exception.Message);
            DiagnosticRaised?.Invoke(this, "event_stream_transient");
            throw;
        }
    }

    private async Task RunSnapshotPollingAsync(CancellationToken cancellationToken)
    {
        // ── Initial REST snapshot is already fresh; avoid a duplicate immediate full task reload. ──
        var firstInterval = IsRealtimeHealthy()
            ? HealthyRestPollInterval
            : DegradedRestPollInterval;
        await Task.Delay(firstInterval, cancellationToken).ConfigureAwait(false);
        var poller = new CoreSnapshotPoller(
            RefreshTruthSnapshotAsync,
            IsRealtimeHealthy,
            HealthyRestPollInterval,
            DegradedRestPollInterval);
        await poller.RunAsync(cancellationToken).ConfigureAwait(false);
    }

    private bool IsRealtimeHealthy() =>
        _connectionStore.Snapshot.CoreReachable
        && _connectionStore.Snapshot.EventStreamState == ConnectionState.Online;

    private async Task RefreshTruthSnapshotAsync(CancellationToken cancellationToken)
    {
        try
        {
            var healthTask = _client.GetHealthAsync(cancellationToken);
            var workerTask = LoadWorkerStatusAsync(cancellationToken);
            var tasksTask  = _client.GetTasksAsync(cancellationToken);
            await Task.WhenAll(healthTask, workerTask, tasksTask).ConfigureAwait(false);

            var health = await healthTask.ConfigureAwait(false);
            _workerStore.Set(await workerTask.ConfigureAwait(false));
            _taskStore.ReplaceTasks(await tasksTask.ConfigureAwait(false));
            _connectionStore.SetCoreReachability(reachable: true);
            HealthChanged?.Invoke(this, health);
        }
        catch (ApiException exception) when (exception.StatusCode is 401 or 403)
        {
            _connectionStore.SetCoreAuthenticationFailed(exception.Message);
            throw;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _connectionStore.SetCoreReachability(reachable: false, exception.Message);
            DiagnosticRaised?.Invoke(this, "rest_truth_poll_failed");
            // ── Keep the poller alive so transient REST failure can self-recover on the next short interval. ──
        }
    }

    private async ValueTask ApplyEventAsync(
        EventEnvelope envelope,
        CancellationToken cancellationToken)
    {
        var result = _taskStore.Apply(envelope, IsVisibleTask);
        if (result != SequenceApplyResult.GapDetected)
        {
            return;
        }

        DiagnosticRaised?.Invoke(
            this,
            $"event_sequence_gap:{_taskStore.Snapshot.LastSequence}:{envelope.Sequence}");
        var tasks = await _client.GetTasksAsync(cancellationToken).ConfigureAwait(false);
        _taskStore.ReloadTasksAtSequence(tasks, envelope.Sequence);
    }

    private static bool IsVisibleTask(TaskRecord task) =>
        !string.Equals(
            task.ResourceTag,
            "phase2-diagnostic",
            StringComparison.Ordinal);

    private void OnRequestMeasured(object? sender, RequestMeasurement measurement) =>
        RequestMeasured?.Invoke(this, measurement);

    private void OnSocketMeasured(object? sender, SocketMeasurement measurement) =>
        SocketMeasured?.Invoke(this, measurement);

    private void OnConnectionStateChanged(object? sender, ConnectionState state)
    {
        _connectionStore.SetEventStreamState(state);
        if (state is ConnectionState.Reconnecting or ConnectionState.Faulted)
        {
            DiagnosticRaised?.Invoke(this, "event_stream_transient");
        }
    }

    private static async Task ObserveCancellationAsync(Task task)
    {
        try
        {
            await task.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // 对端任务由双通道协调器取消。
        }
        catch
        {
            // 原始完成任务已经由调用路径观察；这里只负责释放另一通道。
        }
    }

    private static CapabilitiesResponse Legacy22Response() => new(
        "2.2.0",
        ControlCenterCapabilities.Legacy22,
        new ContractVersions("unavailable", "unavailable"),
        "manual_approval_only");

    private static WorkerStatusResponse NotDeployedWorkerResponse() => new(
        "2.3.0",
        Available: false,
        State: "not_deployed",
        Reason: "worker_runtime_not_installed",
        WorkerId: null,
        SupportedTaskTypes: Array.Empty<string>(),
        ObservedAt: DateTimeOffset.UtcNow);

    private void ThrowIfDisposed() =>
        ObjectDisposedException.ThrowIf(_disposed, this);

    /// <summary>停止事件流、取消订阅并释放 REST 连接池。</summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        await StopAsync().ConfigureAwait(false);
        _client.RequestMeasured -= OnRequestMeasured;
        await _client.DisposeAsync().ConfigureAwait(false);
    }
}
