namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// Actual local byte measurements while the existing native verifier pins all files.
/// NOT a signed/paired device proof, Core admission, durable lease or wire protocol.
/// No device identity, nonce, signature or "verified" flag is manufactured locally.
/// </summary>
internal sealed record ReferenceSnapshotMeasurement(
    string JobId, string TaskId, string ShotId, string AssetId, string ApprovalId,
    string PlanDigest, string GraphDigest, string SnapshotRelativePath,
    string SourceSha256, long SourceBytes, string SnapshotSha256, long SnapshotBytes,
    string ReceiptSha256, long ReceiptBytes);
