using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>Offline exact Core v1.1 identity comparison; no approval is simulated or GPU submitted.</summary>
internal static class ReferenceV11BindingTests
{
    public static void Run()
    {
        const string jobId = "job-v11";
        const string taskId = "task-v11";
        const string package = "creative-package-v11";
        const string shot = "shot-a";
        const string asset = "core-asset-v11";
        const string approval = "core-approval-v11";
        const string goal = "goal-v11";
        const string relative = "PicotooPet/references/sha-pet.png";
        var sha = new string('a', 64);
        var planDigest = new string('b', 64);
        var reference = new ProductionReferenceAssetV11Record(
            "reference_asset.v1", asset, goal, "creative-job-v11", package,
            jobId, taskId, shot, sha, relative, sha, 1024,
            "USER_SUPPLIED", new string('c', 64), "wan22.i2v.production.v1",
            approval, new string('d', 64));
        var descriptor = new TrustedReferenceDescriptor(approval, shot, asset, relative, sha, 1024);
        var coreDescriptor = new ProductionReferenceDescriptorV11Record(
            approval, shot, asset, relative, sha, 1024);
        var task = new ProductionTaskPlanRecord(
            taskId, shot, 1, "IMAGE_TO_VIDEO", "Executable",
            ComfyWorkflowTemplateValidator.I2VWorkflowId,
            "same dog", "wan22.safe-negative.v1",
            12, 832, 480, 24, 73, 3000, relative, reference);
        var plan = new ProductionPlanRecord(
            "1.1", "production.comfyui.v1", jobId, package, sha,
            "goal-" + goal, "video.landscape.v1", 3000, [task]);
        var job = new ProductionJobRecord(
            jobId, package, sha, "goal-" + goal, "production.comfyui.v1",
            planDigest, "Ready", null, null, null, null, "v11-test",
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
        var result = new ProductionReferenceAuthorizationV11Record(
            "reference_authorization.v1", jobId, taskId,
            planDigest, coreDescriptor, reference);

        bool Matches(ProductionJobRecord j, ProductionPlanRecord p,
            ProductionReferenceAuthorizationV11Record auth, TrustedReferenceDescriptor d) =>
            CoreReferenceApprovalSource.Matches(j, p, auth, d, jobId, taskId, planDigest);

        RecoveryTests.Assert(Matches(job, plan, result, descriptor),
            "exact authenticated frozen Core plan and descriptor should match");
        RecoveryTests.Assert(!Matches(job, plan, result,
            descriptor with { AssetId = "wrong-asset" }), "wrong AssetId must be denied");
        RecoveryTests.Assert(!Matches(job, plan, result,
            descriptor with { Sha256 = new string('e', 64) }), "tampered SHA must be denied");
        RecoveryTests.Assert(!Matches(job, plan, result,
            descriptor with { ShotId = "shot-b" }), "cross-shot identity must be denied");
        RecoveryTests.Assert(!Matches(job, plan, result with { PlanDigest = new string('f', 64) },
            descriptor), "stale plan digest must be denied");
        RecoveryTests.Assert(!Matches(job, plan with { SchemaVersion = "1.0" }, result,
            descriptor), "old v1.0 plan must not authorize reference GPU");
        RecoveryTests.Assert(!Matches(job, plan with
            { Tasks = [task with { ReferenceAsset = reference with { GoalId = "goal-other" } }] },
            result, descriptor), "frozen task reference must match authentic Core result");
        RecoveryTests.Assert(!Matches(job, plan, result with
            { ReferenceAsset = reference with { RightsScope = "unapproved" } },
            descriptor), "rights alteration must be denied");
        Console.WriteLine("P0_V11_CORE_REFERENCE_BINDING=PASS (offline; GPU I2V disarmed)");
    }
}
