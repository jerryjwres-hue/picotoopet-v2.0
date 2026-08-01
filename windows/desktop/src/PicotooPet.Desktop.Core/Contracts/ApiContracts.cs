using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 公共健康响应。</summary>
public sealed record HealthResponse(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("database")] string? Database,
    [property: JsonPropertyName("version")] string? Version);

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
    [property: JsonPropertyName("error_message")] string? ErrorMessage);

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
