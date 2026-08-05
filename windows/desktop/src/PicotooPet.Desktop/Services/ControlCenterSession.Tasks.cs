using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>Control Center 的任务动作边界；原始错误只写入脱敏日志。</summary>
public sealed partial class ControlCenterSession
{
    private static readonly TimeSpan DiagnosticObservationWindow = TimeSpan.FromMinutes(2);
    private static readonly TimeSpan[] DiagnosticObservationDelays =
    {
        TimeSpan.FromSeconds(1),
        TimeSpan.FromSeconds(2),
        TimeSpan.FromSeconds(4),
        TimeSpan.FromSeconds(8),
        TimeSpan.FromSeconds(10),
    };

    /// <summary>通过固定端点创建诊断任务；网络重试必须复用幂等键。</summary>
    public async Task<TaskRecord> CreateDiagnosticSnapshotAsync(
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        if (_coordinator is null)
        {
            throw new InvalidOperationException("尚未连接 Mac Core。");
        }
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);

        try
        {
            await using var client = CreateTaskActionClient();
            var task = await client.CreateDiagnosticSnapshotAsync(
                DiagnosticSnapshotRequest.CreateDefault(),
                idempotencyKey,
                cancellationToken).ConfigureAwait(false);
            _stateStore.TaskStore.UpsertTask(task);
            SetStatus($"已创建系统诊断任务 {task.TaskId}。");
            return task;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (ApiException exception)
        {
            _logger.Error("创建系统诊断任务失败", exception);
            SetStatus("创建系统诊断任务失败；详细信息已写入脱敏日志。");
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error("创建系统诊断任务失败", exception);
            const string message = "创建系统诊断任务失败；详细信息已写入脱敏日志。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>优先消费事件快照，必要时使用有界 REST 轮询恢复目标任务。</summary>
    public async Task<TaskObservationResult> ObserveTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        if (_coordinator is null)
        {
            throw new InvalidOperationException("尚未连接 Mac Core。");
        }
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);

        using var linked = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _lifetime.Token);
        try
        {
            var deadline = DateTimeOffset.UtcNow + DiagnosticObservationWindow;
            var delayIndex = 0;
            await using var client = CreateTaskActionClient();

            while (DateTimeOffset.UtcNow < deadline)
            {
                linked.Token.ThrowIfCancellationRequested();
                var eventTask = FindTaskSnapshot(taskId);
                if (eventTask is not null && IsTerminal(eventTask.Status))
                {
                    return new TaskObservationResult(eventTask, ObservationWindowExpired: false);
                }

                var refreshed = await client.GetTaskAsync(taskId, linked.Token)
                    .ConfigureAwait(false);
                _stateStore.TaskStore.UpsertTask(refreshed);
                if (IsTerminal(refreshed.Status))
                {
                    return new TaskObservationResult(refreshed, ObservationWindowExpired: false);
                }

                var delay = DiagnosticObservationDelays[
                    Math.Min(delayIndex, DiagnosticObservationDelays.Length - 1)];
                delayIndex++;
                var remaining = deadline - DateTimeOffset.UtcNow;
                if (remaining <= TimeSpan.Zero)
                {
                    break;
                }
                await Task.Delay(delay <= remaining ? delay : remaining, linked.Token)
                    .ConfigureAwait(false);
            }

            var current = FindTaskSnapshot(taskId)
                ?? await client.GetTaskAsync(taskId, linked.Token).ConfigureAwait(false);
            _stateStore.TaskStore.UpsertTask(current);
            return new TaskObservationResult(
                current,
                ObservationWindowExpired: !IsTerminal(current.Status));
        }
        catch (OperationCanceledException) when (linked.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error($"观察诊断任务失败 task_id={taskId}", exception);
            const string message = "诊断任务观察暂时中断；任务仍由 Mac Core 管理。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>读取已完成诊断任务的固定结果合同。</summary>
    public async Task<DiagnosticSnapshotResult> GetDiagnosticResultAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        if (_coordinator is null)
        {
            throw new InvalidOperationException("尚未连接 Mac Core。");
        }
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);

        try
        {
            await using var client = CreateTaskActionClient();
            return await client.GetTaskResultAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error($"读取诊断结果失败 task_id={taskId}", exception);
            const string message = "诊断结果无法安全显示；详细信息已写入脱敏日志。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>取消可取消任务，并发布 Mac Core 返回的裁决快照。</summary>
    public async Task<TaskRecord> CancelTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        try
        {
            var task = await coordinator.CancelTaskAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
            SetStatus(
                task.Status == "Running"
                    ? $"任务 {taskId} 的取消请求已提交，等待 Worker 安全停止。"
                    : $"任务 {taskId} 已取消。");
            return task;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error($"取消任务失败 task_id={taskId}", exception);
            const string message = "取消任务失败；详细信息已写入脱敏日志。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>为失败或取消任务创建新的子任务，不重新打开原任务。</summary>
    public async Task<TaskRecord> RetryTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        try
        {
            var task = await coordinator.RetryTaskAsync(taskId, cancellationToken)
                .ConfigureAwait(false);
            SetStatus($"已创建重试子任务 {task.TaskId}。");
            return task;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            _logger.Error($"重试任务失败 task_id={taskId}", exception);
            const string message = "创建重试任务失败；详细信息已写入脱敏日志。";
            SetStatus(message);
            throw new InvalidOperationException(message, exception);
        }
    }

    /// <summary>返回冻结的只读轮询间隔，供原生 smoke 验证。</summary>
    public static IReadOnlyList<TimeSpan> GetDiagnosticObservationDelaysForSmoke() =>
        Array.AsReadOnly(DiagnosticObservationDelays);

    private MacCoreClient CreateTaskActionClient()
    {
        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        ValidateConnectionInput(macBaseUrl, token ?? string.Empty, out var baseUri);
        return MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token!));
    }

    private TaskRecord? FindTaskSnapshot(string taskId) =>
        _stateStore.TaskStore.Snapshot.Tasks.FirstOrDefault(
            task => string.Equals(task.TaskId, taskId, StringComparison.Ordinal));

    private static bool IsTerminal(string status) => status is
        "Completed" or
        "Failed" or
        "Cancelled" or
        "Archived";
}

/// <summary>有界观察结束时的任务和窗口状态。</summary>
public sealed record TaskObservationResult(
    TaskRecord Task,
    bool ObservationWindowExpired);
