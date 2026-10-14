using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Contracts;

[assembly: InternalsVisibleTo("PicotooPet.FinalDeliveryIntegration.SmokeTests")]

namespace PicotooPet.Desktop.Services;

/// <summary>
/// C011 bridge: reads only actual Core authority and C010A's immutable QA result.
/// This is not another QA implementation, receipt store or master catalog.
/// </summary>
public sealed record C011QaDeliveryAuthority(
    GoalVideoContinuationRecord Goal,
    ProductionJobRecord Job,
    ProductionPlanRecord Plan,
    ProductionPackageRecord Package)
{
    public string Fingerprint() => FinalQaIdentity.Hash(JsonSerializer.SerializeToNode(this)!);

    public static async Task<C011QaDeliveryAuthority> FetchAsync(
        ControlCenterSession session, string goalId, string jobId, CancellationToken ct)
    {
        var goalTask = session.GetGoalVideoContinuationAsync(goalId, ct);
        var jobsTask = session.GetProductionJobsAsync(ct);
        var planTask = session.GetProductionPlanAsync(jobId, ct);
        var packageTask = session.GetProductionPackageAsync(jobId, ct);
        await Task.WhenAll(goalTask, jobsTask, planTask, packageTask).ConfigureAwait(false);
        var matches = (await jobsTask.ConfigureAwait(false))
            .Where(j => string.Equals(j.ProductionJobId, jobId, StringComparison.Ordinal)).Take(2).ToArray();
        var package = await packageTask.ConfigureAwait(false);
        var goal = await goalTask.ConfigureAwait(false);
        var plan = await planTask.ConfigureAwait(false);
        if (matches.Length != 1 || package is null
            || goal.GoalId != goalId || goal.ProductionJobId != jobId
            || matches[0].ProductionJobId != plan.ProductionJobId
            || package.ProductionJobId != jobId)
        {
            throw new InvalidDataException("C011_CORE_AUTHORITY_MISMATCH");
        }
        return new(goal, matches[0], plan, package);
    }

    /// <summary>
    /// Check only C011 selection binding; the authoritative semantic/media/receipt checks
    /// are performed by FinalVideoQaService.VerifyAsync, never reimplemented here.
    /// </summary>
    public static bool Approved(
        GoalDeliveryCandidateV1 candidate,
        FinalVideoQaInputV1 input,
        FinalVideoQaResult result)
    {
        var receipt = result.Receipt;
        var expectedKind = candidate.Kind == GoalDeliveryKind.C009Master ? "c009_master_v1" : "c004_fallback_v1";
        if (receipt.Outcome != "PASS" || receipt.SchemaVersion != "1.0"
            || receipt.QaProfileId != FinalQaIdentity.Profile
            || !FinalQaIdentity.Sha(receipt.QaInputDigest)
            || !FinalQaIdentity.Sha(receipt.ReceiptDigest)
            || receipt.ReceiptDigest != FinalQaIdentity.ReceiptDigest(receipt)
            || receipt.GoalId != input.GoalContinuation.GoalId
            || receipt.ProductionJobId != candidate.ProductionJobId
            || receipt.ProductionPackageId != candidate.ProductionPackageId
            || receipt.ProductionPackageDigest != candidate.ProductionPackageDigest
            || receipt.ProductionPlanDigest != candidate.ProductionPlanDigest
            || receipt.OutputProfileId != candidate.OutputProfileId
            || receipt.TargetRuntimeMs != candidate.TargetRuntimeMs
            || receipt.NarrationRequired != candidate.NarrationRequired
            || receipt.NarrationPlanDigest != candidate.NarrationPlanDigest
            || receipt.OverlaysRequired != candidate.OverlaysRequired
            || receipt.CaptionOverlayPlanDigest != candidate.CaptionOverlayPlanDigest
            || receipt.CandidateKind != expectedKind
            || receipt.MasterInputDigest != candidate.MasterInputDigest
            || receipt.ArtifactSha256 != candidate.FileSha256
            || receipt.ArtifactBytes != candidate.FileBytes
            || receipt.ArtifactFileName != Path.GetFileName(candidate.FilePath)
            || receipt.PassedCheckIds.Count != FinalQaIdentity.Checks.Count
            || !FinalQaIdentity.Checks.SequenceEqual(receipt.PassedCheckIds))
        {
            return false;
        }
        // ReceiptPath is returned from C010A's exact immutable store, not the UI.
        return Path.IsPathFullyQualified(result.ReceiptPath)
            && ProductionLocalEnvironment.IsOrdinaryFile(result.ReceiptPath);
    }
}
