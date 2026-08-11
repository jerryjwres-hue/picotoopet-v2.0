using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>可进入 2.3.20.1 本地生产层的 creative_ready Creative Package 安全投影。</summary>
public sealed record ProductionEligibleCreativeRecord(
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_job_id")] string CreativeJobId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>生产任务创建只允许选择已存在 Creative Package、固定 Profile 与幂等键。</summary>
public sealed record ProductionJobCreateRequest(
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("production_profile")] string ProductionProfile,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>Core 编译出的单个 shot 固定执行计划。</summary>
public sealed record ProductionTaskPlanRecord(
    [property: JsonPropertyName("production_task_id")] string ProductionTaskId,
    [property: JsonPropertyName("shot_id")] string ShotId,
    [property: JsonPropertyName("order")] int Order,
    [property: JsonPropertyName("render_intent")] string RenderIntent,
    [property: JsonPropertyName("execution_disposition")] string ExecutionDisposition,
    [property: JsonPropertyName("workflow_id")] string? WorkflowId,
    [property: JsonPropertyName("positive_prompt")] string PositivePrompt,
    [property: JsonPropertyName("negative_prompt_policy_id")] string NegativePromptPolicyId,
    [property: JsonPropertyName("seed")] long Seed,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("fps")] int Fps,
    [property: JsonPropertyName("frame_count")] int FrameCount,
    [property: JsonPropertyName("trusted_input_asset_ref")] string? TrustedInputAssetRef);

/// <summary>Core 所有、Windows 只读的 Production Plan。</summary>
public sealed record ProductionPlanRecord(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("production_profile")] string ProductionProfile,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("tasks")] ProductionTaskPlanRecord[] Tasks);

/// <summary>Core 持久化的 Production Job；不携带任意 renderer 配置。</summary>
public sealed record ProductionJobRecord(
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("production_profile")] string ProductionProfile,
    [property: JsonPropertyName("plan_digest")] string? PlanDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("lease_executor_id")] string? LeaseExecutorId,
    [property: JsonPropertyName("lease_expires_at")] DateTimeOffset? LeaseExpiresAt,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>Core 保存的任务执行事实。</summary>
public sealed record ProductionTaskRecord(
    [property: JsonPropertyName("production_task_id")] string ProductionTaskId,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("shot_id")] string ShotId,
    [property: JsonPropertyName("order")] int Order,
    [property: JsonPropertyName("render_intent")] string RenderIntent,
    [property: JsonPropertyName("execution_disposition")] string ExecutionDisposition,
    [property: JsonPropertyName("workflow_id")] string? WorkflowId,
    [property: JsonPropertyName("task_plan")] ProductionTaskPlanRecord TaskPlan,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("attempt_count")] int AttemptCount,
    [property: JsonPropertyName("comfy_prompt_id")] string? ComfyPromptId,
    [property: JsonPropertyName("output_relpath")] string? OutputRelpath,
    [property: JsonPropertyName("output_sha256")] string? OutputSha256,
    [property: JsonPropertyName("output_bytes")] long? OutputBytes,
    [property: JsonPropertyName("output_mime_type")] string? OutputMimeType,
    [property: JsonPropertyName("output_width")] int? OutputWidth,
    [property: JsonPropertyName("output_height")] int? OutputHeight,
    [property: JsonPropertyName("output_frame_count")] int? OutputFrameCount,
    [property: JsonPropertyName("output_fps")] int? OutputFps,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>Windows executor 的短期 claim；durable task snapshot 决定重连后哪些 shot 仍可执行。</summary>
public sealed record ProductionClaimRecord
{
    [JsonConstructor]
    public ProductionClaimRecord(
        string productionJobId,
        string executorId,
        string leaseToken,
        DateTimeOffset leaseExpiresAt,
        ProductionPlanRecord plan,
        ProductionTaskRecord[] tasks)
    {
        ProductionJobId = productionJobId;
        ExecutorId = executorId;
        LeaseToken = leaseToken;
        LeaseExpiresAt = leaseExpiresAt;
        Tasks = tasks ?? Array.Empty<ProductionTaskRecord>();

        // ── Recovery rule: a Core-committed Succeeded shot is never submitted again ──
        var completedTaskIds = Tasks
            .Where(item => string.Equals(item.Status, "Succeeded", StringComparison.Ordinal))
            .Select(item => item.ProductionTaskId)
            .ToHashSet(StringComparer.Ordinal);
        Plan = plan with
        {
            Tasks = plan.Tasks
                .Where(item => !completedTaskIds.Contains(item.ProductionTaskId))
                .ToArray(),
        };
    }

    [JsonPropertyName("production_job_id")]
    public string ProductionJobId { get; }

    [JsonPropertyName("executor_id")]
    public string ExecutorId { get; }

    [JsonPropertyName("lease_token")]
    public string LeaseToken { get; }

    [JsonPropertyName("lease_expires_at")]
    public DateTimeOffset LeaseExpiresAt { get; }

    /// <summary>本次 claim 的 resume plan；已 Succeeded shot 被安全过滤。</summary>
    [JsonPropertyName("plan")]
    public ProductionPlanRecord Plan { get; }

    /// <summary>Core 返回的完整 durable task snapshot，用于审计与恢复判断。</summary>
    [JsonPropertyName("tasks")]
    public ProductionTaskRecord[] Tasks { get; }
}

/// <summary>生产任务 attempt 只提交执行身份、lease 与 Comfy prompt identity。</summary>
public sealed record ProductionTaskAttemptRequest(
    [property: JsonPropertyName("executor_id")] string ExecutorId,
    [property: JsonPropertyName("lease_token")] string LeaseToken,
    [property: JsonPropertyName("comfy_prompt_id")] string? ComfyPromptId);

/// <summary>最终本地渲染失败只回传有界身份、lease、prompt 与失败证据。</summary>
public sealed record ProductionTaskFailureRequest(
    [property: JsonPropertyName("executor_id")] string ExecutorId,
    [property: JsonPropertyName("lease_token")] string LeaseToken,
    [property: JsonPropertyName("comfy_prompt_id")] string? ComfyPromptId,
    [property: JsonPropertyName("failure_code")] string FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage);

/// <summary>Windows 回传的 content-addressed 输出证据。</summary>
public sealed record ProductionTaskCommitRequest(
    [property: JsonPropertyName("executor_id")] string ExecutorId,
    [property: JsonPropertyName("lease_token")] string LeaseToken,
    [property: JsonPropertyName("comfy_prompt_id")] string ComfyPromptId,
    [property: JsonPropertyName("output_relpath")] string OutputRelpath,
    [property: JsonPropertyName("output_sha256")] string OutputSha256,
    [property: JsonPropertyName("output_bytes")] long OutputBytes,
    [property: JsonPropertyName("mime_type")] string MimeType,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("frame_count")] int FrameCount,
    [property: JsonPropertyName("fps")] int Fps);

/// <summary>Core 保存的不可变 Production Package 元数据。</summary>
public sealed record ProductionPackageRecord(
    [property: JsonPropertyName("production_package_id")] string ProductionPackageId,
    [property: JsonPropertyName("production_job_id")] string ProductionJobId,
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("plan_digest")] string PlanDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("manifest")] JsonElement Manifest,
    [property: JsonPropertyName("quality_outcome")] string QualityOutcome,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
