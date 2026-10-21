using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// Consumer-owned Codex #110 approval authority. This always reads the real paired Core;
/// never trusts a caller-supplied local "approved" flag or path-only Creative manifest.
/// Construct one for an exact frozen v1.1 Job/Task. The GPU executor is NOT yet armed:
/// crash-durable managed snapshot lifetime and claim/POST handling remain a separate gate.
/// </summary>
public sealed class CoreReferenceApprovalSource : ITrustedReferenceApprovalSource
{
    private readonly ControlCenterSession _session;
    private readonly string _jobId;
    private readonly string _taskId;
    private readonly string _expectedPlanDigest;

    public CoreReferenceApprovalSource(
        ControlCenterSession session, string jobId, string taskId, string expectedPlanDigest)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedPlanDigest);
        _jobId = jobId;
        _taskId = taskId;
        _expectedPlanDigest = expectedPlanDigest;
    }

    public async Task<bool> IsApprovedAsync(
        TrustedReferenceDescriptor descriptor, CancellationToken cancellationToken)
    {
        try
        {
            // A Core authorization endpoint success alone is insufficient: independently
            // compare it with the actual frozen plan, task, job digest and all bytes/rights.
            var job = await _session.GetProductionJobAsync(_jobId, cancellationToken).ConfigureAwait(false);
            var plan = await _session.GetProductionPlanAsync(_jobId, cancellationToken).ConfigureAwait(false);
            var authority = await _session.GetReferenceAuthorizationV11Async(
                _jobId, _taskId, cancellationToken).ConfigureAwait(false);
            return Matches(job, plan, authority, descriptor, _jobId, _taskId, _expectedPlanDigest);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            // Network loss, revocation, stale plans and all unknown states are DENY.
            return false;
        }
    }

    /// <summary>Pure comparison, suitable for negative native tests; cannot mint Core approval.</summary>
    public static bool Matches(
        ProductionJobRecord job,
        ProductionPlanRecord plan,
        ProductionReferenceAuthorizationV11Record authority,
        TrustedReferenceDescriptor descriptor,
        string jobId, string taskId, string expectedPlanDigest)
    {
        if (job is null || plan is null || authority is null || descriptor is null
            || plan.SchemaVersion != "1.1"
            || plan.ProductionJobId != jobId
            || job.ProductionJobId != jobId
            || authority.SchemaVersion != "reference_authorization.v1"
            || authority.ProductionJobId != jobId
            || authority.ProductionTaskId != taskId
            || !string.Equals(job.PlanDigest, expectedPlanDigest, StringComparison.Ordinal)
            || !string.Equals(authority.PlanDigest, expectedPlanDigest, StringComparison.Ordinal)
            || !string.Equals(plan.CreativePackageDigest, job.CreativePackageDigest, StringComparison.Ordinal)
            || !string.Equals(plan.CreativePackageId, job.CreativePackageId, StringComparison.Ordinal))
            return false;

        var tasks = plan.Tasks.Where(task => task.ProductionTaskId == taskId).ToArray();
        if (tasks.Length != 1) return false;
        var task = tasks[0];
        var bound = task.ReferenceAsset;
        var approved = authority.ReferenceAsset;
        var fromCore = authority.Descriptor;
        if (bound is null || approved is null || fromCore is null
            || !bound.Equals(approved)
            || bound.SchemaVersion != "reference_asset.v1"
            || bound.ProductionJobId != jobId
            || bound.ProductionTaskId != taskId
            || bound.ShotId != task.ShotId
            || bound.CreativePackageId != plan.CreativePackageId
            || bound.CreativePackageDigest != plan.CreativePackageDigest
            || bound.RightsScope != "wan22.i2v.production.v1"
            || !string.Equals(plan.ProjectKey, "goal-" + bound.GoalId, StringComparison.Ordinal)
            || task.RenderIntent != "IMAGE_TO_VIDEO"
            || task.WorkflowId != ComfyWorkflowTemplateValidator.I2VWorkflowId
            || task.ExecutionDisposition != "Executable"
            || task.TrustedInputAssetRef != bound.InputRelativePath)
            return false;

        return string.Equals(descriptor.ApprovalId, fromCore.ApprovalId, StringComparison.Ordinal)
            && string.Equals(descriptor.ShotId, fromCore.ShotId, StringComparison.Ordinal)
            && string.Equals(descriptor.AssetId, fromCore.AssetId, StringComparison.Ordinal)
            && string.Equals(descriptor.RelativePath, fromCore.RelativePath, StringComparison.Ordinal)
            && string.Equals(descriptor.Sha256, fromCore.Sha256, StringComparison.Ordinal)
            && descriptor.ByteLength == fromCore.ByteLength
            && fromCore.ApprovalId == bound.ApprovalId
            && fromCore.ShotId == bound.ShotId
            && fromCore.AssetId == bound.AssetId
            && fromCore.RelativePath == bound.InputRelativePath
            && fromCore.Sha256 == bound.Sha256
            && fromCore.ByteLength == bound.Bytes;
    }

    /// <summary>Explicit bridge from existing Desktop root policy into frozen Codex verifier.</summary>
    public static TrustedReferenceAssetVerifier CreateVerifier(
        string existingComfyInputRoot, CoreReferenceApprovalSource approvals) =>
        new(existingComfyInputRoot,
            new TrustedReferenceFilePolicy(
                ProductionLocalEnvironment.ResolveUnderRoot,
                ProductionLocalEnvironment.AssertNoLinkEscape,
                ProductionLocalEnvironment.IsOrdinaryFile,
                ProductionLocalEnvironment.Sha256FileAsync),
            approvals);
}
