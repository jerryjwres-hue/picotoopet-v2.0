using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker;

/// <summary>只消费现有 Core 作业，无第二套调度数据库；进程生命周期不依赖窗口。</summary>
public sealed class MediaWorkerHost(ProductionSubmissionJournal journal, IProductionJobExecutor executor,
    Func<CancellationToken, Task<ProductionJobRecord[]>> jobs, IComfyPromptReconciler reconciler,
    Action<string> status)
{
    public async Task RunAsync(CancellationToken stop)
    {
        using var singleton = journal.AcquireRuntime();
        while (!stop.IsCancellationRequested)
        {
            try { await TickAsync(stop).ConfigureAwait(false); }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            catch (ProductionWorkerException e) { status(e.Code); }
            catch (Exception) { status("MEDIA_API_OR_TOOL_UNAVAILABLE"); }
            try { await Task.Delay(TimeSpan.FromSeconds(5), stop).ConfigureAwait(false); }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
        }
        status("MEDIA_WORKER_STOPPED");
    }
    public async Task TickAsync(CancellationToken ct)
    {
        var pending = journal.Pending();
        var snapshot = await jobs(ct).ConfigureAwait(false);
        // Recover outstanding GPU work before considering any fresh job, even if Core has cancelled it.
        if (pending.Count > 0)
        {
            var jobId = pending[0].JobId;
            var job = snapshot.SingleOrDefault(j => j.ProductionJobId == jobId)
                ?? throw new ProductionWorkerException("MEDIA_PENDING_CORE_JOB_UNAVAILABLE");
            if (job.Status is "Cancelled" or "Failed" or "NeedsHuman" or "production_ready")
            {
                using var gpu = journal.AcquireGpu();
                foreach (var item in pending.Where(p => p.JobId == jobId))
                {
                    var prompt = item.PromptId;
                    if (prompt is null && item.Phase == "Prepared") { journal.Save(item with { Phase = "Settled" }); continue; }
                    prompt ??= await reconciler.FindExactAsync(item.GraphDigest, ct).ConfigureAwait(false);
                    if (prompt is null || !await reconciler.IsFinishedAsync(prompt, ct).ConfigureAwait(false))
                        throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
                    journal.Save(item with { PromptId = prompt, Phase = "Settled" });
                }
                return;
            }
            if (job.LeaseExpiresAt > DateTimeOffset.UtcNow) { status("MEDIA_WAITING_FOR_CORE_LEASE"); return; }
            await executor.RunAsync(jobId, ct).ConfigureAwait(false);
            return;
        }
        var eligible = snapshot.Where(j => j.Status is "Ready" or "Claimed" or "Rendering")
            .Where(j => j.LeaseExpiresAt is null || j.LeaseExpiresAt <= DateTimeOffset.UtcNow)
            .OrderBy(j => j.CreatedAt).FirstOrDefault();
        if (eligible is not null) await executor.RunAsync(eligible.ProductionJobId, ct).ConfigureAwait(false);
        else status("MEDIA_IDLE");
    }
}
