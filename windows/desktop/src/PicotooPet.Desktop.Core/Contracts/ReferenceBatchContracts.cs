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
    public static void ValidateRequest(ReferenceBatchRequest request) =>
        throw new NotImplementedException("RED: reference batch request validation");

    public static void ValidateReceipt(ReferenceBatchRequest request, ReferenceBatchReceipt receipt) =>
        throw new NotImplementedException("RED: reference batch receipt binding");

    public static string IdempotencyKey(ReferenceBatchRequest request) =>
        throw new NotImplementedException("RED: reference batch deterministic idempotency");
}
