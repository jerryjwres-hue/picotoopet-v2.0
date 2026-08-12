using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>24.1 Shadow 请求只允许引用已经 AcceptedForShadow 的候选。</summary>
public sealed record QualityShadowRunCreateRequest(
    [property: JsonPropertyName("candidate_id")] string CandidateId);

/// <summary>Mac Core 持久化的 Shadow 运行事实；Windows 无权修改策略字段。</summary>
public sealed record QualityShadowRunRecord(
    [property: JsonPropertyName("shadow_run_id")] string ShadowRunId,
    [property: JsonPropertyName("candidate_id")] string CandidateId,
    [property: JsonPropertyName("evaluation_run_id")] string EvaluationRunId,
    [property: JsonPropertyName("snapshot_id")] string SnapshotId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("candidate_class")] string CandidateClass,
    [property: JsonPropertyName("candidate_digest")] string CandidateDigest,
    [property: JsonPropertyName("snapshot_digest")] string SnapshotDigest,
    [property: JsonPropertyName("evaluation_report_digest")] string EvaluationReportDigest,
    [property: JsonPropertyName("shadow_profile_id")] string ShadowProfileId,
    [property: JsonPropertyName("split_version")] string SplitVersion,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("verdict")] string Verdict,
    [property: JsonPropertyName("input_digest")] string InputDigest,
    [property: JsonPropertyName("report_digest")] string ReportDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("completed_at")] DateTimeOffset? CompletedAt);

/// <summary>Shadow arm 指标保留明确 numerator/denominator/availability；不接受用户公式。</summary>
public sealed record QualityShadowArmMetricRecord(
    [property: JsonPropertyName("metric_id")] string MetricId,
    [property: JsonPropertyName("shadow_run_id")] string ShadowRunId,
    [property: JsonPropertyName("arm")] string Arm,
    [property: JsonPropertyName("metric_name")] string MetricName,
    [property: JsonPropertyName("value")] double? Value,
    [property: JsonPropertyName("numerator")] double? Numerator,
    [property: JsonPropertyName("denominator")] double? Denominator,
    [property: JsonPropertyName("availability")] string Availability,
    [property: JsonPropertyName("arm_digest")] string ArmDigest);

/// <summary>Shadow review 使用闭合 action；AcceptedForPromotionReview 仍然只是事实。</summary>
public sealed record QualityShadowReviewRequest(
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>Shadow review append-only 响应。</summary>
public sealed record QualityShadowReviewRecord(
    [property: JsonPropertyName("review_id")] string ReviewId,
    [property: JsonPropertyName("shadow_run_id")] string ShadowRunId,
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
