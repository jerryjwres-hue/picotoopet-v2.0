using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>项目目录的稳定只读合同。</summary>
public sealed record ProjectRecord(
    [property: JsonPropertyName("project_id")] string ProjectId,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("project_type")] string ProjectType,
    [property: JsonPropertyName("source_app")] string SourceApp,
    [property: JsonPropertyName("classification")] string Classification,
    [property: JsonPropertyName("workspace_root")] string? WorkspaceRoot,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

/// <summary>创建项目仅提交元数据，不扫描 workspace_root。</summary>
public sealed record ProjectCreateRequest(
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("project_type")] string ProjectType,
    [property: JsonPropertyName("source_app")] string SourceApp,
    [property: JsonPropertyName("classification")] string Classification = "INTERNAL",
    [property: JsonPropertyName("workspace_root")] string? WorkspaceRoot = null);

/// <summary>工作流步骤的持久化快照。</summary>
public sealed record WorkflowStepRecord(
    [property: JsonPropertyName("workflow_id")] string WorkflowId,
    [property: JsonPropertyName("step_key")] string StepKey,
    [property: JsonPropertyName("ordinal")] int Ordinal,
    [property: JsonPropertyName("task_type")] string TaskType,
    [property: JsonPropertyName("required_capability")] string? RequiredCapability,
    [property: JsonPropertyName("depends_on")] string[] DependsOn,
    [property: JsonPropertyName("payload")] JsonElement Payload,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("task_id")] string? TaskId,
    [property: JsonPropertyName("attempt_count")] int AttemptCount,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage);

/// <summary>工作流持久化快照。</summary>
public sealed record WorkflowRecord(
    [property: JsonPropertyName("workflow_id")] string WorkflowId,
    [property: JsonPropertyName("project_id")] string? ProjectId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("priority")] int Priority,
    [property: JsonPropertyName("max_concurrency")] int MaxConcurrency,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("started_at")] DateTimeOffset? StartedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("steps")] WorkflowStepRecord[] Steps);

/// <summary>工作流安全创建请求；TaskType 仍由 Worker 注册表决定是否可执行。</summary>
public sealed record WorkflowStepCreateRequest(
    [property: JsonPropertyName("step_key")] string StepKey,
    [property: JsonPropertyName("task_type")] string TaskType,
    [property: JsonPropertyName("depends_on")] string[] DependsOn,
    [property: JsonPropertyName("required_capability")] string? RequiredCapability,
    [property: JsonPropertyName("payload")] object Payload,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts = 3,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds = 3600);

/// <summary>工作流安全创建请求。</summary>
public sealed record WorkflowCreateRequest(
    [property: JsonPropertyName("project_id")] string? ProjectId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("priority")] int Priority,
    [property: JsonPropertyName("max_concurrency")] int MaxConcurrency,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("steps")] WorkflowStepCreateRequest[] Steps);

/// <summary>Worker 类型能力快照。</summary>
public sealed record CapabilityRegistrationRecord(
    [property: JsonPropertyName("worker_id")] string WorkerId,
    [property: JsonPropertyName("capability")] string Capability,
    [property: JsonPropertyName("task_types")] string[] TaskTypes,
    [property: JsonPropertyName("healthy")] bool Healthy,
    [property: JsonPropertyName("metadata")] JsonElement Metadata,
    [property: JsonPropertyName("heartbeat_at")] DateTimeOffset HeartbeatAt,
    [property: JsonPropertyName("registered_at")] DateTimeOffset RegisteredAt);

/// <summary>自动化健康聚合，不包含 Token、路径或日志正文。</summary>
public sealed record AutomationHealthResponse(
    [property: JsonPropertyName("workflow_counts")] Dictionary<string, int> WorkflowCounts,
    [property: JsonPropertyName("task_counts")] Dictionary<string, int> TaskCounts,
    [property: JsonPropertyName("capabilities")] CapabilityRegistrationRecord[] Capabilities,
    [property: JsonPropertyName("database_schema_version")] int DatabaseSchemaVersion,
    [property: JsonPropertyName("observed_at")] DateTimeOffset ObservedAt);

/// <summary>结构化诊断事实。</summary>
public sealed record AutomationDiagnosticFact(
    [property: JsonPropertyName("workflow_id")] string? WorkflowId,
    [property: JsonPropertyName("step_key")] string? StepKey,
    [property: JsonPropertyName("task_id")] string? TaskId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("error_code")] string? ErrorCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("trace_id")] string? TraceId,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

/// <summary>结构化诊断快照。</summary>
public sealed record AutomationDiagnosticsResponse(
    [property: JsonPropertyName("facts")] AutomationDiagnosticFact[] Facts,
    [property: JsonPropertyName("observed_at")] DateTimeOffset ObservedAt);
