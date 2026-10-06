using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>供 Goal autopilot 复用的现有 Production executor 最小表面。</summary>
public interface IProductionJobExecutor
{
    Task<ProductionPackageRecord> RunAsync(
        string productionJobId,
        CancellationToken cancellationToken = default);
}

/// <summary>Goal continuation 的只读观察入口；不会创建 Production 事实。</summary>
public interface IGoalProductionAutopilotObserver
{
    GoalProductionAutopilotSnapshot Observe(
        string? goalId,
        GoalVideoContinuationRecord? continuation);
}

public enum GoalProductionAutopilotPhase
{
    Idle,
    Running,
    AwaitingCoreRefresh,
    TemporaryFailure,
    Terminal,
}

/// <summary>仅含有界本地执行状态，不携带异常、路径、令牌、Prompt 或模型信息。</summary>
public sealed record GoalProductionAutopilotSnapshot(
    string? GoalId,
    string? ProductionJobId,
    GoalProductionAutopilotPhase Phase,
    string? StatusText)
{
    public static GoalProductionAutopilotSnapshot Idle(string? goalId, string? productionJobId) =>
        new(goalId, productionJobId, GoalProductionAutopilotPhase.Idle, null);
}

/// <summary>
/// 将当前 Goal 的精确 Production Job 非阻塞地交给既有 ProductionExecutionService。
/// Core 仍拥有 lease、幂等、恢复和所有耐久状态。
/// </summary>
public sealed class GoalProductionAutopilotCoordinator : IGoalProductionAutopilotObserver, IAsyncDisposable
{
    private static readonly HashSet<string> RecoverableStatuses = new(StringComparer.Ordinal)
    {
        "Ready",
        "Claimed",
        "Rendering",
    };

    private static readonly HashSet<string> TerminalStatuses = new(StringComparer.Ordinal)
    {
        "production_ready",
        "Failed",
        "NeedsHuman",
        "Cancelled",
    };

    private readonly object _gate = new();
    private readonly IProductionJobExecutor _executor;
    private readonly IAsyncDisposable? _ownedExecutor;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly HashSet<string> _runningJobs = new(StringComparer.Ordinal);
    private readonly HashSet<string> _completedJobs = new(StringComparer.Ordinal);
    private readonly HashSet<string> _failurePendingDisplay = new(StringComparer.Ordinal);
    private readonly HashSet<Task> _tasks = [];
    private GoalProductionAutopilotSnapshot _current =
        GoalProductionAutopilotSnapshot.Idle(null, null);
    private bool _disposed;

    public GoalProductionAutopilotCoordinator(IProductionJobExecutor executor)
        : this(executor, null)
    {
    }

    private GoalProductionAutopilotCoordinator(
        IProductionJobExecutor executor,
        IAsyncDisposable? ownedExecutor)
    {
        _executor = executor ?? throw new ArgumentNullException(nameof(executor));
        _ownedExecutor = ownedExecutor;
    }

    public static GoalProductionAutopilotCoordinator Create(ControlCenterSession session)
    {
        ArgumentNullException.ThrowIfNull(session);
        var executor = ProductionExecutionService.Create(session);
        return new GoalProductionAutopilotCoordinator(executor, executor);
    }

    public GoalProductionAutopilotSnapshot CurrentSnapshot
    {
        get
        {
            lock (_gate)
            {
                return _current;
            }
        }
    }

    public GoalProductionAutopilotSnapshot Observe(
        string? goalId,
        GoalVideoContinuationRecord? continuation)
    {
        string? jobToStart = null;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            var validContinuation = continuation is not null
                && !string.IsNullOrWhiteSpace(goalId)
                && string.Equals(goalId, continuation.GoalId, StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(continuation.ProductionJobId);
            var productionJobId = validContinuation ? continuation!.ProductionJobId : null;
            if (!string.Equals(_current.GoalId, goalId, StringComparison.Ordinal)
                || !string.Equals(_current.ProductionJobId, productionJobId, StringComparison.Ordinal))
            {
                _current = GoalProductionAutopilotSnapshot.Idle(goalId, productionJobId);
            }

            if (!validContinuation || productionJobId is null)
            {
                return _current;
            }

            var status = continuation!.ProductionStatus;
            if (status is not null && TerminalStatuses.Contains(status))
            {
                _current = new GoalProductionAutopilotSnapshot(
                    goalId,
                    productionJobId,
                    GoalProductionAutopilotPhase.Terminal,
                    null);
                return _current;
            }
            if (status is null || !RecoverableStatuses.Contains(status))
            {
                _current = GoalProductionAutopilotSnapshot.Idle(goalId, productionJobId);
                return _current;
            }
            if (_completedJobs.Contains(productionJobId))
            {
                _current = AwaitingCore(goalId!, productionJobId);
                return _current;
            }
            if (_runningJobs.Contains(productionJobId))
            {
                _current = Running(goalId!, productionJobId);
                return _current;
            }
            if (_failurePendingDisplay.Remove(productionJobId))
            {
                _current = TemporaryFailure(goalId!, productionJobId);
                return _current;
            }

            _runningJobs.Add(productionJobId);
            _current = Running(goalId!, productionJobId);
            jobToStart = productionJobId;
        }

        if (jobToStart is not null)
        {
            StartBackgroundRun(goalId!, jobToStart);
        }
        return CurrentSnapshot;
    }

    private void StartBackgroundRun(string goalId, string productionJobId)
    {
        Task task;
        lock (_gate)
        {
            if (_disposed)
            {
                _runningJobs.Remove(productionJobId);
                return;
            }
            var cancellationToken = _lifetime.Token;
            task = Task.Run(
                () => RunCoreAsync(goalId, productionJobId, cancellationToken),
                CancellationToken.None);
            _tasks.Add(task);
        }
        _ = task.ContinueWith(
            completed =>
            {
                lock (_gate)
                {
                    _tasks.Remove(completed);
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private async Task RunCoreAsync(
        string goalId,
        string productionJobId,
        CancellationToken cancellationToken)
    {
        try
        {
            _ = await _executor.RunAsync(productionJobId, cancellationToken).ConfigureAwait(false);
            lock (_gate)
            {
                _completedJobs.Add(productionJobId);
                if (!_disposed && IsCurrent(goalId, productionJobId))
                {
                    _current = AwaitingCore(goalId, productionJobId);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Coordinator shutdown owns cancellation; Core lease remains the recovery authority.
        }
        catch (Exception)
        {
            lock (_gate)
            {
                _failurePendingDisplay.Add(productionJobId);
                if (!_disposed && IsCurrent(goalId, productionJobId))
                {
                    _current = TemporaryFailure(goalId, productionJobId);
                }
            }
        }
        finally
        {
            lock (_gate)
            {
                _runningJobs.Remove(productionJobId);
            }
        }
    }

    private bool IsCurrent(string goalId, string productionJobId) =>
        string.Equals(_current.GoalId, goalId, StringComparison.Ordinal)
        && string.Equals(_current.ProductionJobId, productionJobId, StringComparison.Ordinal);

    private static GoalProductionAutopilotSnapshot Running(string goalId, string productionJobId) =>
        new(
            goalId,
            productionJobId,
            GoalProductionAutopilotPhase.Running,
            "正在检查本地生产环境并执行固定生产计划。");

    private static GoalProductionAutopilotSnapshot AwaitingCore(string goalId, string productionJobId) =>
        new(
            goalId,
            productionJobId,
            GoalProductionAutopilotPhase.AwaitingCoreRefresh,
            "本地生产结果已提交，正在同步 Core 状态。");

    private static GoalProductionAutopilotSnapshot TemporaryFailure(string goalId, string productionJobId) =>
        new(
            goalId,
            productionJobId,
            GoalProductionAutopilotPhase.TemporaryFailure,
            "本地生产暂时不可用；修复本机条件后将于后续刷新重试。");

    public async ValueTask DisposeAsync()
    {
        Task[] tasks;
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            _lifetime.Cancel();
            tasks = _tasks.ToArray();
        }
        try
        {
            await Task.WhenAll(tasks).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // Expected when an active local render is cancelled during app shutdown.
        }
        if (_ownedExecutor is not null)
        {
            await _ownedExecutor.DisposeAsync().ConfigureAwait(false);
        }
        _lifetime.Dispose();
    }
}
