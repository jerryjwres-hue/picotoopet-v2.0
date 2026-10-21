using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

public sealed record ReferenceCandidate(
    [property: JsonPropertyName("shot_id")] string ShotId,
    [property: JsonPropertyName("input_relative_path")] string InputRelativePath,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("bytes")] long Bytes,
    [property: JsonPropertyName("source_reference")] string SourceReference,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("rights_scope")] string RightsScope);

public sealed record ReferenceBatchRequest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("selected_references")] ReferenceCandidate[] SelectedReferences,
    [property: JsonPropertyName("user_confirms_preview_and_rights")] bool UserConfirmsPreviewAndRights,
    [property: JsonPropertyName("expires_seconds")] int ExpiresSeconds = 1800);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record RegisteredReferenceRecord(
    [property: JsonPropertyName("asset_id")] string AssetId,
    [property: JsonPropertyName("shot_id")] string ShotId,
    [property: JsonPropertyName("input_relative_path")] string InputRelativePath,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("bytes")] long Bytes,
    [property: JsonPropertyName("source_reference")] string SourceReference,
    [property: JsonPropertyName("source_digest")] string SourceDigest);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record ReferenceBatchReceipt(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("batch_id")] string BatchId,
    [property: JsonPropertyName("approval_id")] string ApprovalId,
    [property: JsonPropertyName("approval_request_digest")] string ApprovalRequestDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("expires_at")] DateTimeOffset ExpiresAt,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("references")] RegisteredReferenceRecord[] References);

public static class ReferenceBatchValidation
{
    private const string Schema = "reference_batch.v1";
    private const string RightsScope = "wan22.i2v.production.v1";
    private const long MaxBytes = 32L * 1024 * 1024;

    public static void ValidateRequest(ReferenceBatchRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.SchemaVersion != Schema || !IsUuid(request.GoalId)
            || !IsUuid(request.CreativePackageId) || !IsDigest(request.CreativePackageDigest)
            || !request.UserConfirmsPreviewAndRights || request.ExpiresSeconds is < 60 or > 3600
            || request.SelectedReferences is not { Length: >= 1 and <= 12 })
        {
            throw new ArgumentException("REFERENCE_BATCH_REQUEST_INVALID", nameof(request));
        }

        var shots = new HashSet<string>(StringComparer.Ordinal);
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var candidate in request.SelectedReferences)
        {
            if (candidate is null || !IsCandidate(candidate)
                || !shots.Add(candidate.ShotId) || !paths.Add(candidate.InputRelativePath))
            {
                throw new ArgumentException("REFERENCE_BATCH_CANDIDATE_INVALID", nameof(request));
            }
        }
    }

    public static void ValidateReceipt(ReferenceBatchRequest request, ReferenceBatchReceipt receipt)
    {
        ValidateRequest(request);
        ValidateReceiptIdentity(receipt);
        if (receipt.GoalId != request.GoalId
            || receipt.CreativePackageId != request.CreativePackageId
            || receipt.CreativePackageDigest != request.CreativePackageDigest
            || receipt.References.Length != request.SelectedReferences.Length)
        {
            throw new InvalidDataException("REFERENCE_BATCH_RECEIPT_MISMATCH");
        }
        var selected = request.SelectedReferences.ToDictionary(x => x.ShotId, StringComparer.Ordinal);
        foreach (var reference in receipt.References)
        {
            if (!selected.TryGetValue(reference.ShotId, out var candidate)
                || reference.InputRelativePath != candidate.InputRelativePath
                || reference.Sha256 != candidate.Sha256 || reference.Bytes != candidate.Bytes
                || reference.SourceReference != candidate.SourceReference
                || reference.SourceDigest != candidate.SourceDigest)
            {
                throw new InvalidDataException("REFERENCE_BATCH_RECEIPT_MISMATCH");
            }
        }
    }

    /// <summary>All request fields participate; only shot order is canonicalized.</summary>
    public static string IdempotencyKey(ReferenceBatchRequest request)
    {
        ValidateRequest(request);
        var canonical = request with
        {
            SelectedReferences = request.SelectedReferences.OrderBy(x => x.ShotId, StringComparer.Ordinal).ToArray(),
        };
        return "reference-batch-v1-" + Convert.ToHexStringLower(
            SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(canonical)));
    }

    internal static bool IsUuid(string? value) =>
        Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty;

    internal static void ValidateReceiptIdentity(ReferenceBatchReceipt receipt)
    {
        if (receipt is null || receipt.SchemaVersion != Schema
            || !IsUuid(receipt.BatchId) || !IsUuid(receipt.ApprovalId)
            || !IsUuid(receipt.GoalId) || !IsUuid(receipt.CreativePackageId)
            || !IsDigest(receipt.CreativePackageDigest) || !IsDigest(receipt.ApprovalRequestDigest)
            || receipt.Status is not ("Pending" or "Approved" or "Rejected" or "Revoked" or "Expired")
            || receipt.ExpiresAt == default || receipt.References is not { Length: >= 1 and <= 12 })
        {
            throw new InvalidDataException("REFERENCE_BATCH_RECEIPT_INVALID");
        }

        var assets = new HashSet<Guid>();
        var shots = new HashSet<string>(StringComparer.Ordinal);
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var reference in receipt.References)
        {
            if (reference is null || !IsUuid(reference.AssetId)
                || !assets.Add(Guid.Parse(reference.AssetId))
                || !IsCandidate(new ReferenceCandidate(reference.ShotId, reference.InputRelativePath,
                    reference.Sha256, reference.Bytes, reference.SourceReference, reference.SourceDigest, RightsScope))
                || !shots.Add(reference.ShotId) || !paths.Add(reference.InputRelativePath))
            {
                throw new InvalidDataException("REFERENCE_BATCH_RECEIPT_INVALID");
            }
        }
    }

    private static bool IsCandidate(ReferenceCandidate candidate) =>
        candidate.ShotId is { Length: >= 1 and <= 80 }
        && candidate.ShotId.All(x => char.IsAsciiLetterOrDigit(x) || x is '_' or '.' or '-')
        && IsManagedPath(candidate.InputRelativePath)
        && IsDigest(candidate.Sha256) && candidate.Bytes is > 0 and <= MaxBytes
        && candidate.SourceReference is "USER_SUPPLIED" or "LICENSED"
        && IsDigest(candidate.SourceDigest) && candidate.RightsScope == RightsScope;

    private static bool IsDigest(string? value) =>
        value is { Length: 64 } && value.All(x => x is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static bool IsManagedPath(string? path)
    {
        if (path is not { Length: >= 1 and <= 300 }
            || !path.StartsWith("PicotooPet/references/", StringComparison.Ordinal)
            || path.Contains('\\') || path.Contains(':')
            || !(path.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase)))
        {
            return false;
        }
        return path.Split('/').All(part => part is not ("" or "." or "..")
            && !part.EndsWith(' ') && !part.EndsWith('.'));
    }
}
