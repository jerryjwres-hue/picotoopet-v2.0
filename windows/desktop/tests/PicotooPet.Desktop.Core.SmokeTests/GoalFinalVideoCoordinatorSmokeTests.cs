using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 production_ready 到本地最终视频的非阻塞、去重、切 Goal 与显式打开边界。</summary>
internal static class GoalFinalVideoCoordinatorSmokeTests
{
    public static async Task RunAsync()
    {
        await StartsOnlyCurrentReadyJobWithoutBlockingOrDuplicatingAsync().ConfigureAwait(false);
        await GoalSwitchIgnoresStaleCompletionAndOpenRequiresClickAsync().ConfigureAwait(false);
        await FailureIsBoundedAsync().ConfigureAwait(false);
        await DisposeCancelsActiveAssemblyAsync().ConfigureAwait(false);
    }

    private static async Task StartsOnlyCurrentReadyJobWithoutBlockingOrDuplicatingAsync()
    {
        var assembler = new ControlledAssembler();
        var launcher = new RecordingLauncher();
        await using var coordinator = new GoalFinalVideoCoordinator(assembler, launcher);

        foreach (var status in new[] { "Ready", "Claimed", "Rendering", "Failed", "Cancelled", "NeedsHuman" })
        {
            _ = coordinator.Observe("goal-1", Continuation("goal-1", $"job-{status}", status));
        }
        SmokeAssert.Equal(0, assembler.CallCount, "非 production_ready 状态启动了最终合成");

        var stopwatch = Stopwatch.StartNew();
        var snapshot = coordinator.Observe("goal-1", Continuation("goal-1", "job-ready", "production_ready"));
        stopwatch.Stop();
        SmokeAssert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(1), "Goal 刷新等待了完整最终合成");
        SmokeAssert.Equal(GoalFinalVideoPhase.Assembling, snapshot.Phase, "production_ready 未进入最终合成");
        await assembler.WaitForCallsAsync(1).ConfigureAwait(false);
        _ = coordinator.Observe("goal-1", Continuation("goal-1", "job-ready", "production_ready"));
        SmokeAssert.Equal(1, assembler.CallCount, "重复 Goal 刷新启动了重复最终合成");

        _ = coordinator.Observe("goal-other", Continuation("goal-mismatch", "job-mismatch", "production_ready"));
        SmokeAssert.Equal(1, assembler.CallCount, "Goal 绑定不匹配仍启动最终合成");
    }

    private static async Task GoalSwitchIgnoresStaleCompletionAndOpenRequiresClickAsync()
    {
        var artifactRoot = Path.Combine(Path.GetTempPath(), $"picotoopet-final-open-{Guid.NewGuid():N}");
        Directory.CreateDirectory(artifactRoot);
        var artifact = Artifact("job-old", artifactRoot);
        var assembler = new ControlledAssembler();
        var launcher = new RecordingLauncher();
        try
        {
            await using var coordinator = new GoalFinalVideoCoordinator(assembler, launcher);
            _ = coordinator.Observe("goal-old", Continuation("goal-old", "job-old", "production_ready"));
            await assembler.WaitForCallsAsync(1).ConfigureAwait(false);
            _ = coordinator.Observe("goal-new", null);
            assembler.CompleteNext(artifact);
            await Task.Delay(50).ConfigureAwait(false);
            SmokeAssert.Equal("goal-new", coordinator.CurrentSnapshot.GoalId, "旧 Goal 合成完成覆盖新 Goal UI");
            SmokeAssert.True(!coordinator.OpenCurrent(), "新 Goal 错误打开旧 Goal 成品");
            SmokeAssert.Equal(0, launcher.OpenCount, "合成完成时自动打开了本地成品");

            var ready = coordinator.Observe("goal-old", Continuation("goal-old", "job-old", "production_ready"));
            SmokeAssert.Equal(GoalFinalVideoPhase.Ready, ready.Phase, "回到原 Goal 未恢复已验证成品");
            SmokeAssert.True(ready.CanOpen, "已验证最终成品没有启用打开动作");
            SmokeAssert.Equal(0, launcher.OpenCount, "观察 ready 状态自动打开了本地成品");
            SmokeAssert.True(coordinator.OpenCurrent(), "显式用户动作未打开已验证成品");
            SmokeAssert.Equal(1, launcher.OpenCount, "显式打开调用次数错误");
        }
        finally
        {
            Directory.Delete(artifactRoot, recursive: true);
        }
    }

    private static async Task FailureIsBoundedAsync()
    {
        var assembler = new ControlledAssembler();
        assembler.FailNext(new InvalidOperationException(@"C:\secret\raw-path token-value"));
        await using var coordinator = new GoalFinalVideoCoordinator(assembler, new RecordingLauncher());
        _ = coordinator.Observe("goal-fail", Continuation("goal-fail", "job-fail", "production_ready"));
        await WaitUntilAsync(() => coordinator.CurrentSnapshot.Phase == GoalFinalVideoPhase.Failed).ConfigureAwait(false);
        var status = coordinator.CurrentSnapshot.StatusText ?? string.Empty;
        SmokeAssert.True(status.Contains("最终视频", StringComparison.Ordinal), "失败状态缺少有界最终视频语义");
        SmokeAssert.True(!status.Contains("secret", StringComparison.OrdinalIgnoreCase), "失败状态泄露原始异常路径");
        _ = coordinator.Observe("goal-fail", Continuation("goal-fail", "job-fail", "production_ready"));
        SmokeAssert.Equal(1, assembler.CallCount, "失败后每次刷新热重试最终合成");
    }

    private static async Task DisposeCancelsActiveAssemblyAsync()
    {
        var assembler = new ControlledAssembler();
        var coordinator = new GoalFinalVideoCoordinator(assembler, new RecordingLauncher());
        _ = coordinator.Observe("goal-dispose", Continuation("goal-dispose", "job-dispose", "production_ready"));
        await assembler.WaitForCallsAsync(1).ConfigureAwait(false);
        await coordinator.DisposeAsync().ConfigureAwait(false);
        SmokeAssert.True(assembler.CancellationObserved, "coordinator dispose 未取消活动最终合成");
    }

    private static GoalVideoContinuationRecord Continuation(string goalId, string jobId, string status) => new(
        goalId, new string('a', 64), new string('b', 64), "creative-job",
        "11111111-1111-4111-8111-111111111111", new string('c', 64),
        "creative_ready", jobId, status);

    private static FinalVideoArtifact Artifact(string jobId, string root)
    {
        var videoPath = Path.Combine(root, $"{jobId}.mp4");
        var manifestPath = Path.Combine(root, $"{jobId}.final-video.json");
        File.WriteAllBytes(videoPath, "verified-final-video"u8.ToArray());
        File.WriteAllText(manifestPath, "{}");
        return new FinalVideoArtifact(
            jobId,
            "package-1",
            new string('b', 64),
            videoPath,
            manifestPath,
            new string('d', 64),
            new FileInfo(videoPath).Length,
            Reused: false);
    }

    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(3);
        while (!condition() && DateTimeOffset.UtcNow < deadline)
        {
            await Task.Delay(10).ConfigureAwait(false);
        }
        SmokeAssert.True(condition(), "等待最终视频异步状态超时");
    }

    private sealed class ControlledAssembler : IFinalVideoAssembler
    {
        private readonly ConcurrentQueue<TaskCompletionSource<FinalVideoArtifact>> _pending = new();
        private readonly ConcurrentQueue<Exception> _failures = new();
        private int _callCount;

        public int CallCount => Volatile.Read(ref _callCount);
        public bool CancellationObserved { get; private set; }

        public void FailNext(Exception exception) => _failures.Enqueue(exception);

        public async Task<FinalVideoArtifact> AssembleAsync(
            string productionJobId,
            CancellationToken cancellationToken = default)
        {
            Interlocked.Increment(ref _callCount);
            if (_failures.TryDequeue(out var failure))
            {
                throw failure;
            }
            var pending = new TaskCompletionSource<FinalVideoArtifact>(TaskCreationOptions.RunContinuationsAsynchronously);
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

        public void CompleteNext(FinalVideoArtifact artifact)
        {
            if (!_pending.TryDequeue(out var pending))
            {
                throw new InvalidOperationException("没有等待中的最终合成");
            }
            pending.SetResult(artifact);
        }

        public async Task WaitForCallsAsync(int count)
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(3);
            while (CallCount < count && DateTimeOffset.UtcNow < deadline)
            {
                await Task.Delay(10).ConfigureAwait(false);
            }
            SmokeAssert.Equal(count, CallCount, "最终合成调用次数未达到预期");
        }
    }

    private sealed class RecordingLauncher : IFinalVideoLauncher
    {
        public int OpenCount { get; private set; }

        public void Open(string verifiedFinalVideoPath)
        {
            OpenCount++;
        }
    }
}
