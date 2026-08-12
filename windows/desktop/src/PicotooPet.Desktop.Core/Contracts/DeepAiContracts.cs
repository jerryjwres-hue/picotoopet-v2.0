using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>用户侧只提交已有 NEEDS_DEEP_AI source identity；无 provider/model/endpoint/prompt 字段。</summary>
public sealed record DeepAiEscalationPrepareRequest(
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("source_id")] string SourceId);

/// <summary>Core 冻结的 Paid-AI escalation 事实；Windows 只读。</summary>
public sealed record DeepAiEscalationRecord(
    [property: JsonPropertyName("escalation_job_id")] string EscalationJobId,
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("source_id")] string SourceId,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("policy_version")] string PolicyVersion,
    [property: JsonPropertyName("sanitized_package_relpath")] string SanitizedPackageRelpath,
    [property: JsonPropertyName("sanitized_package_digest")] string SanitizedPackageDigest,
    [property: JsonPropertyName("sanitizer_version")] string SanitizerVersion,
    [property: JsonPropertyName("provider_profile_id")] string ProviderProfileId,
    [property: JsonPropertyName("provider_profile_digest")] string ProviderProfileDigest,
    [property: JsonPropertyName("model_id")] string ModelId,
    [property: JsonPropertyName("max_input_tokens")] int MaxInputTokens,
    [property: JsonPropertyName("max_output_tokens")] int MaxOutputTokens,
    [property: JsonPropertyName("max_calls")] int MaxCalls,
    [property: JsonPropertyName("max_cost_usd")] decimal MaxCostUsd,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("approval_id")] string? ApprovalId,
    [property: JsonPropertyName("approval_digest")] string? ApprovalDigest,
    [property: JsonPropertyName("approval_expires_at")] DateTimeOffset? ApprovalExpiresAt,
    [property: JsonPropertyName("validation_outcome")] string? ValidationOutcome,
    [property: JsonPropertyName("accepted_result_digest")] string? AcceptedResultDigest,
    [property: JsonPropertyName("accepted_result_relpath")] string? AcceptedResultRelpath,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>Core-only readiness projection；批准不自动等于 ProviderReady。</summary>
public sealed record DeepAiReadinessRecord(
    [property: JsonPropertyName("escalation_job_id")] string EscalationJobId,
    [property: JsonPropertyName("execution_enabled")] bool ExecutionEnabled,
    [property: JsonPropertyName("provider_ready")] bool ProviderReady,
    [property: JsonPropertyName("reason_code")] string ReasonCode,
    [property: JsonPropertyName("manual_handoff_id")] string? ManualHandoffId);

/// <summary>审批预算下已经消费的不可逆 paid-provider usage。</summary>
public sealed record DeepAiUsageRecord(
    [property: JsonPropertyName("escalation_job_id")] string EscalationJobId,
    [property: JsonPropertyName("calls_used")] int CallsUsed,
    [property: JsonPropertyName("input_tokens")] int InputTokens,
    [property: JsonPropertyName("output_tokens")] int OutputTokens,
    [property: JsonPropertyName("cost_usd")] decimal CostUsd);

/// <summary>Human feedback 只记录事实；不会触发 Provider 或改变预算。</summary>
public sealed record DeepAiFeedbackRequest(
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("reason_tags")] string[] ReasonTags,
    [property: JsonPropertyName("final_content_digest")] string? FinalContentDigest,
    [property: JsonPropertyName("downstream_ref")] string? DownstreamRef,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>完整 Quality Learning observation，用于用户反馈响应。</summary>
public sealed record DeepAiLearningObservationRecord(
    [property: JsonPropertyName("event_id")] string EventId,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("source_id")] string SourceId,
    [property: JsonPropertyName("escalation_job_id")] string EscalationJobId,
    [property: JsonPropertyName("local_profile")] string? LocalProfile,
    [property: JsonPropertyName("local_model_id")] string? LocalModelId,
    [property: JsonPropertyName("local_template_version")] string? LocalTemplateVersion,
    [property: JsonPropertyName("local_attempt_count")] int? LocalAttemptCount,
    [property: JsonPropertyName("local_quality_outcome")] string LocalQualityOutcome,
    [property: JsonPropertyName("quality_reasons")] string[] QualityReasons,
    [property: JsonPropertyName("provider_profile_id")] string ProviderProfileId,
    [property: JsonPropertyName("provider_model_id")] string ProviderModelId,
    [property: JsonPropertyName("sanitized_input_digest")] string SanitizedInputDigest,
    [property: JsonPropertyName("paid_output_digest")] string? PaidOutputDigest,
    [property: JsonPropertyName("input_tokens")] int? InputTokens,
    [property: JsonPropertyName("output_tokens")] int? OutputTokens,
    [property: JsonPropertyName("cost_usd")] decimal? CostUsd,
    [property: JsonPropertyName("paid_validation_outcome")] string? PaidValidationOutcome,
    [property: JsonPropertyName("human_action")] string HumanAction,
    [property: JsonPropertyName("reason_tags")] string[] ReasonTags,
    [property: JsonPropertyName("final_content_digest")] string? FinalContentDigest,
    [property: JsonPropertyName("downstream_ref")] string? DownstreamRef);

/// <summary>Append-only learning summary；没有 prompt/model/provider/budget mutation 字段。</summary>
public sealed record DeepAiLearningEventRecord(
    [property: JsonPropertyName("event_id")] string EventId,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("source_kind")] string SourceKind,
    [property: JsonPropertyName("source_id")] string SourceId,
    [property: JsonPropertyName("local_quality_outcome")] string LocalQualityOutcome,
    [property: JsonPropertyName("escalation_job_id")] string? EscalationJobId,
    [property: JsonPropertyName("human_action")] string HumanAction,
    [property: JsonPropertyName("reason_tags")] string[] ReasonTags,
    [property: JsonPropertyName("final_content_digest")] string? FinalContentDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>23.1 snapshot 只允许 project/profile/time/stage/limit；没有执行策略字段。</summary>
public sealed record QualityEvaluationSnapshotCreateRequest(
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("evaluation_profile_id")] string EvaluationProfileId,
    [property: JsonPropertyName("stage_profile")] string? StageProfile,
    [property: JsonPropertyName("start_at")] DateTimeOffset? StartAt,
    [property: JsonPropertyName("end_at")] DateTimeOffset? EndAt,
    [property: JsonPropertyName("limit")] int Limit);

/// <summary>不可变 Evaluation Dataset Snapshot；Windows 只读展示 digest 与 member count。</summary>
public sealed record QualityEvaluationSnapshotRecord(
    [property: JsonPropertyName("snapshot_id")] string SnapshotId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("evaluation_profile_id")] string EvaluationProfileId,
    [property: JsonPropertyName("stage_profile")] string? StageProfile,
    [property: JsonPropertyName("start_at")] DateTimeOffset? StartAt,
    [property: JsonPropertyName("end_at")] DateTimeOffset? EndAt,
    [property: JsonPropertyName("limit_count")] int LimitCount,
    [property: JsonPropertyName("scope_digest")] string ScopeDigest,
    [property: JsonPropertyName("snapshot_digest")] string SnapshotDigest,
    [property: JsonPropertyName("member_count")] int MemberCount,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>Evaluation run 只能引用已冻结 snapshot。</summary>
public sealed record QualityEvaluationRunCreateRequest(
    [property: JsonPropertyName("snapshot_id")] string SnapshotId);

/// <summary>Deterministic evaluation run；23.1 不代表任何 runtime policy 已应用。</summary>
public sealed record QualityEvaluationRunRecord(
    [property: JsonPropertyName("evaluation_run_id")] string EvaluationRunId,
    [property: JsonPropertyName("snapshot_id")] string SnapshotId,
    [property: JsonPropertyName("evaluation_profile_id")] string EvaluationProfileId,
    [property: JsonPropertyName("rule_version")] string RuleVersion,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("report_digest")] string ReportDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("completed_at")] DateTimeOffset? CompletedAt);

/// <summary>Offline metric 保留显式 numerator/denominator 与 missing-data availability。</summary>
public sealed record QualityEvaluationMetricRecord(
    [property: JsonPropertyName("metric_id")] string MetricId,
    [property: JsonPropertyName("evaluation_run_id")] string EvaluationRunId,
    [property: JsonPropertyName("metric_name")] string MetricName,
    [property: JsonPropertyName("value")] double? Value,
    [property: JsonPropertyName("numerator")] double? Numerator,
    [property: JsonPropertyName("denominator")] double? Denominator,
    [property: JsonPropertyName("availability")] string Availability,
    [property: JsonPropertyName("cohort_dimension")] string? CohortDimension,
    [property: JsonPropertyName("cohort_key")] string? CohortKey,
    [property: JsonPropertyName("cohort_digest")] string CohortDigest);

/// <summary>Improvement Candidate 是审阅信号，不包含 replacement prompt/model/provider/budget。</summary>
public sealed record QualityImprovementCandidateRecord(
    [property: JsonPropertyName("candidate_id")] string CandidateId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("evaluation_run_id")] string EvaluationRunId,
    [property: JsonPropertyName("snapshot_id")] string SnapshotId,
    [property: JsonPropertyName("rule_version")] string RuleVersion,
    [property: JsonPropertyName("candidate_class")] string CandidateClass,
    [property: JsonPropertyName("cohort_dimension")] string? CohortDimension,
    [property: JsonPropertyName("cohort_key")] string? CohortKey,
    [property: JsonPropertyName("cohort_digest")] string CohortDigest,
    [property: JsonPropertyName("reason_codes")] string[] ReasonCodes,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("candidate_digest")] string CandidateDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

/// <summary>Candidate review 只有闭合集合 action + idempotency key。</summary>
public sealed record QualityImprovementCandidateReviewRequest(
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>AcceptedForShadow 只是 durable review fact；23.1 不执行 Shadow。</summary>
public sealed record QualityImprovementCandidateReviewRecord(
    [property: JsonPropertyName("review_id")] string ReviewId,
    [property: JsonPropertyName("candidate_id")] string CandidateId,
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
