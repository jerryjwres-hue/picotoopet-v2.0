using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式任务详情；只展示固定安全字段和已知结果合同。</summary>
public sealed class TaskDetailViewModel : ObservableObject
{
    private const string DiagnosticTaskType = "system.diagnostic_snapshot";
    private const string ResearchTaskType = "research.search";

    private readonly ControlCenterSession _session;
    private readonly TaskRecord _task;
    private string _resultText = "正在读取结果…";
    private string _resultTitle = "结果";
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
    public string CreatedAtText => _task.CreatedAt.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss");
    public string UpdatedAtText => _task.UpdatedAt.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss");
    public string AttemptText => $"{_task.AttemptCount}/{_task.MaxAttempts}";
    public string GoalText => SafeGoalSummary(_task.Payload);
    public string ErrorText => string.IsNullOrWhiteSpace(_task.ErrorMessage)
        ? "无"
        : _task.ErrorMessage;
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

    public bool IsBusy
    {
        get => _isBusy;
        private set => SetProperty(ref _isBusy, value);
    }

    /// <summary>按任务类型选择固定结果合同；未知类型绝不回退到任意文件浏览。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        if (!HasResult)
        {
            ResultTitle = "结果";
            ResultText = _task.Status == "Completed"
                ? "任务已完成，但没有关联可显示结果。"
                : "该任务当前没有可显示结果。";
            return;
        }

        IsBusy = true;
        try
        {
            switch (_task.TaskType)
            {
                case ResearchTaskType:
                    var research = await _session.GetResearchResultAsync(
                        _task.TaskId,
                        cancellationToken).ConfigureAwait(false);
                    ResultTitle = $"网络调研结果 · {research.Query}";
                    ResultText = research.Output;
                    break;
                case DiagnosticTaskType:
                    var diagnostic = await _session.GetDiagnosticResultAsync(
                        _task.TaskId,
                        cancellationToken).ConfigureAwait(false);
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

    private static string FormatDiagnostic(DiagnosticSnapshotResult result)
    {
        var lines = new List<string>
        {
            $"生成时间：{result.GeneratedAt.LocalDateTime:yyyy-MM-dd HH:mm:ss}",
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
