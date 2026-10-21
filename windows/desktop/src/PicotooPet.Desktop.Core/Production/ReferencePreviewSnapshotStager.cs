namespace PicotooPet.Desktop.Core.Production;

/// <summary>Preview observation only; neither this DTO nor local bytes grant production permission.</summary>
public sealed record ReferencePreviewSnapshot(string InputRelativePath, string Sha256, long Bytes, string Format);

/// <summary>Consumer binds the four existing ProductionLocalEnvironment methods without copying policy.</summary>
public sealed record ReferencePreviewFilePolicy(
    Func<string, string, bool, string> ResolveUnderRoot,
    Action<string, string> AssertNoLinkEscape,
    Func<string, bool> IsOrdinaryFile,
    Func<string, CancellationToken, Task<string>> Sha256FileAsync);

public sealed class ReferencePreviewSnapshotStager
{
    public const int MaxBytes = 32 * 1024 * 1024;
    private readonly string _inputRoot;

    public ReferencePreviewSnapshotStager(string inputRoot, ReferencePreviewFilePolicy policy,
        Func<byte[], string, CancellationToken, Task> validateImage)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(inputRoot);
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentNullException.ThrowIfNull(validateImage);
        _inputRoot = inputRoot;
    }

    public Task<ReferencePreviewSnapshot> StageAsync(string sourcePath, string shotId, CancellationToken cancellationToken = default) =>
        throw new InvalidDataException("REFERENCE_STAGER_NOT_IMPLEMENTED_RED:" + _inputRoot);

    public Task<byte[]> ReadVerifiedAsync(ReferencePreviewSnapshot snapshot, CancellationToken cancellationToken = default) =>
        throw new InvalidDataException("REFERENCE_STAGER_NOT_IMPLEMENTED_RED:" + _inputRoot);
}
