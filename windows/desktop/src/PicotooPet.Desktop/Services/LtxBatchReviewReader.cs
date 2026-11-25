using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;
using PicotooPet.Desktop.Services.QualityObservation;

namespace PicotooPet.Desktop.Services;

public sealed record LtxShotReview(string ShotId, string StatusText, string? LocalPath,
    bool CanReroll = false)
{
    public bool CanPlay => LocalPath is not null;
}

public sealed record LtxBatchReview(IReadOnlyList<LtxShotReview> Shots, string? RoughCutPath, string Summary,
    VisualObservationResult? Observation = null)
{
    public bool CanPlayRoughCut => RoughCutPath is not null;
}

public interface ILtxCandidateReviewGateway
{
    Task<LtxBatchReview> ReadLtxBatchReviewAsync(ReferenceBatchReceipt receipt,
        IReadOnlyList<string> shotIds, CancellationToken cancellationToken);
    Task<LtxBatchReview> ObserveLtxBatchAsync(ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds,
        bool localVlm, CancellationToken cancellationToken);
    Task RerollLtxShotAsync(ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds,
        string shotId, string variant, CancellationToken cancellationToken);
}

/// <summary>Recover the current exact reviewed batch using existing Core jobs; no GPU or new records.</summary>
internal static class LtxBatchReviewReader
{
    internal static async Task<LtxBatchReview> ReadAsync(ControlCenterSession session,
        ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds, CancellationToken ct)
        => await ReadCoreAsync(session, receipt, shotIds, false, false, ct).ConfigureAwait(false);

    internal static Task<LtxBatchReview> ObserveAsync(ControlCenterSession session,
        ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds, bool localVlm, CancellationToken ct)
        => ReadCoreAsync(session, receipt, shotIds, true, localVlm, ct);

    private static async Task<LtxBatchReview> ReadCoreAsync(ControlCenterSession session,
        ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds, bool observe, bool localVlm, CancellationToken ct)
    {
        if (receipt.RightsScope != ReferenceBatchValidation.LtxRightsScope
            || receipt.References.Length is not (1 or 3) || shotIds.Count != 3
            || shotIds.Distinct(StringComparer.Ordinal).Count() != 3)
            throw new InvalidDataException("LTX_REVIEW_SCOPE_INVALID");
        var full = receipt.References.Length == 3;
        var selected = shotIds.Where(id => receipt.References.Any(r => r.ShotId == id)).ToArray();
        if (selected.Length != receipt.References.Length || (!full && selected[0] != shotIds[0]))
            throw new InvalidDataException("LTX_REVIEW_SCOPE_INVALID");

        // 01. Stable keys recover the same jobs after reopening the desktop.
        //     No new freeze call, no guess at a local folder or latest MP4.
        var listed = await session.GetProductionJobsAsync(ct).ConfigureAwait(false);
        var active = full ? await CurrentBatchAsync(session, receipt, ct).ConfigureAwait(false) : null;
        using var core = session.CreateWorkerChallengePreflightClient();
        var jobs = new List<ProductionJobRecord>();
        var shots = new List<LtxShotReview>();
        var observationShots = new List<VisualObservationShot>();
        var probe = new FinalVideoQaMediaProbe(new FixedMasterVideoProcessRunner());
        foreach (var id in selected)
        {
            ct.ThrowIfCancellationRequested();
            var index = Array.IndexOf(shotIds.ToArray(), id);
            var key = "reviewed-ltx-pilot-v12-" + receipt.ApprovalId + "-" + receipt.ApprovalRequestDigest;
            if (full) key += "-shot-" + (index + 1);
            var listedJob = active is not null ? active[index]
                : listed.SingleOrDefault(job => job.IdempotencyKey == key);
            if (listedJob is null)
            {
                shots.Add(new(id, "未找到已冻结任务", null));
                continue;
            }
            var job = await session.GetProductionJobAsync(listedJob.ProductionJobId, ct).ConfigureAwait(false);
            if (job.ProductionJobId != listedJob.ProductionJobId || job.PlanDigest != listedJob.PlanDigest
                || job.IdempotencyKey != (active is null ? key : listedJob.IdempotencyKey)
                || job.ProductionProfile != "production.ltx.desktop.local.v1"
                || job.CreativePackageId != receipt.CreativePackageId || job.CreativePackageDigest != receipt.CreativePackageDigest
                || job.ProjectKey != "goal-" + receipt.GoalId)
                throw new InvalidDataException("LTX_REVIEW_JOB_MISMATCH");

            if (!LtxProductionExecutor.IsCandidateSettled(job))
            {
                shots.Add(new(id, LtxProductionExecutor.IsSelected(job) ? "已冻结，等待生产"
                    : job.Status == "Rendering" ? "生成中或待恢复" : "未完成，需检查任务", null));
                continue;
            }
            var plan = await core.GetLtxPlanAsync(job.ProductionJobId, ct).ConfigureAwait(false);
            var bound = LtxProductionExecutor.ValidatePlan(job, plan, allowSettled: true);
            var reference = receipt.References.Single(r => r.ShotId == id);
            if (bound.ShotId != id || bound.AssetId != reference.AssetId
                || bound.ApprovalId != receipt.ApprovalId || bound.ApprovalRequestDigest != receipt.ApprovalRequestDigest
                || bound.Sha256 != reference.Sha256 || bound.Bytes != reference.Bytes
                || bound.InputRelativePath != reference.InputRelativePath
                || bound.SourceReference != reference.SourceReference || bound.SourceDigest != reference.SourceDigest)
                throw new InvalidDataException("LTX_REVIEW_REFERENCE_MISMATCH");

            // 02. Only the exact settled candidate can be played. The local
            //     file is hashed and decoded again, using the existing probe.
            var candidate = await core.GetLtxCandidateAsync(job.ProductionJobId, ct).ConfigureAwait(false);
            FinalVideoQaMediaProbe.RejectDuplicates(candidate);
            string Text(string field) => candidate.GetProperty(field).GetString() ?? "";
            var generation = Text("generation_id");
            var video = Text("video_asset_id");
            var relative = Text("output_relpath");
            if (Text("schema_version") != "production.ltx.candidate.v1"
                || Text("production_job_id") != job.ProductionJobId || Text("plan_digest") != job.PlanDigest
                || Text("production_task_id") != bound.ProductionTaskId
                || Text("job_status") != "NeedsHuman" || Text("lane") != "local" || Text("mime_type") != "video/mp4"
                || !candidate.GetProperty("decode_verified").GetBoolean() || !candidate.GetProperty("review_required").GetBoolean()
                || candidate.GetProperty("mac_bytes_verified").GetBoolean()
                || !CanonicalId(generation) || !CanonicalId(video)
                || relative != $"PicotooPet/ltx/{job.ProductionJobId}/{bound.ProductionTaskId}/{generation}-video-{video}.mp4")
                throw new InvalidDataException("LTX_REVIEW_CANDIDATE_MISMATCH");
            var root = ProductionLocalEnvironment.ResolveComfyOutputRoot();
            var path = ProductionLocalEnvironment.ResolveUnderRoot(root, relative, true);
            ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(root)!, path);
            var measured = await probe.VerifyLtxCandidateAsync(path, Text("output_sha256"),
                candidate.GetProperty("output_bytes").GetInt64(), ct).ConfigureAwait(false);
            if (measured != new LtxCandidateMediaFacts(candidate.GetProperty("width").GetInt32(),
                candidate.GetProperty("height").GetInt32(), candidate.GetProperty("frame_count").GetInt32(),
                candidate.GetProperty("fps").GetInt32(), candidate.GetProperty("duration_ms").GetInt32()))
                throw new InvalidDataException("LTX_REVIEW_MEDIA_MISMATCH");
            jobs.Add(job);
            shots.Add(new(id, "技术核验通过，待视觉审核", path));
            // 05. Preserve exact source identity from the persisted receipt.
            //     The older observer has a 1000-character advisory action budget.
            var action = plan.GetProperty("prompt").GetString() ?? "";
            if (action.Length > 1000) action = "See frozen production plan; action exceeds observer text budget.";
            observationShots.Add(new(index + 1, id, bound.ProductionTaskId, relative,
                Text("output_sha256"), candidate.GetProperty("output_bytes").GetInt64(),
                measured.FrameCount, measured.DurationMs, action));
        }
        // 03. Reuse the exact existing rough-cut manifest verifier. Reading
        //     never creates a missing rough cut, even when all shots are ready.
        string? rough = null;
        if (full && jobs.Count == 3)
        {
            var identity = ProductionSubmissionJournal.Hash(string.Join("\n", jobs.Select(job =>
                job.ProductionJobId + ":" + job.PlanDigest)));
            rough = await LtxRoughCutAssembly.AssembleAsync(session, jobs, identity, ct, readOnly: true)
                .ConfigureAwait(false);
        }
        // 04. Enable reroll only when the active exact batch is fully
        //     settled and its immutable rough cut exists.
        if (active is not null && rough is not null && receipt.Status == "Approved"
            && receipt.ExpiresAt > DateTimeOffset.UtcNow)
            shots = shots.Select(shot => shot with { CanReroll = shot.CanPlay }).ToList();
        VisualObservationResult? observation = null;
        if (observe && rough is not null && observationShots.Count == 3)
        {
            // 06. Never invent a legacy PASS package. Evidence is bound to
            //     the three current candidate IDs and exact plan digests.
            observation = await LtxVisualObservation.ObserveAsync(jobs, observationShots,
                localVlm, ct).ConfigureAwait(false);
            var current = await CurrentBatchAsync(session, receipt, ct).ConfigureAwait(false);
            if (active is not null && (current is null || !current.Select(job => job.ProductionJobId)
                    .SequenceEqual(jobs.Select(job => job.ProductionJobId))))
                observation = VisualReviewObservation.Unverified("审片期间批次改变；旧证据不能代表当前影片。");
        }
        return new(shots.AsReadOnly(), rough, observation is not null ? observation.Detail : rough is not null
            ? "三镜头候选影片已核验，可播放；正式交付与视觉审核尚未通过。"
            : $"已核验 {jobs.Count}/{selected.Length} 个镜头；完整候选影片尚未就绪。", observation);
    }

    internal static async Task RerollAsync(ControlCenterSession session, ReferenceBatchReceipt receipt,
        IReadOnlyList<string> shotIds, string shotId, string variant, CancellationToken ct)
    {
        // 01. Only a complete active batch may replace one shot. Preserve
        //     its other two settled jobs and all previous candidate files.
        if (receipt.Status != "Approved" || receipt.ExpiresAt <= DateTimeOffset.UtcNow
            || receipt.References.Length != 3 || shotIds.Count != 3 || !CanonicalId(variant))
            throw new InvalidDataException("LTX_REROLL_APPROVAL_REQUIRED");
        var index = Array.IndexOf(shotIds.ToArray(), shotId);
        if (index < 0) throw new InvalidDataException("LTX_REROLL_SHOT_INVALID");
        var previous = await CurrentBatchAsync(session, receipt, ct).ConfigureAwait(false)
            ?? throw new InvalidDataException("LTX_REROLL_ACTIVE_BATCH_REQUIRED");
        if (previous.Any(job => !LtxProductionExecutor.IsCandidateSettled(job)))
            throw new InvalidDataException("LTX_REROLL_BATCH_NOT_SETTLED");
        var current = await ReadAsync(session, receipt, shotIds, ct).ConfigureAwait(false);
        if (current.RoughCutPath is null || !current.Shots.Any(shot => shot.ShotId == shotId && shot.CanReroll))
            throw new InvalidDataException("LTX_REROLL_ROUGH_CUT_REQUIRED");

        // 02. Anchor every reroll to the original job for this position,
        //     not an unbounded chain. The same per-click variant is idempotent.
        var sourceId = P0ThreeShotAcceptanceGate.TryRerollOrigin(previous[index].IdempotencyKey, out var origin)
            ? origin : previous[index].ProductionJobId;
        using var core = session.CreateWorkerChallengePreflightClient();
        var key = $"reviewed-ltx-reroll-v12-{sourceId}-{variant}";
        var replacement = await core.FreezeLtxPilotAsync(receipt.CreativePackageId, receipt.ApprovalId,
            key, ct, shotId, sourceId, variant).ConfigureAwait(false);
        if (replacement.IdempotencyKey != key || replacement.CreativePackageId != receipt.CreativePackageId
            || replacement.CreativePackageDigest != receipt.CreativePackageDigest
            || replacement.ProjectKey != "goal-" + receipt.GoalId)
            throw new InvalidDataException("LTX_REROLL_JOB_MISMATCH");
        var plan = await core.GetLtxPlanAsync(replacement.ProductionJobId, ct).ConfigureAwait(false);
        var bound = LtxProductionExecutor.ValidatePlan(replacement, plan);
        var expected = receipt.References.Single(reference => reference.ShotId == shotId);
        if (bound.ShotId != shotId || bound.ApprovalId != receipt.ApprovalId
            || bound.ApprovalRequestDigest != receipt.ApprovalRequestDigest || bound.AssetId != expected.AssetId
            || bound.Sha256 != expected.Sha256 || bound.Bytes != expected.Bytes
            || bound.InputRelativePath != expected.InputRelativePath
            || bound.SourceReference != expected.SourceReference || bound.SourceDigest != expected.SourceDigest)
            throw new InvalidDataException("LTX_REROLL_REFERENCE_MISMATCH");
        ct.ThrowIfCancellationRequested();
        // 03. Compare-and-swap the exact old batch under the existing GPU
        //     lock. A failure leaves only an inert, frozen replacement job.
        P0ThreeShotAcceptanceGate.ReplaceSettledLtxShot(previous, index, replacement);
    }

    private static async Task<IReadOnlyList<ProductionJobRecord>?> CurrentBatchAsync(
        ControlCenterSession session, ReferenceBatchReceipt receipt, CancellationToken ct)
    {
        var active = await P0ThreeShotAcceptanceGate.ReadActiveLtxBatchAsync(session, ct).ConfigureAwait(false);
        if (active is null || active.Count != 3 || active.Any(job => job.CreativePackageId != receipt.CreativePackageId
            || job.CreativePackageDigest != receipt.CreativePackageDigest || job.ProjectKey != "goal-" + receipt.GoalId))
            return null;
        using var core = session.CreateWorkerChallengePreflightClient();
        for (var index = 0; index < active.Count; index++)
        {
            var job = active[index];
            var plan = await core.GetLtxPlanAsync(job.ProductionJobId, ct).ConfigureAwait(false);
            var reference = LtxProductionExecutor.ValidatePlan(job, plan, allowSettled: true, allowRendering: true);
            if (reference.ApprovalId != receipt.ApprovalId || reference.ApprovalRequestDigest != receipt.ApprovalRequestDigest)
                return null;
        }
        return active;
    }

    private static bool CanonicalId(string value) =>
        Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty && id.ToString("D") == value;
}
