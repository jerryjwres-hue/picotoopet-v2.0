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
