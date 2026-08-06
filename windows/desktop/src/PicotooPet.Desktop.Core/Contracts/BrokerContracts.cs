using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 返回的 Broker Session 固定安全投影。</summary>
public sealed record BrokerSessionRecord(
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("return_id")] string? ReturnId,
    [property: JsonPropertyName("event_count")] int EventCount,
    [property: JsonPropertyName("sandbox_digest")] string? SandboxDigest,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt,
    [property: JsonPropertyName("execution_notice")] string ExecutionNotice);

/// <summary>预留响应；capability 只在本次执行内存中使用，不进入列表或日志。</summary>
public sealed record BrokerSessionCreateResult(
    [property: JsonPropertyName("record")] BrokerSessionRecord Record,
    [property: JsonPropertyName("capability")] string Capability);

/// <summary>Mock Broker Return 的固定文本文件条目。</summary>
public sealed record BrokerReturnFileRecord(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("content")] string Content);

/// <summary>Windows 子进程可提交给 Mac Core 的严格有界 Return 信封。</summary>
public sealed record MockBrokerReturnEnvelope(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("return_id")] string ReturnId,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("sandbox_digest")] string SandboxDigest,
    [property: JsonPropertyName("files")] IReadOnlyList<BrokerReturnFileRecord> Files);

/// <summary>父进程写入固定沙盒、供无界面子进程读取的非秘密安全事实。</summary>
public sealed record MockBrokerSessionInput(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("base_commit")] string BaseCommit);
