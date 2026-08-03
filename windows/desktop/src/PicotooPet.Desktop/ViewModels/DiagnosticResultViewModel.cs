using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>把严格诊断合同映射为固定卡片文本，不渲染任意 JSON。</summary>
public sealed class DiagnosticResultViewModel
{
    private DiagnosticResultViewModel(
        bool isAvailable,
        string statusText,
        string generatedAtText,
        string coreText,
        string workerText,
        string queueText,
        string checksText,
        string warningsText)
    {
        IsAvailable    = isAvailable;
        StatusText     = statusText;
        GeneratedAtText = generatedAtText;
        CoreText       = coreText;
        WorkerText     = workerText;
        QueueText      = queueText;
        ChecksText     = checksText;
        WarningsText   = warningsText;
    }

    public bool IsAvailable { get; }
    public string StatusText { get; }
    public string GeneratedAtText { get; }
    public string CoreText { get; }
    public string WorkerText { get; }
    public string QueueText { get; }
    public string ChecksText { get; }
    public string WarningsText { get; }

    /// <summary>验证固定 schema 和集合后生成安全结果卡片。</summary>
    public static DiagnosticResultViewModel FromResult(DiagnosticSnapshotResult result)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (!string.Equals(result.SchemaVersion, "1.0", StringComparison.Ordinal))
        {
            throw new InvalidDataException("诊断结果 schema_version 不受支持。");
        }
        if (result.Checks is null || result.Warnings is null)
        {
            throw new InvalidDataException("诊断结果缺少固定检查或警告字段。");
        }

        return new DiagnosticResultViewModel(
            isAvailable: true,
            statusText: "诊断结果已通过固定合同校验。",
            generatedAtText: result.GeneratedAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz"),
            coreText: FormatCore(result.Core),
            workerText: FormatWorker(result.Worker),
            queueText: FormatQueue(result.Queue),
            checksText: FormatChecks(result.Checks),
            warningsText: FormatWarnings(result.Warnings));
    }

    /// <summary>生成不会抛出绑定异常的安全错误卡片。</summary>
    public static DiagnosticResultViewModel FromError(string message)
    {
        var safeMessage = string.IsNullOrWhiteSpace(message)
            ? "诊断结果暂时无法显示。"
            : message.Trim();
        return new DiagnosticResultViewModel(
            isAvailable: false,
            statusText: safeMessage,
            generatedAtText: "—",
            coreText: "—",
            workerText: "—",
            queueText: "—",
            checksText: "—",
            warningsText: "—");
    }

    private static string FormatCore(DiagnosticCoreResult? core) => core is null
        ? "本次结果未包含 Core 卡片。"
        : $"版本 {core.Version} · 状态 {core.HealthState} · DB schema {core.DatabaseSchemaVersion}";

    private static string FormatWorker(DiagnosticWorkerResult? worker)
    {
        if (worker is null)
        {
            return "本次结果未包含 Worker 卡片。";
        }
        var workerId = string.IsNullOrWhiteSpace(worker.WorkerId) ? "未提供标识" : worker.WorkerId;
        var supported = worker.SupportedTaskTypes is null || worker.SupportedTaskTypes.Count == 0
            ? "无"
            : string.Join(", ", worker.SupportedTaskTypes.OrderBy(value => value, StringComparer.Ordinal));
        return $"{workerId} · {worker.State}/{worker.Reason} · 支持 {supported}";
    }

    private static string FormatQueue(DiagnosticQueueResult? queue)
    {
        if (queue is null)
        {
            return "本次结果未包含 Queue 卡片。";
        }
        var counts = queue.Counts is null || queue.Counts.Count == 0
            ? "无任务"
            : string.Join(
                ", ",
                queue.Counts
                    .OrderBy(pair => pair.Key, StringComparer.Ordinal)
                    .Select(pair => $"{pair.Key}={pair.Value}"));
        var oldest = queue.OldestQueuedAgeSeconds is null
            ? "无排队任务"
            : $"最老排队 {queue.OldestQueuedAgeSeconds.Value} 秒";
        return $"{counts} · {oldest}";
    }

    private static string FormatChecks(IReadOnlyList<DiagnosticCheckResult> checks)
    {
        if (checks.Count == 0)
        {
            throw new InvalidDataException("诊断结果 checks 不能为空。");
        }
        return string.Join(
            Environment.NewLine,
            checks.Select(check =>
            {
                if (string.IsNullOrWhiteSpace(check.Name)
                    || string.IsNullOrWhiteSpace(check.Status)
                    || string.IsNullOrWhiteSpace(check.ReasonCode))
                {
                    throw new InvalidDataException("诊断检查项缺少必需字段。");
                }
                return $"{check.Name}: {check.Status} ({check.ReasonCode})";
            }));
    }

    private static string FormatWarnings(IReadOnlyList<string> warnings) => warnings.Count == 0
        ? "无警告"
        : string.Join(Environment.NewLine, warnings.OrderBy(value => value, StringComparer.Ordinal));
}