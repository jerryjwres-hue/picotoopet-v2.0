using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 公共健康响应。</summary>
public sealed record HealthResponse(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("database")] string? Database,
    [property: JsonPropertyName("version")] string? Version);

/// <summary>Mac Core 返回的 Worker 可用性快照。</summary>
public sealed record WorkerStatusResponse(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("available")] bool Available,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("reason")] string Reason,
    [property: JsonPropertyName("worker_id")] string? WorkerId,
    [property: JsonPropertyName("supported_task_types")] IReadOnlyList<string> SupportedTaskTypes,
    [property: JsonPropertyName("observed_at")] DateTimeOffset ObservedAt);

/// <summary>任务创建请求；幂等键通过 HTTP Header 发送。</summary>
public sealed record TaskCreateRequest(
    [property: JsonPropertyName("task_type")] string TaskType,
    [property: JsonPropertyName("payload")] IReadOnlyDictionary<string, object?> Payload,
    [property: JsonPropertyName("priority")] int Priority = 100,
    [property: JsonPropertyName("resource_tag")] string? ResourceTag = null,
    [property: JsonPropertyName("project_id")] string? ProjectId = null,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts = 3,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds = 3600,
    [property: JsonPropertyName("cloud_policy")] string CloudPolicy = "local_only");

/// <summary>固定系统诊断创建请求；客户端不能指定任意任务类型或服务端执行参数。</summary>
public sealed record DiagnosticSnapshotRequest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("sections")] IReadOnlyList<string> Sections)
{
    private static readonly IReadOnlyList<string> DefaultSections =
        Array.AsReadOnly(["core", "worker", "queue"]);

    /// <summary>创建包含全部安全白名单卡片的默认请求。</summary>
    public static DiagnosticSnapshotRequest CreateDefault() => new(
        "1.0",
        DefaultSections);
}

/// <summary>Mac Core 返回的稳定任务快照。</summary>
public sealed record TaskRecord(
    [property: JsonPropertyName("task_id")] string TaskId,
    [property: JsonPropertyName("parent_task_id")] string? ParentTaskId,
    [property: JsonPropertyName("project_id")] string? ProjectId,
    [property: JsonPropertyName("task_type")] string TaskType,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("priority")] int Priority,
    [property: JsonPropertyName("resource_tag")] string? ResourceTag,
    [property: JsonPropertyName("payload")] JsonElement Payload,
    [property: JsonPropertyName("attempt_count")] int AttemptCount,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("error_code")] string? ErrorCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("result_id")] string? ResultId = null);

/// <summary>审批中心读取的安全记录，不包含令牌、令牌哈希或原始任意路径。</summary>
public sealed record ApprovalRecord(
    [property: JsonPropertyName("approval_id")] string ApprovalId,
    [property: JsonPropertyName("task_id")] string? TaskId,
    [property: JsonPropertyName("approval_type")] string ApprovalType,
    [property: JsonPropertyName("scope_summary")] string ScopeSummary,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("requested_by")] string RequestedBy,
    [property: JsonPropertyName("resolved_by")] string? ResolvedBy,
    [property: JsonPropertyName("expires_at")] DateTimeOffset ExpiresAt,
    [property: JsonPropertyName("requested_at")] DateTimeOffset RequestedAt,
    [property: JsonPropertyName("resolved_at")] DateTimeOffset? ResolvedAt,
    [property: JsonPropertyName("decision_reason")] string? DecisionReason);

/// <summary>审批中心的摘要绑定终态决策。</summary>
public sealed record ApprovalDecisionRequest(
    [property: JsonPropertyName("decision")] string Decision,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("reason")] string Reason);

/// <summary>Phase 10A 由 Mac Core 发布的固定 Handoff 模板。</summary>
public sealed record HandoffTemplateRecord(
    [property: JsonPropertyName("template_id")] string TemplateId,
    [property: JsonPropertyName("display_name")] string DisplayName,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("provider_configured")] bool ProviderConfigured,
    [property: JsonPropertyName("repo_url")] string RepoUrl,
    [property: JsonPropertyName("base_ref")] string BaseRef,
    [property: JsonPropertyName("base_commit")] string BaseCommit);

/// <summary>Phase 10A 唯一允许的用户输入；不包含路径、命令、仓库或凭据。</summary>
public sealed record HandoffPrepareRequest(
    [property: JsonPropertyName("template_id")] string TemplateId,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("objective")] string Objective,
    [property: JsonPropertyName("expires_seconds")] int ExpiresSeconds);

/// <summary>Handoff 准备、审批和终态观察使用的固定安全投影。</summary>
public sealed record HandoffRecord(
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("template_id")] string TemplateId,
    [property: JsonPropertyName("template_name")] string TemplateName,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("objective_summary")] string ObjectiveSummary,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("provider_configured")] bool ProviderConfigured,
    [property: JsonPropertyName("repo_url")] string RepoUrl,
    [property: JsonPropertyName("base_ref")] string BaseRef,
    [property: JsonPropertyName("base_commit")] string BaseCommit,
    [property: JsonPropertyName("sensitivity")] string Sensitivity,
    [property: JsonPropertyName("planned_read_count")] int PlannedReadCount,
    [property: JsonPropertyName("planned_write_count")] int PlannedWriteCount,
    [property: JsonPropertyName("required_tests")] IReadOnlyList<string> RequiredTests,
    [property: JsonPropertyName("budget_summary")] string BudgetSummary,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("approval_id")] string? ApprovalId,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("expires_at")] DateTimeOffset ExpiresAt,
    [property: JsonPropertyName("security_boundaries")] IReadOnlyList<string> SecurityBoundaries);

/// <summary>诊断结果中的 Core 固定卡片。</summary>
public sealed record DiagnosticCoreResult(
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("health_state")] string HealthState,
    [property: JsonPropertyName("database_schema_version")] int DatabaseSchemaVersion);

/// <summary>诊断结果中的 Worker 固定卡片。</summary>
public sealed record DiagnosticWorkerResult(
    [property: JsonPropertyName("worker_id")] string? WorkerId,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("reason")] string Reason,
    [property: JsonPropertyName("supported_task_types")] IReadOnlyList<string> SupportedTaskTypes,
    [property: JsonPropertyName("last_heartbeat_at")] DateTimeOffset? LastHeartbeatAt);

/// <summary>诊断结果中的队列固定卡片。</summary>
public sealed record DiagnosticQueueResult(
    [property: JsonPropertyName("counts")] IReadOnlyDictionary<string, int> Counts,
    [property: JsonPropertyName("oldest_queued_age_seconds")] int? OldestQueuedAgeSeconds);

/// <summary>诊断结果中的固定检查项。</summary>
public sealed record DiagnosticCheckResult(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("reason_code")] string ReasonCode);

/// <summary>任务关联的严格系统诊断结果。</summary>
public sealed record DiagnosticSnapshotResult(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("generated_at")] DateTimeOffset GeneratedAt,
    [property: JsonPropertyName("core")] DiagnosticCoreResult? Core,
    [property: JsonPropertyName("worker")] DiagnosticWorkerResult? Worker,
    [property: JsonPropertyName("queue")] DiagnosticQueueResult? Queue,
    [property: JsonPropertyName("checks")] IReadOnlyList<DiagnosticCheckResult> Checks,
    [property: JsonPropertyName("warnings")] IReadOnlyList<string> Warnings);

/// <summary>系统状态响应；服务明细保留为 JSON，避免客户端强耦合。</summary>
public sealed record StatusResponse(
    [property: JsonPropertyName("task_counts")] IReadOnlyDictionary<string, int> TaskCounts,
    [property: JsonPropertyName("services")] JsonElement Services);

/// <summary>统一 API 错误外层。</summary>
public sealed record ApiErrorEnvelope(
    [property: JsonPropertyName("error")] ApiErrorDetail Error);

/// <summary>统一 API 错误明细。</summary>
public sealed record ApiErrorDetail(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("retryable")] bool Retryable,
    [property: JsonPropertyName("trace_id")] string? TraceId);
