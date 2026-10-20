using System.IO;
using System.Security.Cryptography;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// Versioned transport candidate, NOT approval evidence by itself.
/// A future authenticated Core authority must bind the grant + source to an immutable plan
/// before the ordinary GPU executor may consume any such candidate.
/// </summary>
public sealed record ReferenceAssetIdentityV1(
    string SchemaVersion,
    string GoalId,
    string CreativeJobId,
    string ProductionJobId,
    string ProductionTaskId,
    string ShotId,
    string CreativePackageDigest,
    string InputRelativePath,
    string Sha256,
    long Bytes,
    string SourceReference,
    string SourceDigest,
    string RightsScope,
    string ApprovalId,
    string ApprovalRequestDigest,
    string ApprovalStatus);

/// <summary>
/// A pinned, hash-verified Comfy input handle. FileShare.Read denies further Windows
/// write/delete opens while the handle is held; after crash the next host must rehash.
/// This is only the byte-side verifier, NOT the Core authorization/consent issuance path.
/// </summary>
public sealed class VerifiedReferenceSnapshot : IAsyncDisposable
{
    private readonly FileStream _handle;

    internal VerifiedReferenceSnapshot(string relativePath, FileStream handle)
    {
        RelativePath = relativePath;
        _handle = handle;
    }

    public string RelativePath { get; }

    public ValueTask DisposeAsync() => _handle.DisposeAsync();
}

public static class TrustedReferenceSnapshotVerifier
{
    private const long MaximumReferenceBytes = 32L * 1024 * 1024;
    private const string I2VUseScope = "wan22.i2v.production.v1";

    /// <summary>Pure file verification. Caller must separately authenticate Core grant/plan.</summary>
    public static async Task<VerifiedReferenceSnapshot> VerifyAsync(
        ProductionPlanRecord plan, ProductionTaskPlanRecord task,
        ReferenceAssetIdentityV1 reference, string inputRoot, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(task);
        ArgumentNullException.ThrowIfNull(reference);

        if (reference.SchemaVersion != "reference_asset.v1"
            || reference.ProductionJobId != plan.ProductionJobId
            || reference.ProductionTaskId != task.ProductionTaskId
            || reference.ShotId != task.ShotId
            || reference.CreativePackageDigest != plan.CreativePackageDigest
            || reference.GoalId is not { Length: > 0 and <= 160 }
            || reference.CreativeJobId is not { Length: > 0 and <= 160 }
            || !plan.Tasks.Any(item => item == task)
            || task.RenderIntent != "IMAGE_TO_VIDEO"
            || task.WorkflowId != ComfyWorkflowTemplateValidator.I2VWorkflowId
            || task.TrustedInputAssetRef != reference.InputRelativePath
            || reference.ApprovalStatus != "Approved"
            || reference.RightsScope != I2VUseScope
            || string.IsNullOrWhiteSpace(reference.ApprovalId)
            || reference.ApprovalId.Length > 160
            || string.IsNullOrWhiteSpace(reference.SourceReference)
            || reference.SourceReference.Length > 240
            || !IsSha(reference.SourceDigest)
            || !IsSha(reference.ApprovalRequestDigest)
            || !IsSha(reference.Sha256)
            || reference.Bytes is <= 0 or > MaximumReferenceBytes
            || string.IsNullOrWhiteSpace(reference.InputRelativePath)
            || reference.InputRelativePath.Length > 300
            || !IsSupportedExtension(reference.InputRelativePath))
        {
            throw new ProductionWorkerException("I2V_REFERENCE_IDENTITY_INVALID");
        }

        string path;
        try
        {
            path = ProductionLocalEnvironment.ResolveUnderRoot(
                inputRoot, reference.InputRelativePath, requireExistingFile: true);
            ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, path);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(path))
                throw new InvalidDataException("I2V_REFERENCE_INVALID_FILE");
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException
            or ArgumentException or NotSupportedException)
        {
            throw new ProductionWorkerException("I2V_REFERENCE_PATH_REJECTED");
        }

        FileStream? handle = null;
        try
        {
            // No FileShare.Write or FileShare.Delete: block replacement until Comfy has
            // finished consuming this input; no private copy and no second asset store.
            handle = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
                bufferSize: 64 * 1024, options: FileOptions.Asynchronous | FileOptions.SequentialScan);
            if (handle.Length != reference.Bytes)
                throw new ProductionWorkerException("I2V_REFERENCE_BYTES_MISMATCH");
            var bytes = await SHA256.HashDataAsync(handle, cancellationToken).ConfigureAwait(false);
            var digest = Convert.ToHexString(bytes).ToLowerInvariant();
            if (!string.Equals(digest, reference.Sha256, StringComparison.Ordinal))
                throw new ProductionWorkerException("I2V_REFERENCE_SHA256_MISMATCH");
            handle.Position = 0;
            var pinned = new VerifiedReferenceSnapshot(reference.InputRelativePath, handle);
            handle = null;
            return pinned;
        }
        finally
        {
            if (handle is not null)
                await handle.DisposeAsync().ConfigureAwait(false);
        }
    }

    private static bool IsSha(string? value) =>
        value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static bool IsSupportedExtension(string path) =>
        path.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase)
        || path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase);
}
