using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 提供的固定用户目标模板；Windows 不自行发明 task type。</summary>
public sealed record GoalTemplateRecord(
    [property: JsonPropertyName("goal_type")] string GoalType,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("example")] string Example);

/// <summary>Windows 唯一允许提交的高层目标字段；权限、优先级和工作流均由 Mac Core 决定。</summary>
public sealed record HumanGoalCreateRequest(
    [property: JsonPropertyName("goal_type")] string GoalType,
    [property: JsonPropertyName("objective")] string Objective,
    [property: JsonPropertyName("depth")] string Depth);

/// <summary>Mac Core 的耐久 Goal 只读投影。</summary>
public sealed record HumanGoalRecord(
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("parent_goal_id")] string? ParentGoalId,
    [property: JsonPropertyName("workflow_id")] string? WorkflowId,
    [property: JsonPropertyName("origin")] string Origin,
    [property: JsonPropertyName("intent_type")] string IntentType,
    [property: JsonPropertyName("priority_class")] string PriorityClass,
    [property: JsonPropertyName("objective")] string Objective,
    [property: JsonPropertyName("constraints")] JsonElement Constraints,
    [property: JsonPropertyName("budget_class")] string BudgetClass,
    [property: JsonPropertyName("pinned")] bool Pinned,
    [property: JsonPropertyName("score")] double? Score,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt);

/// <summary>已校验 Web GPT 交接包元数据；不含 Mac 本地文件路径。</summary>
public sealed record GoalHandoffMetadataRecord(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("goal_id")] string GoalId,
    [property: JsonPropertyName("handoff_ready")] bool HandoffReady,
    [property: JsonPropertyName("package_name")] string PackageName,
    [property: JsonPropertyName("package_sha256")] string PackageSha256,
    [property: JsonPropertyName("package_size_bytes")] long PackageSizeBytes,
    [property: JsonPropertyName("prompt_version")] string PromptVersion,
    [property: JsonPropertyName("manual_web_gpt_upload_required")] bool ManualWebGptUploadRequired);
