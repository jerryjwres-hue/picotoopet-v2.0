using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Work Package v1 中单个声明输入；路径只能由生产者包内 manifest 提供并由 Core 再验证。</summary>
public sealed record BusinessInputDescriptor(
    [property: JsonPropertyName("artifact_id")] string ArtifactId,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("media_type")] string MediaType,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("size_bytes")] long SizeBytes,
    [property: JsonPropertyName("record_key_field")] string? RecordKeyField);

/// <summary>业务程序生成的严格 Work Package v1 manifest。</summary>
public sealed record BusinessWorkPackageManifest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("package_id")] string PackageId,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("producer_id")] string ProducerId,
    [property: JsonPropertyName("producer_version")] string ProducerVersion,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("analysis_profile")] string AnalysisProfile,
    [property: JsonPropertyName("objective")] string Objective,
    [property: JsonPropertyName("inputs")] BusinessInputDescriptor[] Inputs);

/// <summary>Mac Core 的耐久业务包事实。</summary>
public sealed record BusinessWorkPackageRecord(
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("idempotency_key")] string IdempotencyKey,
    [property: JsonPropertyName("producer_id")] string ProducerId,
    [property: JsonPropertyName("producer_version")] string ProducerVersion,
    [property: JsonPropertyName("project_key")] string ProjectKey,
    [property: JsonPropertyName("analysis_profile")] string AnalysisProfile,
    [property: JsonPropertyName("objective")] string Objective,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("compressed_size_bytes")] long CompressedSizeBytes,
    [property: JsonPropertyName("uncompressed_size_bytes")] long? UncompressedSizeBytes,
    [property: JsonPropertyName("package_object_relpath")] string? PackageObjectRelpath,
    [property: JsonPropertyName("preprocess_digest")] string? PreprocessDigest,
    [property: JsonPropertyName("result_package_id")] string? ResultPackageId,
    [property: JsonPropertyName("deep_ai_handoff_id")] string? DeepAiHandoffId,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("error_message")] string? ErrorMessage,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt);

/// <summary>可恢复上传会话；VerifiedSizeBytes 是下一块的唯一合法 offset。</summary>
public sealed record BusinessUploadSessionRecord(
    [property: JsonPropertyName("upload_session_id")] string UploadSessionId,
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("total_size_bytes")] long TotalSizeBytes,
    [property: JsonPropertyName("verified_size_bytes")] long VerifiedSizeBytes,
    [property: JsonPropertyName("chunk_size_bytes")] int ChunkSizeBytes,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("staging_relpath")] string StagingRelpath,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finalized_at")] DateTimeOffset? FinalizedAt);

/// <summary>准备上传只绑定 manifest、完整 ZIP digest 与大小，不接收路径/模型/prompt。</summary>
public sealed record BusinessUploadPrepareRequest(
    [property: JsonPropertyName("manifest")] BusinessWorkPackageManifest Manifest,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("total_size_bytes")] long TotalSizeBytes);

/// <summary>准备结果同时返回耐久包事实与可恢复会话。</summary>
public sealed record BusinessUploadPrepareResponse(
    [property: JsonPropertyName("work_package")] BusinessWorkPackageRecord WorkPackage,
    [property: JsonPropertyName("upload_session")] BusinessUploadSessionRecord UploadSession);

/// <summary>已通过质量门的结构化 Result Package 元数据。</summary>
public sealed record BusinessResultPackageRecord(
    [property: JsonPropertyName("result_package_id")] string ResultPackageId,
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("analysis_profile")] string AnalysisProfile,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("preprocess_digest")] string PreprocessDigest,
    [property: JsonPropertyName("model_adapter_version")] string ModelAdapterVersion,
    [property: JsonPropertyName("configured_model_id")] string ConfiguredModelId,
    [property: JsonPropertyName("template_version")] string TemplateVersion,
    [property: JsonPropertyName("quality_outcome")] string QualityOutcome,
    [property: JsonPropertyName("result_digest")] string ResultDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("result")] JsonElement Result,
    [property: JsonPropertyName("warnings")] string[] Warnings,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

/// <summary>仅供人工 Web GPT 异常路径导出的脱敏 Handoff 元数据。</summary>
public sealed record DeepAiHandoffRecord(
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("work_package_id")] string WorkPackageId,
    [property: JsonPropertyName("source_digest")] string SourceDigest,
    [property: JsonPropertyName("preprocess_digest")] string PreprocessDigest,
    [property: JsonPropertyName("local_result_digest")] string LocalResultDigest,
    [property: JsonPropertyName("quality_reasons")] string[] QualityReasons,
    [property: JsonPropertyName("return_schema")] JsonElement ReturnSchema,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("package_relpath")] string PackageRelpath,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);
