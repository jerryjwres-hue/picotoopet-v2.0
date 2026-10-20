using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// Opt-in acceptance boundary only. No model loads, GPU calls, Core writes, or second scheduler.
/// Core's full frozen plan, NOT claim's succeeded-filtered resume plan, is authoritative.
/// </summary>
public static class Stage1SingleShotGate
{
    public const string ModeVariable = "PICOTOO_P0_STAGE1_SINGLE_SHOT";
    public const string JobVariable = "PICOTOO_P0_STAGE1_PRODUCTION_JOB_ID";
    private const string T2V = "comfy.wan22.ti2v5b.t2v.v1";

    /// <summary>
    /// A missing mode variable means ordinary unchanged production. An explicitly armed mode
    /// without an exact Core job ID remains INERT (useful while preparing a new Goal).
    /// </summary>
    public static bool IsArmed()
    {
        var value = Environment.GetEnvironmentVariable(ModeVariable);
        if (value is null) return false;
        if (value != "1") throw new ProductionWorkerException("STAGE1_MODE_INVALID");
        return true;
    }

    public static string? ExactTargetJobId()
    {
        if (!IsArmed()) return null;
        var id = Environment.GetEnvironmentVariable(JobVariable);
        if (string.IsNullOrWhiteSpace(id)) return null;
        if (id.Length > 160 || id != id.Trim() || id.Any(char.IsWhiteSpace))
            throw new ProductionWorkerException("STAGE1_JOB_ID_INVALID");
        return id;
    }

    /// <summary>Read-only, pre-claim gate; caller must authenticate exact Core job read.</summary>
    public static void Validate(ProductionPlanRecord plan, ProductionJobRecord job, string targetJobId)
    {
        if (plan is null || job is null || !string.Equals(targetJobId, job.ProductionJobId, StringComparison.Ordinal)
            || !string.Equals(targetJobId, plan.ProductionJobId, StringComparison.Ordinal)
            || job.Status is not ("Ready" or "Claimed" or "Rendering")
            || plan.SchemaVersion != "1.0"
            || plan.ProductionProfile != "production.comfyui.v1"
            || plan.ProductionProfile != job.ProductionProfile
            || string.IsNullOrWhiteSpace(plan.CreativePackageId)
            || !string.Equals(plan.CreativePackageId, job.CreativePackageId, StringComparison.Ordinal)
            || !string.Equals(plan.CreativePackageDigest, job.CreativePackageDigest, StringComparison.Ordinal)
            || !string.Equals(plan.ProjectKey, job.ProjectKey, StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(plan.ProjectKey)
            || !IsSha(plan.CreativePackageDigest)
            || !IsSha(job.PlanDigest)
            || plan.Tasks is not { Length: 1 })
            throw new ProductionWorkerException("STAGE1_SINGLE_SHOT_PLAN_REJECTED");

        // ── Compare actual canonical bytes against the durable Core plan digest. ──
        var digest = Convert.ToHexString(SHA256.HashData(
            CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))).ToLowerInvariant();
        if (!string.Equals(digest, job.PlanDigest, StringComparison.Ordinal))
            throw new ProductionWorkerException("STAGE1_SINGLE_SHOT_PROVENANCE_REJECTED");

        var task = plan.Tasks[0];
        if (string.IsNullOrWhiteSpace(task.ProductionTaskId)
            || string.IsNullOrWhiteSpace(task.ShotId) || task.Order != 1
            || task.ExecutionDisposition != "Executable"
            || task.RenderIntent != "GENERATIVE_VIDEO" || task.WorkflowId != T2V
            || task.TrustedInputAssetRef is not null
            || task.NegativePromptPolicyId != "wan22.safe-negative.v1"
            || string.IsNullOrWhiteSpace(task.PositivePrompt)
            || task.Width < 256 || task.Height < 256
            || task.Fps is < 1 or > 30 || task.FrameCount is < 1 or > 121
            || task.FrameCount % 4 != 1 || task.TargetDurationMs <= 0
            || plan.TargetRuntimeMs != task.TargetDurationMs)
            throw new ProductionWorkerException("STAGE1_SINGLE_SHOT_TASK_REJECTED");
    }

    /// <summary>
    /// Second barrier after claim: Core strips Succeeded tasks from the resume plan,
    /// so require one original task and one matching durable task snapshot instead.
    /// </summary>
    public static void ValidateClaim(ProductionPlanRecord original, ProductionClaimRecord claim)
    {
        if (original.Tasks is not { Length: 1 }
            || claim.ProductionJobId != original.ProductionJobId
            || claim.Plan.ProductionJobId != original.ProductionJobId
            || claim.Tasks is not { Length: 1 }
            || claim.Tasks[0].ProductionTaskId != original.Tasks[0].ProductionTaskId
            || claim.Tasks[0].TaskPlan != original.Tasks[0]
            || claim.Tasks[0].ExecutionDisposition != "Executable"
            || claim.Tasks[0].WorkflowId != T2V
            || claim.Plan.Tasks.Length > 1
            || (claim.Plan.Tasks.Length == 1 && claim.Plan.Tasks[0] != original.Tasks[0])
            || (claim.Plan.Tasks.Length == 0 && claim.Tasks[0].Status != "Succeeded"))
            throw new ProductionWorkerException("STAGE1_SINGLE_SHOT_CLAIM_REJECTED");
    }

    private static bool IsSha(string? sha) => sha is { Length: 64 }
        && sha.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
}
