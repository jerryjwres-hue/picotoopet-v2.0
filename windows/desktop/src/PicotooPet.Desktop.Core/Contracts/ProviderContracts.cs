using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Contracts;

/// <summary>Mac Core 固定的真实 Codex 低预算；Windows 只能读取，不能扩大。</summary>
public sealed record ProviderBudgetRecord(
    [property: JsonPropertyName("max_turns")] int MaxTurns,
    [property: JsonPropertyName("timeout_seconds")] int TimeoutSeconds,
    [property: JsonPropertyName("max_changed_files")] int MaxChangedFiles,
    [property: JsonPropertyName("max_file_bytes")] int MaxFileBytes,
    [property: JsonPropertyName("max_return_bytes")] int MaxReturnBytes,
    [property: JsonPropertyName("automatic_retries")] int AutomaticRetries,
    [property: JsonPropertyName("concurrency")] int Concurrency,
    [property: JsonPropertyName("network_tools_allowed")] bool NetworkToolsAllowed)
{
    /// <summary>仅供离线 WPF smoke 使用的冻结预算投影。</summary>
    public static ProviderBudgetRecord Fixed { get; } = new(
        8,
        900,
        5,
        65536,
        262144,
        0,
        1,
        NetworkToolsAllowed: false);
}

/// <summary>不包含凭据、账户余额或 Usage 页面内容的 Provider 就绪状态。</summary>
public sealed record ProviderStatusRecord(
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("readiness")] string Readiness,
    [property: JsonPropertyName("real_execution_default")] bool RealExecutionDefault,
    [property: JsonPropertyName("usage_machine_readable")] bool UsageMachineReadable,
    [property: JsonPropertyName("execution_host")] string ExecutionHost,
    [property: JsonPropertyName("message")] string Message);

/// <summary>Windows 唯一允许提交的账户层人工额度确认。</summary>
public sealed record ProviderUsageConfirmationRequest(
    [property: JsonPropertyName("status")] string Status);

/// <summary>人工确认与 Handoff digest、固定预算及短期过期时间的安全绑定。</summary>
public sealed record ProviderUsageConfirmationRecord(
    [property: JsonPropertyName("confirmation_id")] string ConfirmationId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("budget")] ProviderBudgetRecord Budget,
    [property: JsonPropertyName("confirmed_at")] DateTimeOffset ConfirmedAt,
    [property: JsonPropertyName("expires_at")] DateTimeOffset ExpiresAt);

/// <summary>真实 Codex Session 的 Windows 安全投影；不含 transcript、密钥、命令或文件正文。</summary>
public sealed record ProviderSessionRecord(
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("handoff_id")] string HandoffId,
    [property: JsonPropertyName("provider")] string Provider,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("request_digest")] string RequestDigest,
    [property: JsonPropertyName("package_digest")] string PackageDigest,
    [property: JsonPropertyName("budget")] ProviderBudgetRecord Budget,
    [property: JsonPropertyName("turns_used")] int TurnsUsed,
    [property: JsonPropertyName("elapsed_seconds")] int ElapsedSeconds,
    [property: JsonPropertyName("changed_file_count")] int ChangedFileCount,
    [property: JsonPropertyName("return_id")] string? ReturnId,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("provider_usage_unknown")] bool ProviderUsageUnknown,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt,
    [property: JsonPropertyName("updated_at")] DateTimeOffset UpdatedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt,
    [property: JsonPropertyName("execution_notice")] string ExecutionNotice);
