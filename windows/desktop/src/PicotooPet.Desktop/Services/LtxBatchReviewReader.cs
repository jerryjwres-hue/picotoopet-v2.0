using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.Desktop.Services;

public sealed record LtxShotReview(string ShotId, string StatusText, string? LocalPath)
{
    public bool CanPlay => LocalPath is not null;
}

public sealed record LtxBatchReview(IReadOnlyList<LtxShotReview> Shots, string? RoughCutPath, string Summary)
{
    public bool CanPlayRoughCut => RoughCutPath is not null;
}

public interface ILtxCandidateReviewGateway
{
    Task<LtxBatchReview> ReadLtxBatchReviewAsync(ReferenceBatchReceipt receipt,
        IReadOnlyList<string> shotIds, CancellationToken cancellationToken);
}

/// <summary>Recover the current exact reviewed batch using existing Core jobs; no GPU or new records.</summary>
internal static class LtxBatchReviewReader
{
    internal static async Task<LtxBatchReview> ReadAsync(ControlCenterSession session,
        ReferenceBatchReceipt receipt, IReadOnlyList<string> shotIds, CancellationToken ct)
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
        using var core = session.CreateWorkerChallengePreflightClient();
        var jobs = new List<ProductionJobRecord>();
        var shots = new List<LtxShotReview>();
        var probe = new FinalVideoQaMediaProbe(new FixedMasterVideoProcessRunner());
        foreach (var id in selected)
        {
            ct.ThrowIfCancellationRequested();
            var index = Array.IndexOf(shotIds.ToArray(), id);
            var key = "reviewed-ltx-pilot-v12-" + receipt.ApprovalId + "-" + receipt.ApprovalRequestDigest;
            if (full) key += "-shot-" + (index + 1);
            var listedJob = listed.SingleOrDefault(job => job.IdempotencyKey == key);
            if (listedJob is null)
            {
                shots.Add(new(id, "未找到已冻结任务", null));
                continue;
            }
            var job = await session.GetProductionJobAsync(listedJob.ProductionJobId, ct).ConfigureAwait(false);
            if (job.ProductionJobId != listedJob.ProductionJobId || job.PlanDigest != listedJob.PlanDigest
                || job.IdempotencyKey != key || job.ProductionProfile != "production.ltx.desktop.local.v1"
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
        return new(shots.AsReadOnly(), rough, rough is not null
            ? "三镜头候选影片已核验，可播放；正式交付与视觉审核尚未通过。"
            : $"已核验 {jobs.Count}/{selected.Length} 个镜头；完整候选影片尚未就绪。");
    }

    private static bool CanonicalId(string value) =>
        Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty && id.ToString("D") == value;
}
