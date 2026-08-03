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
    /// <summary>创建包含全部安全白名单卡片的默认请求。</summary>
    public static DiagnosticSnapshotRequest CreateDefault() => new(
        "1.0",
        new[] { "core", "worker", "queue" });
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
    [property: JsonPropertyName("result_id")] string? ResultId,
    [property: JsonPropertyName("attempt_count")] int AttemptCount,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("error_code")] string? ErrorCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage);

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
