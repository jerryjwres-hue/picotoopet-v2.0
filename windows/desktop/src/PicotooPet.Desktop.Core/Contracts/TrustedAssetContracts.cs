using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>C006B1 受信图片资产的封闭常量；调用方不能自选 root、source kind 或相对路径。</summary>
public static class TrustedAssetConstants
{
    public const string ManagedRootId = "windows.comfy-input.v1";
    public const string SourceKind = "windows_user_import.v1";
    public const string ScopeAutonomousGoal = "autonomous_goal";
    public const string ScopeProject = "project";
    public const string MediaTypePng = "image/png";
    public const string MediaTypeJpeg = "image/jpeg";
    public const long MaxBytes = 50_000_000;
    public const int MaxDimension = 16_384;
    public const long MaxPixels = 36_000_000;
    public const string RelativeRoot = "PicotooPet/assets/v1";

    /// <summary>由 SHA-256 与规范媒体类型推导的内容寻址相对路径；与 Core 推导规则逐字一致。</summary>
    public static string DeriveRelativePath(string sha256, string mediaType)
    {
        var extension = mediaType switch
        {
            MediaTypePng => "png",
            MediaTypeJpeg => "jpg",
            _ => throw new ArgumentOutOfRangeException(nameof(mediaType)),
        };
        return $"{RelativeRoot}/{sha256[..2]}/{sha256}.{extension}";
    }
}

/// <summary>POST /api/v1/assets 只携带有界注册事实；不含源路径、URL、asset_id 或 managed_relpath。</summary>
public sealed record TrustedAssetRegisterRequest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("scope_kind")] string ScopeKind,
    [property: JsonPropertyName("scope_id")] string ScopeId,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("size_bytes")] long SizeBytes,
    [property: JsonPropertyName("media_type")] string MediaType,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("duration_ms")] long? DurationMs,
    [property: JsonPropertyName("managed_root_id")] string ManagedRootId,
    [property: JsonPropertyName("source_kind")] string SourceKind);

/// <summary>Core 签发的受信资产来源记录。</summary>
public sealed record TrustedAssetProvenanceRecord(
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("byte_authority")] string ByteAuthority,
    [property: JsonPropertyName("bytes_in_core")] bool BytesInCore);

/// <summary>Core 所有的不可变受信资产身份；不含任何绝对路径。</summary>
public sealed record TrustedAssetRecord(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("asset_id")] string AssetId,
    [property: JsonPropertyName("scope_kind")] string ScopeKind,
    [property: JsonPropertyName("scope_id")] string ScopeId,
    [property: JsonPropertyName("scope_key")] string ScopeKey,
    [property: JsonPropertyName("artifact_type")] string ArtifactType,
    [property: JsonPropertyName("classification")] string Classification,
    [property: JsonPropertyName("managed_root_id")] string ManagedRootId,
    [property: JsonPropertyName("managed_relpath")] string ManagedRelPath,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("size_bytes")] long SizeBytes,
    [property: JsonPropertyName("media_type")] string MediaType,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("duration_ms")] long? DurationMs,
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("provenance")] TrustedAssetProvenanceRecord Provenance,
    [property: JsonPropertyName("cloud_policy")] string CloudPolicy,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
