using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>创建耐久 Business Pipeline Run 只绑定既有 Work Package、固定 adapter profile 与幂等键。</summary>
public sealed record BusinessPipelineRunCreateRequest(
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("adapter_profile")] string AdapterProfile,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>Mac Core 所有的 2.3.21.1 跨 Business/Creative/Production 编排事实。</summary>
public sealed record BusinessPipelineRunRecord(
    [property: JsonPropertyName("pipeline_run_id")] string PipelineRunId,
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("result_package_id")] string? ResultPackageId,
    [property: JsonPropertyName("creative_job_id")] string? CreativeJobId,
    [property: JsonPropertyName("creative_package_id")] string? CreativePackageId,
    [property: JsonPropertyName("production_job_id")] string? ProductionJobId,
    [property: JsonPropertyName("production_package_id")] string? ProductionPackageId,
    [property: JsonPropertyName("return_package_id")] string? ReturnPackageId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("producer_id")] string ProducerId,
    [property: JsonPropertyName("producer_version")] string ProducerVersion,
    [property: JsonPropertyName("adapter_profile")] string AdapterProfile,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("quality_outcome")] string? QualityOutcome,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>Core 保存的不可变 Business Return Package v1 元数据；Windows 不能重述 package path。</summary>
public sealed record BusinessReturnPackageRecord(
    [property: JsonPropertyName("return_package_id")] string ReturnPackageId,
    [property: JsonPropertyName("pipeline_run_id")] string PipelineRunId,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("manifest")] JsonElement Manifest,
    [property: JsonPropertyName("quality_outcome")] string QualityOutcome,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
