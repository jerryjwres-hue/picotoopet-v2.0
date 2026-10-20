using System.IO;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>窗口观察者退出不能取消独立 worker，重复 job/event 仍只有一次 /prompt。</summary>
internal static class HostTests
{
    public static async Task RunAsync()
    {
        using var f = new RecoveryTests.Fixture();
        f.Comfy.HoldOutput = true;
        using var stop = new CancellationTokenSource();
        await using var executor = f.Executor();
        var job = new ProductionJobRecord("job", "creative", new string('a',64), "project", "production.comfyui.v1", new string('b',64), "Ready",
            null, null, null, null, "idempotent", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        var jobs = new[] { job, job with { ProductionJobId = "job-2" } };
        using var http = new System.Net.Http.HttpClient(f.Comfy, false) { BaseAddress = ComfyProductionClient.FixedBaseAddress };
        using var reconcile = new ComfyPromptReconciler(http);
        var host = new MediaWorkerHost(f.Journal, executor, _ => Task.FromResult(jobs), reconcile, _ => { });
        var work = host.TickAsync(stop.Token);
        await f.Comfy.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var observer = new GoalProductionAutopilotCoordinator(new OnlyObserveExecutor(f.Gateway));
        var continuation = new GoalVideoContinuationRecord("goal", new string('a',64), new string('b',64), "creative-job", "creative", new string('a',64), "creative_ready", "job", "Ready");
        observer.Observe("goal", continuation); observer.Observe("goal", continuation);
        await observer.DisposeAsync();
        RecoveryTests.Assert(!work.IsCompleted && f.Comfy.Submits == 1, "UI disposal must not cancel independent executor");
        f.Comfy.HoldOutput = false;
        await work.WaitAsync(TimeSpan.FromSeconds(5));
        RecoveryTests.Assert(f.Gateway.Commits == 1, "result completes after UI teardown");
        jobs = [job with { Status = "production_ready" }];
        await host.TickAsync(stop.Token);
        RecoveryTests.Assert(f.Comfy.Submits == 1, "host must not rerun completed outputs");
        using var runtime = f.Journal.AcquireRuntime();
        await RecoveryTests.ThrowsCodeAsync("MEDIA_WORKER_BUSY", () => host.RunAsync(stop.Token));
        Console.WriteLine("MEDIA_WORKER_UI_TEARDOWN_HOST=PASS");
    }
    private sealed class OnlyObserveExecutor(RecoveryTests.FakeGateway gateway) : IProductionJobExecutor
    {
        public async Task<ProductionPackageRecord> RunAsync(string productionJobId, CancellationToken cancellationToken = default)
        {
            while (true)
            {
                var package = await gateway.GetProductionPackageAsync(productionJobId, cancellationToken);
                if (package is not null) return package;
                await Task.Delay(5, cancellationToken);
            }
        }
    }
}
