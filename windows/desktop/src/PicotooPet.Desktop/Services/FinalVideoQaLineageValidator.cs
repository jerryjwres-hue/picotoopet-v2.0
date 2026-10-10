using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

internal sealed record FinalQaVerifiedInput(FinalArtifactReceiptV1 Template, string CandidatePath, long Frames);

/// <summary>只读重验 Goal 到最终候选的完整身份链，不选择最新文件，不修复上游清单。</summary>
internal sealed class FinalVideoQaLineageValidator
{
    private readonly PostProductionMasterSourceVerifier _sources;
    private readonly PostProductionMasterArtifactCatalog _masters;
    internal FinalVideoQaLineageValidator(string finals, string narration, string overlays, string masters)
    {
        _sources = new(finals, narration, overlays);
        _masters = new(masters);
    }
    internal async Task<FinalQaVerifiedInput> VerifyAsync(FinalVideoQaInputV1 input, CancellationToken ct)
    {
        try
        {
            var goal = input.GoalContinuation;
            var job = input.ProductionJob;
            var plan = input.ProductionPlan;
            var package = input.ProductionPackage;
            var source = input.MasterInput;
            var n = source.NarrationPlan.Plan;
            var o = source.OverlayPlan.Plan;
            if (o.CaptionsRequired || o.Captions.Count != 0) throw new FinalVideoQaException("CAPTION_PROFILE_UNSUPPORTED");
            NarrationPlanContract.Validate(source.NarrationPlan);
            CaptionOverlayPlanParser.Validate(source.OverlayPlan);
            if (PostProductionMasterSourceVerifier.ComputeOverlayPlanDigest(o) != source.OverlayPlan.CaptionOverlayPlanDigest)
                throw new FinalVideoQaException("INPUT_INVALID");
            var planDigest = FinalQaIdentity.Hash(JsonSerializer.SerializeToNode(plan)!);
            if (goal.ProductionJobId != job.ProductionJobId || goal.ProductionStatus != "production_ready"
                || job.Status != "production_ready" || goal.CreativeStatus != "creative_ready"
                || goal.CreativePackageId != job.CreativePackageId || goal.CreativePackageDigest != job.CreativePackageDigest
                || plan.SchemaVersion != "1.0" || plan.ProductionJobId != job.ProductionJobId
                || plan.CreativePackageId != job.CreativePackageId || plan.CreativePackageDigest != job.CreativePackageDigest
                || plan.ProjectKey != job.ProjectKey || plan.ProductionProfile != job.ProductionProfile
                || package.ProductionJobId != job.ProductionJobId || package.CreativePackageId != job.CreativePackageId
                || package.QualityOutcome != "PASS" || planDigest != job.PlanDigest || planDigest != package.PlanDigest
                || planDigest != n.ProductionPlanDigest || planDigest != o.ProductionPlanDigest
                || n.ProductionJobId != job.ProductionJobId || o.ProductionJobId != job.ProductionJobId
                || n.CreativePackageId != job.CreativePackageId || o.CreativePackageId != job.CreativePackageId
                || n.CreativePackageDigest != job.CreativePackageDigest || o.CreativePackageDigest != job.CreativePackageDigest
                || source.C004.ProductionJobId != job.ProductionJobId || source.C004.ProductionPackageId != package.ProductionPackageId
                || source.C004.ProductionPackageDigest != package.PackageDigest
                || n.TargetRuntimeMs != plan.TargetRuntimeMs || o.TargetRuntimeMs != plan.TargetRuntimeMs || o.OutputProfileId != plan.OutputProfileId)
                throw new FinalVideoQaException("LINEAGE_MISMATCH");
            if (!FinalQaIdentity.Sha(goal.HandoffSha256) || !FinalQaIdentity.Sha(goal.ReturnSha256)
                || !FinalQaIdentity.Sha(package.PackageDigest) || !Id(goal.GoalId) || !Id(goal.CreativeJobId)
                || !Id(package.ProductionPackageId)) throw new FinalVideoQaException("INPUT_INVALID");
            var frames = ValidateTiming(plan);
            var required = n.NarrationRequired || o.OverlaysRequired;
            if (required && input.MasterArtifact is null) throw new FinalVideoQaException("MASTER_REQUIRED");
            if (!required && input.MasterArtifact is not null || !n.NarrationRequired && source.NarrationArtifact is not null
                || !o.OverlaysRequired && source.OverlayArtifact is not null)
                throw new FinalVideoQaException("INPUT_INVALID");
            var c004 = await _sources.VerifyFinalVideoAsync(source.C004, ct).ConfigureAwait(false);
            var c004ManifestSha = await ProductionLocalEnvironment.Sha256FileAsync(source.C004.ManifestPath, ct).ConfigureAwait(false);
            VerifiedNarrationSource? narration = n.NarrationRequired
                ? await _sources.VerifyNarrationAsync(source.NarrationArtifact!, source.NarrationPlan, ct).ConfigureAwait(false) : null;
            VerifiedOverlaySource? overlay = o.OverlaysRequired
                ? await _sources.VerifyOverlayAsync(source.OverlayArtifact!, source.C004, source.OverlayPlan, ct).ConfigureAwait(false) : null;
            var visual = overlay?.Visual ?? c004.Visual;
            var identity = new MasterIdentityFacts(job.ProductionJobId, package.ProductionPackageId, package.PackageDigest,
                planDigest, job.CreativePackageId, job.CreativePackageDigest, plan.TargetRuntimeMs, plan.OutputProfileId,
                n.NarrationRequired, source.NarrationPlan.NarrationPlanDigest, narration?.ManifestSha256,
                narration?.IdentitySegments ?? [], o.OverlaysRequired, source.OverlayPlan.CaptionOverlayPlanDigest,
                visual.SourceKind, visual.Sha256, visual.Bytes, c004.Visual.Sha256, c004.Visual.Bytes,
                overlay?.Visual.Sha256, overlay?.Visual.Bytes, overlay?.ManifestSha256);
            string? masterDigest = null, masterManifestSha = null;
            string candidate = c004.Visual.Path, sha = c004.Visual.Sha256;
            long bytes = c004.Visual.Bytes;
            if (required)
            {
                masterDigest = MasterInputIdentity.Compute(identity);
                var supplied = input.MasterArtifact!;
                if (supplied.MasterInputDigest != masterDigest || supplied.ProductionPlanDigest != planDigest)
                    throw new FinalVideoQaException("LINEAGE_MISMATCH");
                var exact = await _masters.FindVerifiedExactAsync(new(identity, masterDigest), ct).ConfigureAwait(false)
                    ?? throw new FinalVideoQaException("MASTER_REQUIRED");
                if (!string.Equals(Path.GetFullPath(exact.FilePath), Path.GetFullPath(supplied.FilePath), StringComparison.OrdinalIgnoreCase)
                    || !string.Equals(Path.GetFullPath(exact.ManifestPath), Path.GetFullPath(supplied.ManifestPath), StringComparison.OrdinalIgnoreCase)
                    || exact with { FilePath = "", ManifestPath = "", Reused = false }
                    != supplied with { FilePath = "", ManifestPath = "", Reused = false })
                    throw new FinalVideoQaException("LINEAGE_MISMATCH");
                candidate = exact.FilePath; sha = exact.Sha256; bytes = exact.Bytes;
                masterManifestSha = await ProductionLocalEnvironment.Sha256FileAsync(exact.ManifestPath, ct).ConfigureAwait(false);
            }
            var template = new FinalArtifactReceiptV1("1.0", FinalQaIdentity.Profile, "", "", "PASS",
                goal.GoalId, goal.HandoffSha256, goal.ReturnSha256, goal.CreativeJobId, goal.CreativePackageId, goal.CreativePackageDigest,
                job.ProductionJobId, planDigest, package.ProductionPackageId, package.PackageDigest, plan.TargetRuntimeMs, plan.OutputProfileId,
                n.NarrationRequired, source.NarrationPlan.NarrationPlanDigest, narration?.ManifestSha256, narration?.IdentitySegments ?? [],
                false, o.OverlaysRequired, source.OverlayPlan.CaptionOverlayPlanDigest, overlay?.Visual.Sha256, overlay?.Visual.Bytes, overlay?.ManifestSha256,
                c004ManifestSha, c004.Visual.Sha256, c004.Visual.Bytes,
                required ? "c009_master_v1" : "c004_fallback_v1", required ? "postproduction-master.local.v1" : "final-videos.local.v1",
                visual.SourceKind, visual.Sha256, visual.Bytes,
                required ? PostProductionMasterProfiles.MasterProfileId : null,
                required ? PostProductionMasterProfiles.VideoProfileId : null,
                required ? PostProductionMasterProfiles.AudioProfileId : null, masterDigest, masterManifestSha,
                Path.GetFileName(candidate), sha, bytes,
                new FinalQaObservedMedia("mp4", 0, 0, new FinalQaVideoFacts(0, "", "", 0, 0, 0, 0, 0, null), null),
                FinalQaIdentity.Checks, default);
            var node = FinalArtifactReceiptStore.InputFields(template);
            node["container_timestamp_budget_us"] = FinalQaIdentity.ContainerTimestampBudgetUs;
            node["tasks"] = JsonSerializer.SerializeToNode(plan.Tasks.Select(t => new
                { order = t.Order, width = t.Width, height = t.Height, fps = t.Fps, frame_count = t.FrameCount, target_duration_ms = t.TargetDurationMs }));
            template = template with { QaInputDigest = FinalQaIdentity.Hash(node) };
            return new(template, candidate, frames);
        }
        catch (FinalVideoQaException) { throw; }
        catch (OperationCanceledException) { throw; }
        catch (MasterCompositionException) { throw new FinalVideoQaException("ARTIFACT_INVALID"); }
        catch (Exception e) when (e is NarrationPlanContractException or TextOverlayException or JsonException
            or ArgumentException or NullReferenceException or InvalidOperationException or OverflowException)
        { throw new FinalVideoQaException("INPUT_INVALID"); }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException)
        { throw new FinalVideoQaException("ARTIFACT_INVALID"); }
    }
    private static bool Id(string? s) => s is { Length: > 0 and <= 160 } && !s.Any(char.IsControl);
    internal static long ValidateTiming(ProductionPlanRecord plan)
    {
        var (width, height) = FinalVideoQaMediaProbe.Dimensions(plan.OutputProfileId);
        if (plan.Tasks is not { Length: > 0 and <= 120 } || plan.TargetRuntimeMs is <= 0 or > 600_000)
            throw new FinalVideoQaException("INPUT_INVALID");
        long frames = 0, ms = 0;
        foreach (var (task, index) in plan.Tasks.Select((t, i) => (t, i)))
        {
            if (task.Order != index + 1 || task.Width != width || task.Height != height || task.Fps != 24
                || task.FrameCount <= 0 || task.TargetDurationMs <= 0) throw new FinalVideoQaException("OUTPUT_PROFILE_MISMATCH");
            frames = checked(frames + task.FrameCount); ms = checked(ms + task.TargetDurationMs);
        }
        if (ms != plan.TargetRuntimeMs) throw new FinalVideoQaException("RUNTIME_MISMATCH");
        return frames;
    }
}
