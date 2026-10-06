using System.Diagnostics;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public interface IGoalFinalVideoObserver
{
    GoalFinalVideoSnapshot Observe(
        string? goalId,
        GoalVideoContinuationRecord? continuation);

    bool OpenCurrent();
}

public interface IFinalVideoLauncher
{
    void Open(string verifiedFinalVideoPath);
}

public enum GoalFinalVideoPhase
{
    Idle,
    Assembling,
    Ready,
    Failed,
}

public sealed record GoalFinalVideoSnapshot(
    string? GoalId,
    string? ProductionJobId,
    GoalFinalVideoPhase Phase,
    string? StatusText,
    bool CanOpen)
{
    public static GoalFinalVideoSnapshot Idle(string? goalId, string? productionJobId) =>
        new(goalId, productionJobId, GoalFinalVideoPhase.Idle, null, CanOpen: false);
}

/// <summary>仅观察当前 Goal 的 production_ready，并非阻塞派生一个本地最终视频。</summary>
public sealed class GoalFinalVideoCoordinator : IGoalFinalVideoObserver, IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly IFinalVideoAssembler _assembler;
    private readonly IFinalVideoLauncher _launcher;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly HashSet<string> _runningJobs = new(StringComparer.Ordinal);
    private readonly HashSet<string> _failedJobs = new(StringComparer.Ordinal);
    private readonly Dictionary<string, FinalVideoArtifact> _artifacts = new(StringComparer.Ordinal);
    private readonly HashSet<Task> _tasks = [];
    private GoalFinalVideoSnapshot _current = GoalFinalVideoSnapshot.Idle(null, null);
    private bool _disposed;

    public GoalFinalVideoCoordinator(
        IFinalVideoAssembler assembler,
        IFinalVideoLauncher launcher)
    {
        _assembler = assembler ?? throw new ArgumentNullException(nameof(assembler));
        _launcher = launcher ?? throw new ArgumentNullException(nameof(launcher));
    }

    public static GoalFinalVideoCoordinator Create(ControlCenterSession session) =>
        new(FinalVideoAssemblyService.Create(session), new ShellFinalVideoLauncher());

    public GoalFinalVideoSnapshot CurrentSnapshot
    {
        get
        {
            lock (_gate)
            {
                return _current;
            }
        }
    }

    public GoalFinalVideoSnapshot Observe(
        string? goalId,
        GoalVideoContinuationRecord? continuation)
    {
        string? jobToStart = null;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            var valid = continuation is not null
                && !string.IsNullOrWhiteSpace(goalId)
                && string.Equals(goalId, continuation.GoalId, StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(continuation.ProductionJobId);
            var productionJobId = valid ? continuation!.ProductionJobId : null;
            if (!string.Equals(_current.GoalId, goalId, StringComparison.Ordinal)
                || !string.Equals(_current.ProductionJobId, productionJobId, StringComparison.Ordinal))
            {
                _current = GoalFinalVideoSnapshot.Idle(goalId, productionJobId);
            }
            if (!valid
                || productionJobId is null
                || !string.Equals(continuation!.ProductionStatus, "production_ready", StringComparison.Ordinal))
            {
                return _current;
            }
            if (_artifacts.ContainsKey(productionJobId))
            {
                _current = Ready(goalId!, productionJobId);
                return _current;
            }
            if (_failedJobs.Contains(productionJobId))
            {
                _current = Failed(goalId!, productionJobId);
                return _current;
            }
            if (_runningJobs.Contains(productionJobId))
            {
                _current = Assembling(goalId!, productionJobId);
                return _current;
            }

            _runningJobs.Add(productionJobId);
            _current = Assembling(goalId!, productionJobId);
            jobToStart = productionJobId;
        }

        if (jobToStart is not null)
        {
            StartBackgroundAssembly(goalId!, jobToStart);
        }
        return CurrentSnapshot;
    }

    public bool OpenCurrent()
    {
        string? path = null;
        lock (_gate)
        {
            if (_disposed
                || _current is not { Phase: GoalFinalVideoPhase.Ready, ProductionJobId: not null } snapshot
                || !_artifacts.TryGetValue(snapshot.ProductionJobId, out var artifact)
                || !ProductionLocalEnvironment.IsOrdinaryFile(artifact.FilePath))
            {
                return false;
            }
            path = artifact.FilePath;
        }
        try
        {
            _launcher.Open(path);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private void StartBackgroundAssembly(string goalId, string productionJobId)
    {
        Task task;
        lock (_gate)
        {
            if (_disposed)
            {
                _runningJobs.Remove(productionJobId);
                return;
            }
            task = Task.Run(
                () => AssembleCoreAsync(goalId, productionJobId, _lifetime.Token),
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

    private async Task AssembleCoreAsync(
        string goalId,
        string productionJobId,
        CancellationToken cancellationToken)
    {
        try
        {
            var artifact = await _assembler.AssembleAsync(productionJobId, cancellationToken)
                .ConfigureAwait(false);
            lock (_gate)
            {
                _artifacts[productionJobId] = artifact;
                if (!_disposed && IsCurrent(goalId, productionJobId))
                {
                    _current = Ready(goalId, productionJobId);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // App shutdown owns cancellation; source and durable Core facts remain untouched.
        }
        catch (Exception)
        {
            lock (_gate)
            {
                _failedJobs.Add(productionJobId);
                if (!_disposed && IsCurrent(goalId, productionJobId))
                {
                    _current = Failed(goalId, productionJobId);
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

    private static GoalFinalVideoSnapshot Assembling(string goalId, string productionJobId) =>
        new(goalId, productionJobId, GoalFinalVideoPhase.Assembling, "正在合成最终视频", CanOpen: false);

    private static GoalFinalVideoSnapshot Ready(string goalId, string productionJobId) =>
        new(goalId, productionJobId, GoalFinalVideoPhase.Ready, "最终视频已就绪", CanOpen: true);

    private static GoalFinalVideoSnapshot Failed(string goalId, string productionJobId) =>
        new(
            goalId,
            productionJobId,
            GoalFinalVideoPhase.Failed,
            "最终视频合成失败；源文件和 Core 事实未被修改。",
            CanOpen: false);

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
            // Expected during app shutdown.
        }
        _lifetime.Dispose();
    }
}

public sealed class ShellFinalVideoLauncher : IFinalVideoLauncher
{
    public void Open(string verifiedFinalVideoPath)
    {
        if (!ProductionLocalEnvironment.IsOrdinaryFile(verifiedFinalVideoPath))
        {
            throw new FileNotFoundException("FINAL_VIDEO_NOT_AVAILABLE");
        }
        _ = Process.Start(new ProcessStartInfo
        {
            FileName = verifiedFinalVideoPath,
            UseShellExecute = true,
        }) ?? throw new InvalidOperationException("FINAL_VIDEO_OPEN_FAILED");
    }
}
