using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Goal continuation 到既有 Production executor 的非阻塞、去重和生命周期边界。</summary>
internal static class GoalProductionAutopilotCoordinatorSmokeTests
{
    public static async Task RunAsync()
    {
        await StartsReadyJobWithoutBlockingOrDuplicatingAsync().ConfigureAwait(false);
        await TerminalStatesNeverStartAsync().ConfigureAwait(false);
        await FailureIsBoundedAndLaterObservationRetriesAsync().ConfigureAwait(false);
        await GoalSwitchIgnoresStaleCompletionAsync().ConfigureAwait(false);
        await DisposeCancelsActiveRunAsync().ConfigureAwait(false);
    }

    private static async Task StartsReadyJobWithoutBlockingOrDuplicatingAsync()
    {
        var executor = new ControlledExecutor();
        await using var coordinator = new GoalProductionAutopilotCoordinator(executor);

        var stopwatch = Stopwatch.StartNew();
        var first = coordinator.Observe("goal-1", Continuation("goal-1", "job-1", "Ready"));
        stopwatch.Stop();
        SmokeAssert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(1), "Goal 刷新等待了完整 Production render");
        SmokeAssert.Equal(GoalProductionAutopilotPhase.Running, first.Phase, "Ready job 未进入本地自动执行");
        await executor.WaitForCallsAsync(1).ConfigureAwait(false);

        _ = coordinator.Observe("goal-1", Continuation("goal-1", "job-1", "Ready"));
        _ = coordinator.Observe("goal-1", Continuation("goal-1", "job-1", "Rendering"));
        SmokeAssert.Equal(1, executor.CallCount, "重复 5 秒观察启动了重复 executor");

        executor.CompleteNext(Package("job-1"));
        await WaitUntilAsync(() =>
            coordinator.CurrentSnapshot.Phase == GoalProductionAutopilotPhase.AwaitingCoreRefresh).ConfigureAwait(false);
        _ = coordinator.Observe("goal-1", Continuation("goal-1", "job-1", "Ready"));
        SmokeAssert.Equal(1, executor.CallCount, "成功后旧 Ready 投影重复启动 executor");
    }

    private static async Task TerminalStatesNeverStartAsync()
    {
        var executor = new ControlledExecutor();
        await using var coordinator = new GoalProductionAutopilotCoordinator(executor);
        foreach (var status in new[] { "production_ready", "Failed", "NeedsHuman", "Cancelled" })
        {
            var snapshot = coordinator.Observe(
                $"goal-{status}",
                Continuation($"goal-{status}", $"job-{status}", status));
            SmokeAssert.Equal(GoalProductionAutopilotPhase.Terminal, snapshot.Phase, $"终态 {status} 未映射为 Terminal");
        }
        _ = coordinator.Observe(
            "goal-current",
            Continuation("goal-other", "job-mismatched", "Ready"));
        SmokeAssert.Equal(0, executor.CallCount, "终态 Production job 被自动执行");
    }

    private static async Task FailureIsBoundedAndLaterObservationRetriesAsync()
    {
        const string secret = @"C:\secret\models\token-raw";
        var executor = new ControlledExecutor();
        executor.FailNext(new InvalidOperationException(secret));
        await using var coordinator = new GoalProductionAutopilotCoordinator(executor);

        _ = coordinator.Observe("goal-failure", Continuation("goal-failure", "job-failure", "Ready"));
        await WaitUntilAsync(() =>
            coordinator.CurrentSnapshot.Phase == GoalProductionAutopilotPhase.TemporaryFailure).ConfigureAwait(false);
        SmokeAssert.True(
            coordinator.CurrentSnapshot.StatusText?.Contains(secret, StringComparison.Ordinal) != true,
            "本地 Production 异常路径泄露到 Goal Center 状态");

        _ = coordinator.Observe("goal-failure", Continuation("goal-failure", "job-failure", "Ready"));
        SmokeAssert.Equal(1, executor.CallCount, "失败后的第一次状态展示立即热重试");
        _ = coordinator.Observe("goal-failure", Continuation("goal-failure", "job-failure", "Ready"));
        await executor.WaitForCallsAsync(2).ConfigureAwait(false);
        SmokeAssert.Equal(2, executor.CallCount, "后续 Goal 刷新未允许本地条件修复后重试");
        SmokeAssert.True(
            coordinator.CurrentSnapshot.Phase != GoalProductionAutopilotPhase.AwaitingCoreRefresh,
            "失败重试伪造了 Production 成功");
    }

    private static async Task GoalSwitchIgnoresStaleCompletionAsync()
    {
        var executor = new ControlledExecutor();
        await using var coordinator = new GoalProductionAutopilotCoordinator(executor);
        _ = coordinator.Observe("goal-old", Continuation("goal-old", "job-old", "Ready"));
        await executor.WaitForCallsAsync(1).ConfigureAwait(false);

        _ = coordinator.Observe("goal-new", null);
        executor.CompleteNext(Package("job-old"));
        await Task.Delay(50).ConfigureAwait(false);
        SmokeAssert.Equal("goal-new", coordinator.CurrentSnapshot.GoalId, "旧 Goal 完成覆盖了新 Goal 状态");
        SmokeAssert.True(coordinator.CurrentSnapshot.ProductionJobId is null, "旧 Production job 泄漏到新 Goal");
    }

    private static async Task DisposeCancelsActiveRunAsync()
    {
        var executor = new ControlledExecutor();
        var coordinator = new GoalProductionAutopilotCoordinator(executor);
        _ = coordinator.Observe("goal-dispose", Continuation("goal-dispose", "job-dispose", "Ready"));
        await executor.WaitForCallsAsync(1).ConfigureAwait(false);
        await coordinator.DisposeAsync().ConfigureAwait(false);
        SmokeAssert.True(executor.CancellationObserved, "coordinator dispose 未取消活动 Production run");
    }

    private static GoalVideoContinuationRecord Continuation(string goalId, string jobId, string status) => new(
        goalId, new string('a', 64), new string('b', 64), "creative-job",
        "11111111-1111-4111-8111-111111111111", new string('c', 64),
        "creative_ready", jobId, status);

    private static ProductionPackageRecord Package(string jobId) => new(
        "package-1", jobId, "creative-package", new string('d', 64), new string('e', 64),
        "production/package.json", JsonDocument.Parse("{}").RootElement.Clone(), "PASS", DateTimeOffset.UtcNow);

    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(3);
        while (!condition() && DateTimeOffset.UtcNow < deadline)
        {
            await Task.Delay(10).ConfigureAwait(false);
        }
        SmokeAssert.True(condition(), "等待 autopilot 异步状态超时");
    }

    private sealed class ControlledExecutor : IProductionJobExecutor
    {
        private readonly ConcurrentQueue<TaskCompletionSource<ProductionPackageRecord>> _pending = new();
        private readonly ConcurrentQueue<Exception> _failures = new();
        private int _callCount;

        public int CallCount => Volatile.Read(ref _callCount);
        public bool CancellationObserved { get; private set; }

        public void FailNext(Exception exception) => _failures.Enqueue(exception);

        public async Task<ProductionPackageRecord> RunAsync(
            string productionJobId,
            CancellationToken cancellationToken = default)
        {
            Interlocked.Increment(ref _callCount);
            if (_failures.TryDequeue(out var failure))
            {
                throw failure;
            }
            var pending = new TaskCompletionSource<ProductionPackageRecord>(
                TaskCreationOptions.RunContinuationsAsynchronously);
            _pending.Enqueue(pending);
            try
            {
                return await pending.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                CancellationObserved = true;
                throw;
            }
        }

        public void CompleteNext(ProductionPackageRecord package)
        {
            if (!_pending.TryDequeue(out var pending))
            {
                throw new InvalidOperationException("没有等待中的 Production run");
            }
            pending.SetResult(package);
        }

        public async Task WaitForCallsAsync(int count)
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(3);
            while (CallCount < count && DateTimeOffset.UtcNow < deadline)
            {
                await Task.Delay(10).ConfigureAwait(false);
            }
            SmokeAssert.Equal(count, CallCount, "Production executor 调用次数未达到预期");
        }
    }
}
