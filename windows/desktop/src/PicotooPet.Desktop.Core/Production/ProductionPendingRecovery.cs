using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>HasPending forbids fresh GPU work, including when waiting for a lease or draining terminal work.</summary>
public sealed record ProductionPendingRecoveryResult(bool HasPending, string? RecoverableJobId);

/// <summary>Shared by the approved same-EXE host. No window, scheduling loop, credentials or second renderer.</summary>
public sealed class ProductionPendingRecovery(ProductionSubmissionJournal journal, IComfyPromptReconciler reconciler,
    Func<string, CancellationToken, Task<ProductionJobRecord>> getExactJob)
{
    public async Task<ProductionPendingRecoveryResult> ReconcileAsync(CancellationToken ct = default)
    {
        using var gpu = journal.AcquireGpu();
        var pending = journal.Pending();
        if (pending.Count == 0) return new(false, null);
        string? recover = null;
        foreach (var group in pending.GroupBy(p => p.JobId, StringComparer.Ordinal))
        {
            var job = await getExactJob(group.Key, ct).ConfigureAwait(false);
            if (job.ProductionJobId != group.Key) throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
            if (job.Status is "Cancelled" or "Failed" or "NeedsHuman" or "production_ready")
            {
                foreach (var item in group)
                    await ReconcileTerminalAsync(journal, reconciler, item, ct).ConfigureAwait(false);
            }
            else if (job.Status is "Ready" or "Claimed" or "Rendering")
            {
                if (job.LeaseExpiresAt > DateTimeOffset.UtcNow) return new(true, null);
                if (recover is not null && recover != group.Key)
                    throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
                recover = group.Key;
            }
            else throw new ProductionWorkerException("MEDIA_PENDING_CORE_JOB_UNAVAILABLE");
        }
        return new(true, recover);
    }

    /// <summary>Caller holds AcquireGpu. Core terminal status is not evidence that CUDA has stopped.</summary>
    public static async Task ReconcileTerminalAsync(ProductionSubmissionJournal journal, IComfyPromptReconciler reconciler,
        ProductionSubmission item, CancellationToken ct = default)
    {
        if (item.Phase == "Settled") return;
        if (item.Phase == "Prepared" && item.PromptId is null)
        { journal.Save(item with { Phase = "Settled" }); return; }
        var prompt = item.PromptId ?? await reconciler.FindExactAsync(item.GraphDigest, ct).ConfigureAwait(false);
        if (prompt is null) throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        item = item with { PromptId = prompt, Phase = item.Phase == "FailurePending" ? "FailurePending" : "Submitted" };
        journal.Save(item);
        if (!await reconciler.IsFinishedAsync(prompt, ct).ConfigureAwait(false))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        journal.Save(item with { Phase = "Settled" });
    }
}
