using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Return 安全投影中的固定验证检查。</summary>
public sealed record ReturnValidationCheckRecord(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("passed")] bool Passed);

/// <summary>不包含原始 payload 的有界 Return 事件摘要。</summary>
public sealed record ReturnEventSummaryRecord(
    [property: JsonPropertyName("sequence")] int Sequence,
    [property: JsonPropertyName("event_type")] string EventType,
    [property: JsonPropertyName("summary")] string Summary);

/// <summary>Phase 10B-A 供 Windows 观察的固定 Return 安全投影。</summary>
public sealed record ReturnRecord(
    [property: JsonPropertyName("return_id")] string ReturnId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("manifest_digest")] string ManifestDigest,
    [property: JsonPropertyName("changed_file_count")] int ChangedFileCount,
    [property: JsonPropertyName("event_count")] int EventCount,
    [property: JsonPropertyName("validation_checks")] IReadOnlyList<ReturnValidationCheckRecord> ValidationChecks,
    [property: JsonPropertyName("event_summaries")] IReadOnlyList<ReturnEventSummaryRecord> EventSummaries,
    [property: JsonPropertyName("quarantine_code")] string? QuarantineCode,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("execution_notice")] string ExecutionNotice);
