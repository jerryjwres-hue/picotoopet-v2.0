using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Security;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// One explicit LTX pilot in the existing same-EXE Worker. No new scheduler,
/// database, GPU lock, credential file or alternate Wan claim path.
/// </summary>
internal static class LtxProductionExecutor
{
    internal static bool IsSelected(ProductionJobRecord job) =>
        job.ProductionProfile == "production.ltx.desktop.local.v1"
        && job.Status == "NeedsHuman"
        && job.FailureCode == "LTX_SIGNED_WORKER_NOT_ENABLED"
        && Guid.TryParseExact(job.ProductionJobId, "D", out _)
        && job.PlanDigest is { Length: 64 };

    // 01. This is technical candidate completion, never visual or film PASS.
    internal static bool IsCandidateSettled(ProductionJobRecord job) =>
        job.ProductionProfile == "production.ltx.desktop.local.v1"
        && job.Status == "NeedsHuman" && job.FailureCode == "LTX_PILOT_REVIEW_REQUIRED"
        && job.LeaseExecutorId is null && job.LeaseExpiresAt is null
        && job.FinishedAt is not null && job.PlanDigest is { Length: 64 };

    // 02. Read-only UI may inspect a currently rendering frozen plan;
    //     this state never passes IsSelected or starts another GPU claim.
    internal static bool IsRendering(ProductionJobRecord job) =>
        job.ProductionProfile == "production.ltx.desktop.local.v1"
        && job.Status == "Rendering" && job.PlanDigest is { Length: 64 };

    internal static async Task RunAsync(ControlCenterSession session, ProductionJobRecord job,
        ProductionSubmissionJournal journal, CancellationToken ct, string? batchIdentity = null)
    {
        if (!IsSelected(job)) throw new ProductionWorkerException("LTX_PILOT_NOT_SELECTED");
        var digest = job.PlanDigest!;
        using var gpu = journal.AcquireGpu();
        if (journal.Pending().Count != 0)
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        // 01. Preserve the existing exact operator permit, including armed
        //     HOLD semantics. No config file is created or changed by dispatch.
        using var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermit(
            job.ProductionJobId, digest, batchIdentity);
        var executor = ProductionExecutionService.NormalizeExecutorId("windows-production-" + Environment.MachineName);
        var pairing = WorkerLocalPairing.Require(executor);
        using var core = session.CreateWorkerChallengePreflightClient();
        var plan = await core.GetLtxPlanAsync(job.ProductionJobId, ct).ConfigureAwait(false);
        var reference = ValidatePlan(job, plan);
        // 02. Explicit local deployment settings. No guessing at a user's
        //     vendor settings location; no token in env, JSON or arguments.
        var settings = Environment.GetEnvironmentVariable("PICOTOO_LTX_SETTINGS_FILE");
        var token = new CredentialManagerTokenStore("PicotooPetV2/LtxDesktopRemoteToken").Read();
        if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(settings) || string.IsNullOrWhiteSpace(token))
            throw new ProductionWorkerException("LTX_LOCAL_CONFIGURATION_REQUIRED");
        await using var vendor = LtxDesktopLocalI2vPreflightClient.Create(token);
        var dataRoot = ProductionLocalEnvironment.ResolveComfyDataRoot();
        var inputRoot = Path.Combine(dataRoot, "input");
        var outputRoot = ProductionLocalEnvironment.ResolveComfyOutputRoot();
        var source = ProductionLocalEnvironment.ResolveUnderRoot(inputRoot, reference.InputRelativePath, true);
        ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, source);
        var draft = new LtxDesktopI2vDraft(reference.ShotId, "", "video.vertical.v1", source,
            reference.Sha256, plan.GetProperty("prompt").GetString()!, plan.GetProperty("seed").GetInt32(),
            reference.CreativePackageDigest);
        // 03. Read-only capability probe before allocating an Attempt.
        var readiness = await vendor.PreflightAsync(draft, settings!, ct).ConfigureAwait(false);
        var intent = LtxDesktopLocalI2vPreflightClient.SubmissionIntentDigest(draft, readiness.VendorSubmissionTemplate);
        var approval = core.LtxReferenceApproval(reference, digest, intent);
        var store = new ProductionReferenceSnapshotStore(inputRoot,
            (_, _, _) => throw new ProductionWorkerException("LTX_LEGACY_REFERENCE_PATH_DENIED"));
        using var snapshot = await store.PrepareLtxAsync(reference, digest, intent, approval, journal, gpu, ct)
            .ConfigureAwait(false);
        var snapshotPath = ProductionLocalEnvironment.ResolveUnderRoot(inputRoot, snapshot.RelativePath, true);
        draft = draft with { FirstFrameFile = snapshotPath };
        var claim = await core.ClaimLtxPreparedAsync(reference, digest, intent, WorkerLocalPairing.KeyRoot,
            executor, pairing.Fingerprint, snapshot, journal, gpu, ct).ConfigureAwait(false);
        // 04. Both vendor POSTs must recheck the live signed reservation
        //     and the exact pinned reference. Do not recreate a lost claim.
        async Task Recheck(CancellationToken cancellationToken)
        {
            await snapshot.RecheckForWitnessAsync(cancellationToken).ConfigureAwait(false);
            _ = await core.CheckLtxLeaseAsync(claim, journal, gpu, false, cancellationToken).ConfigureAwait(false);
        }
        var submitted = await vendor.SubmitClaimedOnceTransportAsync(draft, settings!, journal, gpu,
            job.ProductionJobId, reference.ProductionTaskId, digest, intent, Recheck, ct).ConfigureAwait(false);
        await core.BindLtxGenerationAsync(claim, journal, gpu, ct).ConfigureAwait(false);
        permit.Dispose(); // 05. Existing HOLD may change after both POSTs, not cancel already-started media.
        var expected = new LtxDesktopGenerationExpectation(submitted.GenerationId,
            submitted.StartFrameAssetId, draft.Prompt, draft.Seed);
        // 06. Bounded same-process polling; only the exact generation is
        //     queried. Unknown/terminal errors leave the journal unresolved.
        var deadline = DateTimeOffset.UtcNow.AddMinutes(30);
        while (DateTimeOffset.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            _ = await core.CheckLtxLeaseAsync(claim, journal, gpu, true, ct).ConfigureAwait(false);
            try { _ = await vendor.InspectCompletedGenerationAsync(expected, ct).ConfigureAwait(false); }
            catch (InvalidOperationException error) when (error.Message == "LTX_GENERATION_NOT_SUCCEEDED")
            {
                await Task.Delay(TimeSpan.FromSeconds(10), ct).ConfigureAwait(false);
                continue;
            }
            _ = await core.CollectCompletedLtxCandidateAsync(claim, vendor, outputRoot, journal, gpu, ct)
                .ConfigureAwait(false);
            return;
        }
        throw new ProductionWorkerException("LTX_GENERATION_WAIT_UNRESOLVED");
    }

    internal static ProductionReferenceAssetV11Record ValidatePlan(ProductionJobRecord job, JsonElement plan,
        bool allowSettled = false, bool allowRendering = false)
    {
        // 07. Verify the original JSON digest and complete renderer identity,
        //     not a locally reconstructed Wan or StoryPack plan.
        if ((!IsSelected(job) && !(allowSettled && IsCandidateSettled(job))
            && !(allowRendering && IsRendering(job))) || plan.ValueKind != JsonValueKind.Object
            || Convert.ToHexStringLower(SHA256.HashData(CanonicalJson.Serialize(JsonNode.Parse(plan.GetRawText())!))) != job.PlanDigest
            || plan.GetProperty("schema_version").GetString() != "1.2"
            || plan.GetProperty("production_profile").GetString() != job.ProductionProfile
            || plan.GetProperty("workflow_id").GetString() != "ltx.desktop.local.i2v.v1"
            || plan.GetProperty("production_job_id").GetString() != job.ProductionJobId
            || plan.GetProperty("creative_package_id").GetString() != job.CreativePackageId
            || plan.GetProperty("creative_package_digest").GetString() != job.CreativePackageDigest
            || plan.GetProperty("project_key").GetString() != job.ProjectKey
            || plan.GetProperty("source_output_profile").GetString() != "video.vertical.v1"
            || plan.GetProperty("model").GetString() != "ltx-2.5-fast"
            || plan.GetProperty("resolution").GetString() != "720p"
            || plan.GetProperty("aspect_ratio").GetString() != "9:16"
            || plan.GetProperty("duration_seconds").GetInt32() != 4
            || plan.GetProperty("fps").GetInt32() != 24
            || plan.GetProperty("seed").GetInt32() < 0
            || plan.GetProperty("prompt").GetString() is not { Length: > 0 and <= 5000 })
            throw new ProductionWorkerException("LTX_PLAN_IDENTITY_MISMATCH");
        var reference = plan.GetProperty("reference_asset").Deserialize<ProductionReferenceAssetV11Record>();
        if (reference is null || reference.SchemaVersion != "reference_asset.v1"
            || reference.RightsScope != "ltx.desktop.local.i2v.production.v1"
            || reference.ProductionJobId != job.ProductionJobId
            || reference.CreativePackageId != job.CreativePackageId
            || reference.CreativePackageDigest != job.CreativePackageDigest
            || reference.ProductionTaskId != plan.GetProperty("production_task_id").GetString()
            || !Guid.TryParseExact(reference.ProductionTaskId, "D", out _)
            || reference.ShotId != plan.GetProperty("shot_id").GetString())
            throw new ProductionWorkerException("LTX_PLAN_REFERENCE_MISMATCH");
        return reference;
    }
}
