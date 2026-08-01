using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>展示真实连接、健康、任务和折叠诊断摘要的总览页面。</summary>
public sealed class OverviewPageViewModel : PageViewModel
{
    /// <summary>从一次会话快照创建只读总览。</summary>
    public OverviewPageViewModel(
        ControlCenterSessionSnapshot snapshot,
        string connectionText)
        : base("总览")
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ConnectionText = connectionText;
        HealthText     = snapshot.HealthText;
        LatencyText    = snapshot.LatencyText;
        StatusMessage  = snapshot.StatusMessage;
        Tasks = snapshot.State.Tasks.Tasks
            .Select(TaskRowViewModel.FromRecord)
            .ToArray();
    }

    /// <summary>当前连接状态。</summary>
    public string ConnectionText { get; }

    /// <summary>Mac Core 健康摘要。</summary>
    public string HealthText { get; }

    /// <summary>折叠诊断区显示的 p95 延迟。</summary>
    public string LatencyText { get; }

    /// <summary>当前会话状态说明。</summary>
    public string StatusMessage { get; }

    /// <summary>真实任务快照。</summary>
    public IReadOnlyList<TaskRowViewModel> Tasks { get; }

    /// <summary>当前任务数量。</summary>
    public int TaskCount => Tasks.Count;
}
