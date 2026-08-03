using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>把严格诊断合同映射为固定卡片文本，不渲染任意 JSON。</summary>
public sealed class DiagnosticResultViewModel
{
    private static readonly HashSet<string> PublicTaskStatuses = new(
        new[]
        {
            "Archived",
            "Cancelled",
            "Completed",
            "Created",
            "Failed",
            "Queued",
            "Retrying",
            "Running",
            "Validating",
            "WaitingForApproval",
            "WaitingForTool",
        },
        StringComparer.Ordinal);

    private static readonly HashSet<string> AllowedWarnings = new(
        new[]
        {
            "CORE_DEGRADED",
            "QUEUE_BACKLOG",
            "QUEUE_OLD",
            "WORKER_OFFLINE",
            "WORKER_STALE",
        },
        StringComparer.Ordinal);

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
        IsAvailable     = isAvailable;
        StatusText      = statusText;
        GeneratedAtText = generatedAtText;
        CoreText        = coreText;
        WorkerText      = workerText;
        QueueText       = queueText;
        ChecksText      = checksText;
        WarningsText    = warningsText;
    }

    public bool IsAvailable { get; }
    public string StatusText { get; }
    public string GeneratedAtText { get; }
    public string CoreText { get; }
    public string WorkerText { get; }
    public string QueueText { get; }
    public string ChecksText { get; }
    public string WarningsText { get; }

    /// <summary>验证固定 schema、白名单值和结构一致性后生成安全结果卡片。</summary>
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

        ValidateCore(result.Core);
        ValidateWorker(result.Worker);
        ValidateQueue(result.Queue);
        ValidateChecks(
            result.Checks,
            hasCore: result.Core is not null,
            hasWorker: result.Worker is not null,
            hasQueue: result.Queue is not null);
        ValidateWarnings(result.Warnings);

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

    private static void ValidateCore(DiagnosticCoreResult? core)
    {
        if (core is null)
        {
            return;
        }
        ValidateText(core.Version, "core.version", minLength: 1, maxLength: 64);
        if (core.HealthState is not ("online" or "degraded" or "offline"))
        {
            throw new InvalidDataException("诊断结果 core.health_state 不受支持。");
        }
        if (core.DatabaseSchemaVersion is < 0 or > 10_000)
        {
            throw new InvalidDataException("诊断结果 database_schema_version 超出范围。");
        }
    }

    private static void ValidateWorker(DiagnosticWorkerResult? worker)
    {
        if (worker is null)
        {
            return;
        }
        if (worker.WorkerId is not null)
        {
            ValidateText(worker.WorkerId, "worker.worker_id", minLength: 1, maxLength: 128);
        }
        if (worker.State is not ("starting" or "online" or "degraded" or "offline"))
        {
            throw new InvalidDataException("诊断结果 worker.state 不受支持。");
        }
        ValidateText(worker.Reason, "worker.reason", minLength: 1, maxLength: 100);
        if (worker.SupportedTaskTypes is null || worker.SupportedTaskTypes.Count > 32)
        {
            throw new InvalidDataException("诊断结果 supported_task_types 数量非法。");
        }
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var taskType in worker.SupportedTaskTypes)
        {
            ValidateText(taskType, "worker.supported_task_types", minLength: 1, maxLength: 100);
            if (!seen.Add(taskType))
            {
                throw new InvalidDataException("诊断结果 supported_task_types 不允许重复。");
            }
        }
    }

    private static void ValidateQueue(DiagnosticQueueResult? queue)
    {
        if (queue is null)
        {
            return;
        }
        if (queue.Counts is null || queue.Counts.Count > PublicTaskStatuses.Count)
        {
            throw new InvalidDataException("诊断结果 queue.counts 无效。");
        }
        foreach (var pair in queue.Counts)
        {
            if (!PublicTaskStatuses.Contains(pair.Key) || pair.Value < 0)
            {
                throw new InvalidDataException("诊断结果 queue.counts 包含未知状态或负值。");
            }
        }
        if (queue.OldestQueuedAgeSeconds is < 0 or > 315_360_000)
        {
            throw new InvalidDataException("诊断结果 oldest_queued_age_seconds 超出范围。");
        }
    }

    private static void ValidateChecks(
        IReadOnlyList<DiagnosticCheckResult> checks,
        bool hasCore,
        bool hasWorker,
        bool hasQueue)
    {
        if (checks.Count == 0 || checks.Count > 3)
        {
            throw new InvalidDataException("诊断结果 checks 数量非法。");
        }

        var expected = new HashSet<string>(StringComparer.Ordinal);
        if (hasCore) expected.Add("core_health");
        if (hasWorker) expected.Add("worker_heartbeat");
        if (hasQueue) expected.Add("queue_backlog");
        if (expected.Count != checks.Count)
        {
            throw new InvalidDataException("诊断结果卡片与 checks 数量不一致。");
        }

        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var check in checks)
        {
            if (check is null)
            {
                throw new InvalidDataException("诊断结果包含空检查项。");
            }
            if (!seen.Add(check.Name) || !expected.Contains(check.Name))
            {
                throw new InvalidDataException("诊断结果包含未知或重复检查项。");
            }
            if (check.Status is not ("pass" or "warn" or "fail"))
            {
                throw new InvalidDataException("诊断检查状态不受支持。");
            }
            if (!IsAllowedCheck(check))
            {
                throw new InvalidDataException("诊断检查原因码与状态不符合固定合同。");
            }
        }
    }

    private static bool IsAllowedCheck(DiagnosticCheckResult check) =>
        (check.Name, check.Status, check.ReasonCode) switch
        {
            ("core_health", "pass", "CORE_HEALTHY") => true,
            ("core_health", "warn", "CORE_DEGRADED") => true,
            ("core_health", "fail", "CORE_DEGRADED") => true,
            ("worker_heartbeat", "pass", "WORKER_ONLINE") => true,
            ("worker_heartbeat", "warn", "WORKER_STALE") => true,
            ("worker_heartbeat", "fail", "WORKER_OFFLINE") => true,
            ("queue_backlog", "pass", "QUEUE_HEALTHY") => true,
            ("queue_backlog", "warn", "QUEUE_BACKLOG") => true,
            ("queue_backlog", "warn", "QUEUE_OLD") => true,
            _ => false,
        };

    private static void ValidateWarnings(IReadOnlyList<string> warnings)
    {
        if (warnings.Count > AllowedWarnings.Count)
        {
            throw new InvalidDataException("诊断结果 warnings 数量非法。");
        }
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var warning in warnings)
        {
            if (!AllowedWarnings.Contains(warning) || !seen.Add(warning))
            {
                throw new InvalidDataException("诊断结果包含未知或重复警告。");
            }
        }
    }

    private static void ValidateText(
        string? value,
        string field,
        int minLength,
        int maxLength)
    {
        if (value is null
            || value.Length < minLength
            || value.Length > maxLength
            || value.Any(char.IsControl))
        {
            throw new InvalidDataException($"诊断结果 {field} 包含非法文本。");
        }
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
        var supported = worker.SupportedTaskTypes.Count == 0
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
        var counts = queue.Counts.Count == 0
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

    private static string FormatChecks(IReadOnlyList<DiagnosticCheckResult> checks) =>
        string.Join(
            Environment.NewLine,
            checks.Select(check =>
                $"{check.Name}: {check.Status} ({check.ReasonCode})"));

    private static string FormatWarnings(IReadOnlyList<string> warnings) => warnings.Count == 0
        ? "无警告"
        : string.Join(Environment.NewLine, warnings.OrderBy(value => value, StringComparer.Ordinal));
}