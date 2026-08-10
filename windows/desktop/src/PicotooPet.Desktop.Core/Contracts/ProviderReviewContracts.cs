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

/// <summary>Phase 10D-C 本地 Git Commit Candidate 的只读安全事实。</summary>
public sealed record ProviderCommitCandidateRecord(
    [property: JsonPropertyName("commit_candidate_id")] string CommitCandidateId,
    [property: JsonPropertyName("adoption_candidate_id")] string AdoptionCandidateId,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("return_id")] string ReturnId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("base_commit")] string BaseCommit,
    [property: JsonPropertyName("change_set_digest")] string ChangeSetDigest,
    [property: JsonPropertyName("approval_id")] string ApprovalId,
    [property: JsonPropertyName("message_preview")] string MessagePreview,
    [property: JsonPropertyName("message_digest")] string MessageDigest,
    [property: JsonPropertyName("tree_sha")] string? TreeSha,
    [property: JsonPropertyName("commit_sha")] string? CommitSha,
    [property: JsonPropertyName("local_ref")] string LocalRef,
    [property: JsonPropertyName("validation_checks")] IReadOnlyList<string> ValidationChecks,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("author_time_utc")] DateTimeOffset? AuthorTimeUtc,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>Phase 10E 受控远端 Push + Draft PR 的只读安全事实。</summary>
public sealed record ProviderPublicationCandidateRecord(
    [property: JsonPropertyName("publication_candidate_id")] string PublicationCandidateId,
    [property: JsonPropertyName("commit_candidate_id")] string CommitCandidateId,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("repo_url")] string RepoUrl,
    [property: JsonPropertyName("repository_slug")] string RepositorySlug,
    [property: JsonPropertyName("base_ref")] string BaseRef,
    [property: JsonPropertyName("base_commit")] string BaseCommit,
    [property: JsonPropertyName("commit_sha")] string CommitSha,
    [property: JsonPropertyName("change_set_digest")] string ChangeSetDigest,
    [property: JsonPropertyName("remote_ref")] string RemoteRef,
    [property: JsonPropertyName("remote_branch")] string RemoteBranch,
    [property: JsonPropertyName("approval_id")] string ApprovalId,
    [property: JsonPropertyName("pr_title_digest")] string PrTitleDigest,
    [property: JsonPropertyName("pr_body_digest")] string PrBodyDigest,
    [property: JsonPropertyName("pr_number")] int? PrNumber,
    [property: JsonPropertyName("pr_url")] string? PrUrl,
    [property: JsonPropertyName("pr_head_sha")] string? PrHeadSha,
    [property: JsonPropertyName("validation_checks")] IReadOnlyList<string> ValidationChecks,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);
