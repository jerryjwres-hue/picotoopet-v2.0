using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Return 中一个只读、有界文本变更事实。</summary>
public sealed record ProviderReviewFileRecord(
    [property: JsonPropertyName("operation")] string Operation,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("size_bytes")] int SizeBytes,
    [property: JsonPropertyName("base_sha256")] string? BaseSha256,
    [property: JsonPropertyName("result_sha256")] string? ResultSha256);

/// <summary>Windows 可读取的 Review 安全投影；diff 只读且最大 128 KiB。</summary>
public sealed record ProviderReviewRecord(
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("return_id")] string? ReturnId,
    [property: JsonPropertyName("review_status")] string ReviewStatus,
    [property: JsonPropertyName("change_set_digest")] string? ChangeSetDigest,
    [property: JsonPropertyName("review_diff_digest")] string? ReviewDiffDigest,
    [property: JsonPropertyName("changed_file_count")] int ChangedFileCount,
    [property: JsonPropertyName("payload_bytes")] int PayloadBytes,
    [property: JsonPropertyName("files")] IReadOnlyList<ProviderReviewFileRecord> Files,
    [property: JsonPropertyName("review_diff")] string ReviewDiff,
    [property: JsonPropertyName("decision")] string? Decision,
    [property: JsonPropertyName("candidate_id")] string? CandidateId);

/// <summary>已接受 Return 在新隔离 worktree 中的本地落地候选事实。</summary>
public sealed record ProviderAdoptionCandidateRecord(
    [property: JsonPropertyName("candidate_id")] string CandidateId,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("return_id")] string ReturnId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("base_commit")] string BaseCommit,
    [property: JsonPropertyName("change_set_digest")] string ChangeSetDigest,
    [property: JsonPropertyName("changed_file_count")] int ChangedFileCount,
    [property: JsonPropertyName("validation_checks")] IReadOnlyList<string> ValidationChecks,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);
