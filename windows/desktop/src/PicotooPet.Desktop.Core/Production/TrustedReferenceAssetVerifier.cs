namespace PicotooPet.Desktop.Core.Production;

/// <summary>Untrusted candidate; not a permission receipt. Every field must match authenticated Core approval.</summary>
public sealed record TrustedReferenceDescriptor(
    string ApprovalId, string ShotId, string AssetId, string RelativePath, string Sha256, long ByteLength);

/// <summary>Consumer-owned authenticated Core boundary. No local-disk or manifest-only implementation is valid.</summary>
public interface ITrustedReferenceApprovalSource
{
    Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken cancellationToken);
}

/// <summary>
/// Bind directly to ProductionLocalEnvironment.ResolveUnderRoot / AssertNoLinkEscape /
/// IsOrdinaryFile / Sha256FileAsync in Desktop. Core cannot depend on Desktop; do not copy its policy here.
/// </summary>
public sealed record TrustedReferenceFilePolicy(
    Func<string, string, bool, string> ResolveUnderRoot,
    Action<string, string> AssertNoLinkEscape,
    Func<string, bool> IsOrdinaryFile,
    Func<string, CancellationToken, Task<string>> Sha256FileAsync);

/// <summary>Process-bound read lease; consumer must retain through Comfy LoadImage completion.</summary>
public sealed class VerifiedReferenceAsset : IDisposable
{
    internal VerifiedReferenceAsset(string fullPath, string relativePath)
    {
        FullPath = fullPath;
        RelativePath = relativePath;
    }
    public string FullPath { get; }
    public string RelativePath { get; }
    public void Dispose() { }
}

/// <summary>Independent integrity boundary; authenticated Core approval integration is not supplied here.</summary>
public sealed class TrustedReferenceAssetVerifier
{
    public TrustedReferenceAssetVerifier(string managedRoot, TrustedReferenceFilePolicy policy, ITrustedReferenceApprovalSource approvals)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(managedRoot);
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentNullException.ThrowIfNull(approvals);
    }

    public Task<VerifiedReferenceAsset> VerifyAsync(TrustedReferenceDescriptor descriptor, string expectedShotId,
        string expectedAssetId, CancellationToken cancellationToken = default) =>
        throw new InvalidDataException("TRUSTED_REFERENCE_NOT_IMPLEMENTED_RED");
}
