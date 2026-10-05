using System.Globalization;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式任务详情；只展示固定安全字段、Core 耐久进度和已知结果合同。</summary>
public sealed class TaskDetailViewModel : ObservableObject
{
    private const string DiagnosticTaskType = "system.diagnostic_snapshot";
    private const string ResearchTaskType = "research.search";
    private static readonly TimeSpan ProgressRefreshInterval = TimeSpan.FromSeconds(2);

    private readonly ControlCenterSession _session;
    private readonly TaskRecord _task;
    private string _resultText = "正在读取结果…";
    private string _resultTitle = "结果";
    private string _progressStageText = "尚未报告阶段";
    private string _progressValueText = "尚无可验证数值进度";
    private string _progressMessageText = "等待 Mac Core 耐久进度。";
    private string _lastActivityText = "尚无活动时间";
    private string _recentActivityText = "暂无耐久活动记录。";
    private bool _isBusy;

    public TaskDetailViewModel(ControlCenterSession session, TaskRecord task)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _task = task ?? throw new ArgumentNullException(nameof(task));
    }

    public string TaskId => _task.TaskId;
    public string Title => FriendlyTaskTitle(_task.TaskType);
    public string TaskType => _task.TaskType;
    public string StatusText => FriendlyStatus(_task.Status);
    public string SafeStatusSummaryText => SafeStatusSummary(_task);
    public string CreatedAtText => _task.CreatedAt.LocalDateTime.ToString(
        "yyyy-MM-dd HH:mm:ss",
        CultureInfo.InvariantCulture);
    public string UpdatedAtText => _task.UpdatedAt.LocalDateTime.ToString(
        "yyyy-MM-dd HH:mm:ss",
        CultureInfo.InvariantCulture);
    public string AttemptText => $"{_task.AttemptCount}/{_task.MaxAttempts}";
    public string GoalText => SafeGoalSummary(_task.Payload);
    public bool HasResult => !string.IsNullOrWhiteSpace(_task.ResultId);

    public string ResultTitle
    {
        get => _resultTitle;
        private set => SetProperty(ref _resultTitle, value);
    }

    public string ResultText
    {
        get => _resultText;
        private set => SetProperty(ref _resultText, value);
    }

    /// <summary>Core 最近一次明确上报的阶段；未知阶段不由 Windows 猜测。</summary>
    public string ProgressStageText
    {
        get => _progressStageText;
        private set => SetProperty(ref _progressStageText, value);
    }

    /// <summary>只展示服务端可验证的 N/M 或服务端百分比。</summary>
    public string ProgressValueText
    {
        get => _progressValueText;
        private set => SetProperty(ref _progressValueText, value);
    }

    /// <summary>最近一条 Core 耐久进度消息。</summary>
    public string ProgressMessageText
    {
        get => _progressMessageText;
        private set => SetProperty(ref _progressMessageText, value);
    }

    /// <summary>最近耐久活动的绝对时间，不根据本地时钟推算剩余时间。</summary>
    public string LastActivityText
    {
        get => _lastActivityText;
        private set => SetProperty(ref _lastActivityText, value);
    }

    /// <summary>最近有界活动记录；不展开 details 中的任意原始数据。</summary>
    public string RecentActivityText
    {
        get => _recentActivityText;
        private set => SetProperty(ref _recentActivityText, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set => SetProperty(ref _isBusy, value);
    }

    /// <summary>先读取 Core 耐久进度，再按任务类型读取固定结果合同。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        IsBusy = true;
        try
        {
            await LoadProgressAsync(cancellationToken);

            if (!HasResult)
            {
                ResultTitle = "结果";
                ResultText = _task.Status == "Completed"
                    ? "任务已完成，但没有关联可显示结果。"
                    : "结果尚未生成；上方会显示 Mac Core 已持久化的真实处理进度。";
                return;
            }

            switch (_task.TaskType)
            {
                case ResearchTaskType:
                    // 保留 Window Loaded 捕获的 WPF 同步上下文，结果属性始终在 UI 线程更新。
                    var research = await _session.GetResearchResultAsync(
                        _task.TaskId,
                        cancellationToken);
                    ResultTitle = $"网络调研结果 · {research.Query}";
                    ResultText = research.Output;
                    break;
                case DiagnosticTaskType:
                    var diagnostic = await _session.GetDiagnosticResultAsync(
                        _task.TaskId,
                        cancellationToken);
                    ResultTitle = "系统诊断结果";
                    ResultText = FormatDiagnostic(diagnostic);
                    break;
                default:
                    ResultTitle = "结果信息";
                    ResultText = "该任务已有结果，但当前类型尚未配置安全正文预览。任务和结果仍完整保存在 Mac Core。";
                    break;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            ResultTitle = "结果读取失败";
            ResultText = "结果暂时无法安全显示。任务记录没有被修改或删除。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>窗口存活期间以固定 2 秒节奏刷新 Core 耐久进度；关闭窗口即由调用方取消。</summary>
    public async Task RunProgressLoopAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            await Task.Delay(ProgressRefreshInterval, cancellationToken);
            await LoadProgressAsync(cancellationToken);
        }
    }

    private async Task LoadProgressAsync(CancellationToken cancellationToken)
    {
        try
        {
            var progress = await _session.GetTaskProgressAsync(
                _task.TaskId,
                cancellationToken);
            ProgressStageText = string.IsNullOrWhiteSpace(progress.Stage)
                ? "尚未报告阶段"
                : progress.Stage;
            ProgressValueText = FormatProgressValue(progress);
            ProgressMessageText = string.IsNullOrWhiteSpace(progress.LatestMessage)
                ? "Mac Core 尚未写入进度消息。"
                : progress.LatestMessage;
            LastActivityText = progress.LastActivityAt is DateTimeOffset activityAt
                ? activityAt.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
                : "尚无活动时间";
            RecentActivityText = FormatRecentActivity(progress.RecentEvents);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            ProgressStageText = "进度暂不可用";
            ProgressValueText = "未获得可验证数值进度";
            ProgressMessageText = "Mac Core 进度读取暂时失败；任务事实和结果不会因此被修改。";
            LastActivityText = "暂不可用";
            RecentActivityText = "暂时无法读取耐久活动记录。";
        }
    }

    private static string FormatProgressValue(TaskProgressSnapshot progress)
    {
        if (progress.Completed is int completed && progress.Total is int total)
        {
            return progress.Percent is double percent
                ? $"{completed}/{total} · {percent:F1}%"
                : $"{completed}/{total}";
        }
        if (progress.Percent is double serverPercent)
        {
            return $"{serverPercent:F1}%（Core 报告）";
        }
        return "尚无可验证数值进度";
    }

    private static string FormatRecentActivity(IReadOnlyList<TaskProgressEvent>? events)
    {
        if (events is null || events.Count == 0)
        {
            return "暂无耐久活动记录。";
        }

        return string.Join(
            Environment.NewLine,
            events.TakeLast(8).Select(progressEvent =>
            {
                var timestamp = progressEvent.CreatedAt.LocalDateTime.ToString(
                    "HH:mm:ss",
                    CultureInfo.InvariantCulture);
                return $"• {timestamp} · {progressEvent.Stage} · {progressEvent.Message}";
            }));
    }

    private static string SafeGoalSummary(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object)
        {
            return "未提供可显示的任务目标摘要。";
        }
        foreach (var name in new[] { "query", "goal", "objective", "title", "prompt" })
        {
            if (payload.TryGetProperty(name, out var value)
                && value.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(value.GetString()))
            {
                return value.GetString()!;
            }
        }
        return "任务参数已保存；此页面不展开任意原始载荷。";
    }

    private static string SafeStatusSummary(TaskRecord task)
    {
        if (task.Status == "Failed")
        {
            return string.IsNullOrWhiteSpace(task.ErrorCode)
                ? "任务执行失败。详细信息已记录，可从任务中心创建重试任务。"
                : $"任务执行失败（错误码：{task.ErrorCode}）。详细信息已记录，可从任务中心创建重试任务。";
        }

        return task.Status switch
        {
            "Cancelled" => "任务已安全取消，不会继续执行。",
            "Archived" => "任务已归档，可在“已删除”中恢复。",
            "Completed" when !string.IsNullOrWhiteSpace(task.ResultId) => "任务已完成，可在下方查看结果。",
            "Completed" => "任务已完成，但当前没有关联可显示结果。",
            "Running" => "任务正在处理；处理阶段和活动以 Mac Core 耐久进度为准。",
            "Queued" => "任务正在等待执行；排队状态由 Mac Core 管理。",
            _ => "任务状态由 Mac Core 管理。",
        };
    }

    private static string FormatDiagnostic(DiagnosticSnapshotResult result)
    {
        var generatedAt = result.GeneratedAt.LocalDateTime.ToString(
            "yyyy-MM-dd HH:mm:ss",
            CultureInfo.InvariantCulture);
        var lines = new List<string>
        {
            $"生成时间：{generatedAt}",
            $"Core：{result.Core?.HealthState ?? "未返回"}",
            $"Worker：{result.Worker?.State ?? "未返回"}",
        };
        if (result.Checks.Count > 0)
        {
            lines.Add("");
            lines.Add("检查项：");
            lines.AddRange(result.Checks.Select(check =>
                $"• {check.Name}：{check.Status} ({check.ReasonCode})"));
        }
        if (result.Warnings.Count > 0)
        {
            lines.Add("");
            lines.Add("提醒：");
            lines.AddRange(result.Warnings.Select(warning => $"• {warning}"));
        }
        return string.Join(Environment.NewLine, lines);
    }

    private static string FriendlyTaskTitle(string taskType) => taskType switch
    {
        DiagnosticTaskType => "系统诊断",
        ResearchTaskType => "网络调研",
        "business.local_intelligence.v1" => "业务数据分析",
        "creative.content_plan.v1" => "内容方案",
        "autonomous.discovery.v1" => "自主调研",
        "autonomous.goal_synthesis.v1" => "目标分析",
        "autonomous.goal_handoff.v1" => "结果交接",
        "system.noop" => "系统任务",
        _ => "任务详情",
    };

    private static string FriendlyStatus(string status) => status switch
    {
        "Queued" => "等待执行",
        "Running" => "处理中",
        "Completed" => "已完成",
        "Failed" => "失败",
        "Cancelled" => "已取消",
        "Archived" => "已归档",
        _ => status,
    };
}
