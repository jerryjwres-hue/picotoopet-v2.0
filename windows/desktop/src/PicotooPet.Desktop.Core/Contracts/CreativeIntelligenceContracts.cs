using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>可进入 Creative Intelligence 的 2.3.18.1 PASS Result Package 安全投影。</summary>
public sealed record CreativeEligibleSourceRecord(
    [property: JsonPropertyName("result_package_id")] string ResultPackageId,
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("analysis_profile")] string AnalysisProfile,
    [property: JsonPropertyName("result_digest")] string ResultDigest,
    [property: JsonPropertyName("summary")] string Summary,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>准备创意任务只接受来源、固定 Profile、业务目标与幂等键。</summary>
public sealed record CreativeJobCreateRequest(
    [property: JsonPropertyName("source_result_package_ids")] string[] SourceResultPackageIds,
    [property: JsonPropertyName("creative_profile")] string CreativeProfile,
    [property: JsonPropertyName("creative_objective")] string? CreativeObjective,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey);

/// <summary>Mac Core 持久化的 Creative Job。</summary>
public sealed record CreativeJobRecord(
    [property: JsonPropertyName("creative_job_id")] string CreativeJobId,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("creative_profile")] string CreativeProfile,
    [property: JsonPropertyName("creative_objective")] string? CreativeObjective,
    [property: JsonPropertyName("objective_digest")] string ObjectiveDigest,
    [property: JsonPropertyName("source_set_digest")] string SourceSetDigest,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("current_stage")] string? CurrentStage,
    [property: JsonPropertyName("creative_package_id")] string? CreativePackageId,
    [property: JsonPropertyName("deep_ai_handoff_id")] string? DeepAiHandoffId,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>不可变 Creative Package 的安全元数据。</summary>
public sealed record CreativePackageRecord(
    [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
    [property: JsonPropertyName("creative_job_id")] string CreativeJobId,
    [property: JsonPropertyName("source_set_digest")] string SourceSetDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("manifest")] JsonElement Manifest,
    [property: JsonPropertyName("quality_outcome")] string QualityOutcome,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>仅供人工 Web GPT 异常路径导出的脱敏 Creative Handoff。</summary>
public sealed record CreativeDeepAiHandoffRecord(
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("creative_job_id")] string CreativeJobId,
    [property: JsonPropertyName("stage_kind")] string StageKind,
    [property: JsonPropertyName("source_set_digest")] string SourceSetDigest,
    [property: JsonPropertyName("failed_result_digest")] string FailedResultDigest,
    [property: JsonPropertyName("quality_reasons")] string[] QualityReasons,
    [property: JsonPropertyName("return_schema")] JsonElement ReturnSchema,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
