using System.IO;
using System.Security.Cryptography;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>Offline byte/identity tests only: synthetic grants cannot constitute Core authority.</summary>
internal static class ReferenceAssetSmokeTests
{
    public static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "picotoopet-reference-" + Guid.NewGuid().ToString("N"));
        var relative = Path.Combine("approved", "pet.png");
        Directory.CreateDirectory(Path.Combine(root, "approved"));
        var full = Path.Combine(root, relative);
        // A byte fixture exercises identity, not image decoding or perceptual validation.
        var bytes = new byte[] { 137, 80, 78, 71, 13, 10, 26, 10, 9, 8, 7, 6 };
        await File.WriteAllBytesAsync(full, bytes);
        var digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var (plan, task) = Plan(relative);
        var reference = new ReferenceAssetIdentityV1(
            "reference_asset.v1", "goal-a", "creative-job-a", "production-job-a",
            "task-a", "shot-a", new string('a', 64), relative, digest, bytes.Length,
            "user-selected-image", new string('b', 64), "wan22.i2v.production.v1",
            "approval-a", new string('c', 64), "Approved");
        try
        {
            await using (var pinned = await TrustedReferenceSnapshotVerifier.VerifyAsync(
                plan, task, reference, root, CancellationToken.None))
            {
                RecoveryTests.Assert(pinned.RelativePath == relative, "approved bytes not pinned");
                var replacementBlocked = false;
                try
                {
                    await File.WriteAllBytesAsync(full, bytes);
                }
                catch (IOException)
                {
                    replacementBlocked = true;
                }
                RecoveryTests.Assert(replacementBlocked, "reference file must be write-locked while Comfy reads it");
            }

            await RejectAsync(plan, task, reference with { ShotId = "shot-b" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { ProductionTaskId = "task-other" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { ApprovalStatus = "Pending" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { SourceReference = "" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { RightsScope = "unapproved" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { CreativePackageDigest = new string('d', 64) }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { ApprovalRequestDigest = "" }, root,
                "I2V_REFERENCE_IDENTITY_INVALID");
            await RejectAsync(plan, task, reference with { Bytes = bytes.Length + 1 }, root,
                "I2V_REFERENCE_BYTES_MISMATCH");

            // Restart loses the read lock, but must never preserve a stale byte approval.
            await File.WriteAllBytesAsync(full, bytes.Select(b => (byte)(b ^ 1)).ToArray());
            await RejectAsync(plan, task, reference, root, "I2V_REFERENCE_SHA256_MISMATCH");

            var traversal = reference with { InputRelativePath = "../pet.png" };
            var traversalTask = task with { TrustedInputAssetRef = "../pet.png" };
            var traversalPlan = plan with { Tasks = [traversalTask] };
            await RejectAnyAsync(traversalPlan, traversalTask, traversal, root);
            Console.WriteLine("P0_I2V_REFERENCE_BYTE_IDENTITY=PASS (offline; no Core grant issued)");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    private static (ProductionPlanRecord, ProductionTaskPlanRecord) Plan(string relative)
    {
        var task = new ProductionTaskPlanRecord(
            "task-a", "shot-a", 1, "IMAGE_TO_VIDEO", "Executable",
            ComfyWorkflowTemplateValidator.I2VWorkflowId, "pet walking", "wan22.safe-negative.v1",
            123, 832, 480, 24, 73, 3000, relative);
        var plan = new ProductionPlanRecord(
            "1.0", "production.comfyui.v1", "production-job-a", "creative-package-a",
            new string('a', 64), "goal-a", "video.landscape.v1", 3000, [task]);
        return (plan, task);
    }

    private static async Task RejectAsync(
        ProductionPlanRecord plan, ProductionTaskPlanRecord task,
        ReferenceAssetIdentityV1 reference, string root, string code)
    {
        await RecoveryTests.ThrowsCodeAsync(code, async () =>
        {
            await using var result = await TrustedReferenceSnapshotVerifier.VerifyAsync(
                plan, task, reference, root, CancellationToken.None);
        });
    }

    private static async Task RejectAnyAsync(
        ProductionPlanRecord plan, ProductionTaskPlanRecord task,
        ReferenceAssetIdentityV1 reference, string root)
    {
        try
        {
            await using var result = await TrustedReferenceSnapshotVerifier.VerifyAsync(
                plan, task, reference, root, CancellationToken.None);
        }
        catch (ProductionWorkerException) { return; }
        throw new InvalidOperationException("invalid path was allowed");
    }
}
