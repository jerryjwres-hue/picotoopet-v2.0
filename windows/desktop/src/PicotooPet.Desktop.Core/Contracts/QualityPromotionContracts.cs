using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>25.1 Promotion 创建请求只能引用 Mac Core 已持久化的 Shadow run。</summary>
public sealed record QualityPromotionCreateRequest(
    [property: JsonPropertyName("shadow_run_id")] string ShadowRunId);

/// <summary>Promotion 版本是治理事实；25.1 Windows 不把它当作可执行策略。</summary>
public sealed record QualityPromotionRecord(
    [property: JsonPropertyName("promotion_id")] string PromotionId,
    [property: JsonPropertyName("shadow_run_id")] string ShadowRunId,
    [property: JsonPropertyName("candidate_id")] string CandidateId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("candidate_class")] string CandidateClass,
    [property: JsonPropertyName("candidate_digest")] string CandidateDigest,
    [property: JsonPropertyName("shadow_report_digest")] string ShadowReportDigest,
    [property: JsonPropertyName("evaluation_report_digest")] string EvaluationReportDigest,
    [property: JsonPropertyName("snapshot_digest")] string SnapshotDigest,
    [property: JsonPropertyName("promotion_profile_id")] string PromotionProfileId,
    [property: JsonPropertyName("slot_key")] string SlotKey,
    [property: JsonPropertyName("version_no")] int VersionNo,
    [property: JsonPropertyName("proposal_digest")] string ProposalDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("supersedes_promotion_id")] string? SupersedesPromotionId,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("activated_at")] DateTimeOffset? ActivatedAt,
    [property: JsonPropertyName("rolled_back_at")] DateTimeOffset? RolledBackAt);

/// <summary>激活/回滚审批请求必须回显 exact request digest，且没有 Prompt/Model/Provider 等自由字段。</summary>
public sealed record QualityPromotionApprovalRequestRecord(
    [property: JsonPropertyName("approval_request_id")] string ApprovalRequestId,
    [property: JsonPropertyName("promotion_id")] string PromotionId,
    [property: JsonPropertyName("approval_kind")] string ApprovalKind,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("rollback_reason_code")] string? RollbackReasonCode,
    [property: JsonPropertyName("restore_promotion_id")] string? RestorePromotionId,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("expires_at")] DateTimeOffset ExpiresAt,
    [property: JsonPropertyName("resolved_at")] DateTimeOffset? ResolvedAt);

/// <summary>激活/回滚决定仅包含闭合 decision、服务器 digest 与幂等键。</summary>
public sealed record QualityPromotionDecisionRequest(
    [property: JsonPropertyName("decision")] string Decision,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>回滚原因是三值闭合枚举的字符串表示，不允许自由文本进入 Core。</summary>
public sealed record QualityPromotionRollbackRequest(
    [property: JsonPropertyName("rollback_reason_code")] string RollbackReasonCode);

/// <summary>Promotion 决策事实是 append-only 审计记录。</summary>
public sealed record QualityPromotionDecisionRecord(
    [property: JsonPropertyName("decision_id")] string DecisionId,
    [property: JsonPropertyName("approval_request_id")] string ApprovalRequestId,
    [property: JsonPropertyName("promotion_id")] string PromotionId,
    [property: JsonPropertyName("decision")] string Decision,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("decision_digest")] string DecisionDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>Rollback 事实记录当前版本与直接恢复前任的不可变身份。</summary>
public sealed record QualityPromotionRollbackRecord(
    [property: JsonPropertyName("rollback_id")] string RollbackId,
    [property: JsonPropertyName("promotion_id")] string PromotionId,
    [property: JsonPropertyName("restore_promotion_id")] string? RestorePromotionId,
    [property: JsonPropertyName("approval_request_id")] string ApprovalRequestId,
    [property: JsonPropertyName("rollback_reason_code")] string RollbackReasonCode,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("rollback_digest")] string RollbackDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>Promotion 历史只读返回精确决策与 rollback 事实。</summary>
public sealed record QualityPromotionHistoryRecord(
    [property: JsonPropertyName("decisions")] IReadOnlyList<QualityPromotionDecisionRecord> Decisions,
    [property: JsonPropertyName("rollbacks")] IReadOnlyList<QualityPromotionRollbackRecord> Rollbacks);
